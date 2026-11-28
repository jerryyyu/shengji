import Foundation
import Capacitor
import StoreKit
import os

/// In-app purchases for the Shop (StoreKit 2). The server is the record of what
/// a player owns: every transaction is handed to the page as its JWS with its
/// `transactionId` (and `unverified: true` when StoreKit could not verify it on
/// the device), the page sends it on for the server to check, and
/// only the page's `finish({transactionId})` after the server recorded it
/// finishes it (StoreDelivery.swift). Until then StoreKit keeps it and
/// `pending()` hands it over again, at this launch or the next.
/// - `products({ids})` resolves `{products: [{id, displayName, displayPrice}]}`
///   in the order asked; an id the App Store does not know is left out.
/// - `purchase({id, appAccountToken})` passes the account's token (a UUID
///   from the server) to StoreKit, so Apple signs which account paid, and resolves `{status: "purchased", jws, productId, transactionId}`,
///   `{status: "cancelled"}`, `{status: "pending"}` or `{status: "unverified",
///   jws, productId, transactionId, unverified: true}`. Nothing is finished here.
/// - `pending()` resolves `{transactions: [{jws, productId, transactionId}]}`:
///   every transaction not finished yet, an unverified one flagged.
/// - `finish({transactionId})` resolves `{finished}`: false when that
///   transaction is not unfinished (already finished, or unknown).
/// - `restore()` syncs with the App Store (it may ask the player to sign in),
///   then resolves `{transactions: [{jws, productId, transactionId}]}` from the current
///   entitlements; `entitlements()` resolves the same without the sync, so it
///   never prompts. Only unrevoked transactions are listed, an unverified
///   one flagged.
/// - `storefront()` resolves `{countryCode}` (ISO 3166-1 alpha-3) or null.
/// - Event `transaction` `{jws, productId, transactionId}`: a transaction
///   (an unverified one flagged) that arrived outside a purchase call (Ask to Buy, another
///   device, a refund or its revocation). It is not finished either: with no
///   page listening it is still in `pending()`.
/// Log lines carry event names and product ids only, never a JWS or a
/// transaction id.
@objc(ShengjiStorePlugin)
public class ShengjiStorePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiStorePlugin"
    public let jsName = "ShengjiStore"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "products", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "purchase", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "restore", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "entitlements", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "storefront", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "pending", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "finish", returnType: CAPPluginReturnPromise)
    ]

    private let delivery = StoreDelivery(ledger: StoreKitLedger())

    /// Delivers updates on the bridge's queue, where listeners are added and
    /// removed.
    private lazy var forwarder = UpdateForwarder(
        queue: (bridge as? CapacitorBridge)?.dispatchQueue ?? DispatchQueue.main
    ) { [weak self] payload in
        self?.notifyListeners("transaction", data: payload, retainUntilConsumed: true)
    }

    private static let log = Logger(subsystem: "com.jerryyu.shengji", category: "store")

    /// Listens for the whole life of the plugin and forwards each update to
    /// the page; StoreKit keeps it unfinished until the page acknowledges it.
    private var updatesTask: Task<Void, Never>?

    override public func load() {
        _ = forwarder
        updatesTask = Task.detached { [weak self] in
            for await result in Transaction.updates {
                guard let self = self else { return }
                // A revocation is forwarded too: its JWS carries the revocation
                // date, and the server decides what it removes. So is an
                // unverified one, flagged: the server checks its JWS itself.
                let delivered = ShengjiStorePlugin.delivered(result)
                let productId = delivered.productId
                if delivered.unverified { ShengjiStorePlugin.log.error("update unverified") }
                self.forwarder.forward(delivered)
                ShengjiStorePlugin.log.info("update forwarded \(productId, privacy: .public)")
            }
        }
    }

    deinit {
        updatesTask?.cancel()
    }

    // MARK: JS methods

    @objc func products(_ call: CAPPluginCall) {
        let ids = (call.getArray("ids") ?? []).compactMap { $0 as? String }
        guard !ids.isEmpty else {
            call.resolve(["products": [Any]()])
            return
        }
        Task {
            do {
                let found = try await Product.products(for: ids)
                let byId = Dictionary(found.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
                let list: [[String: Any]] = ids.compactMap { id in
                    guard let product = byId[id] else { return nil }
                    return ["id": product.id, "displayName": product.displayName, "displayPrice": product.displayPrice]
                }
                ShengjiStorePlugin.log.info("products \(list.count, privacy: .public) of \(ids.count, privacy: .public)")
                call.resolve(["products": list])
            } catch {
                ShengjiStorePlugin.log.error("products failed")
                call.reject("could not load products", "store_error", error)
            }
        }
    }

    @objc func purchase(_ call: CAPPluginCall) {
        guard let id = call.getString("id"), !id.isEmpty else {
            call.reject("id must be a non-empty string", "bad_request")
            return
        }
        var options: Set<Product.PurchaseOption> = []
        if let raw = call.getString("appAccountToken") {
            guard let token = UUID(uuidString: raw) else {
                call.reject("appAccountToken must be a UUID", "bad_request")
                return
            }
            options.insert(.appAccountToken(token))
        }
        Task {
            do {
                guard let product = try await Product.products(for: [id]).first else {
                    ShengjiStorePlugin.log.error("purchase: no product \(id, privacy: .public)")
                    call.reject("product not found", "product_not_found")
                    return
                }
                switch try await product.purchase(options: options) {
                case .success(let result):
                    switch result {
                    case .verified(let transaction):
                        let delivered = DeliveredTransaction(id: transaction.id, productId: transaction.productID,
                                                             jws: result.jwsRepresentation)
                        call.resolve(delivered.payload.merging(["status": "purchased"]) { a, _ in a })
                        ShengjiStorePlugin.log.info("purchased \(id, privacy: .public)")
                    case .unverified:
                        // still the App Store's purchase: handed over, flagged, for the server to check
                        ShengjiStorePlugin.log.error("purchase unverified \(id, privacy: .public)")
                        call.resolve(Self.delivered(result).payload.merging(["status": "unverified"]) { a, _ in a })
                    }
                case .userCancelled:
                    ShengjiStorePlugin.log.info("purchase cancelled \(id, privacy: .public)")
                    call.resolve(["status": "cancelled"])
                case .pending:
                    ShengjiStorePlugin.log.info("purchase pending \(id, privacy: .public)")
                    call.resolve(["status": "pending"])
                @unknown default:
                    ShengjiStorePlugin.log.error("purchase: unknown result \(id, privacy: .public)")
                    call.reject("unknown purchase result", "store_error")
                }
            } catch {
                ShengjiStorePlugin.log.error("purchase failed \(id, privacy: .public)")
                call.reject("purchase failed", "store_error", error)
            }
        }
    }

    @objc func restore(_ call: CAPPluginCall) {
        Task {
            do {
                try await AppStore.sync()
            } catch {
                ShengjiStorePlugin.log.error("restore sync failed")
                call.reject("restore failed", "store_error", error)
                return
            }
            let list = await Self.currentEntitlements()
            ShengjiStorePlugin.log.info("restore \(list.count, privacy: .public)")
            call.resolve(["transactions": list])
        }
    }

    @objc func entitlements(_ call: CAPPluginCall) {
        Task {
            let list = await Self.currentEntitlements()
            ShengjiStorePlugin.log.info("entitlements \(list.count, privacy: .public)")
            call.resolve(["transactions": list])
        }
    }

    @objc func storefront(_ call: CAPPluginCall) {
        Task {
            if let code = await Storefront.current?.countryCode {
                call.resolve(["countryCode": code])
            } else {
                call.resolve(["countryCode": NSNull()])
            }
        }
    }

    @objc func pending(_ call: CAPPluginCall) {
        Task {
            let list = await delivery.pending()
            ShengjiStorePlugin.log.info("pending \(list.count, privacy: .public)")
            call.resolve(["transactions": list])
        }
    }

    @objc func finish(_ call: CAPPluginCall) {
        guard let id = call.getString("transactionId"), !id.isEmpty else {
            call.reject("transactionId must be a non-empty string", "bad_request")
            return
        }
        Task {
            let finished = await delivery.acknowledge(id)
            ShengjiStorePlugin.log.info("finish \(finished, privacy: .public)")
            call.resolve(["finished": finished])
        }
    }

    private static func currentEntitlements() async -> [[String: Any]] {
        var list: [[String: Any]] = []
        for await result in Transaction.currentEntitlements {
            guard result.unsafePayloadValue.revocationDate == nil else { continue }
            list.append(delivered(result).payload)
        }
        return list
    }

    /// A StoreKit result as the page receives it, verified or flagged unverified.
    static func delivered(_ result: VerificationResult<Transaction>) -> DeliveredTransaction {
        let transaction = result.unsafePayloadValue
        if case .unverified = result {
            return DeliveredTransaction(id: transaction.id, productId: transaction.productID,
                                        jws: result.jwsRepresentation, unverified: true)
        }
        return DeliveredTransaction(id: transaction.id, productId: transaction.productID,
                                    jws: result.jwsRepresentation)
    }
}

/// StoreKit's own ledger: `Transaction.unfinished`, an unverified one
/// flagged. The page finishes an unverified one only after the server's own
/// check of its JWS granted it.
struct StoreKitLedger: StoreLedger {
    func unfinished() async -> [DeliveredTransaction] {
        var list: [DeliveredTransaction] = []
        for await result in Transaction.unfinished {
            list.append(ShengjiStorePlugin.delivered(result))
        }
        return list
    }

    func finish(id: UInt64) async -> Bool {
        for await result in Transaction.unfinished {
            let transaction = result.unsafePayloadValue
            guard transaction.id == id else { continue }
            await transaction.finish()
            return true
        }
        return false
    }
}
