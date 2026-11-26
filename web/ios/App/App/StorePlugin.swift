import Foundation
import Capacitor
import StoreKit
import os

/// In-app purchases for the Shop (StoreKit 2). The server is the record of what
/// a player owns: every verified transaction is handed to the page as its JWS,
/// which the page sends on for the server to check, so the app keeps no copy.
/// - `products({ids})` resolves `{products: [{id, displayName, displayPrice}]}`
///   in the order asked; an id the App Store does not know is left out.
/// - `purchase({id})` resolves `{status: "purchased", jws, productId}`,
///   `{status: "cancelled"}`, `{status: "pending"}` or `{status: "unverified"}`.
///   A verified purchase is finished once the page has its JWS: a lost
///   delivery comes back through `restore()` or `entitlements()`. An
///   unverified one is never finished, so StoreKit offers it again.
/// - `restore()` syncs with the App Store (it may ask the player to sign in),
///   then resolves `{transactions: [{jws, productId}]}` from the current
///   entitlements; `entitlements()` resolves the same without the sync, so it
///   never prompts. Only verified, unrevoked transactions are listed.
/// - `storefront()` resolves `{countryCode}` (ISO 3166-1 alpha-3) or null.
/// - Event `transaction` `{jws, productId}`: a verified transaction that
///   arrived outside a purchase call (Ask to Buy, another device, a refund or
///   its revocation); it is finished once sent.
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
        CAPPluginMethod(name: "storefront", returnType: CAPPluginReturnPromise)
    ]

    private static let log = Logger(subsystem: "com.jerryyu.shengji", category: "store")

    /// Listens for the whole life of the plugin: a transaction that is not
    /// collected here stays unfinished and StoreKit redelivers it every launch.
    private var updatesTask: Task<Void, Never>?

    override public func load() {
        updatesTask = Task.detached { [weak self] in
            for await result in Transaction.updates {
                guard case .verified(let transaction) = result else {
                    ShengjiStorePlugin.log.error("update unverified")
                    continue
                }
                let productId = transaction.productID
                guard let self = self else { return }
                // A revocation is forwarded too: its JWS carries the revocation
                // date, and the server decides what it removes. The event is
                // retained until the page listens, so one that arrives at
                // launch, before the page subscribes, still reaches it.
                self.notifyListeners("transaction", data: ["jws": result.jwsRepresentation, "productId": productId],
                                     retainUntilConsumed: true)
                ShengjiStorePlugin.log.info("update forwarded \(productId, privacy: .public)")
                await transaction.finish()
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
        Task {
            do {
                guard let product = try await Product.products(for: [id]).first else {
                    ShengjiStorePlugin.log.error("purchase: no product \(id, privacy: .public)")
                    call.reject("product not found", "product_not_found")
                    return
                }
                switch try await product.purchase() {
                case .success(let result):
                    switch result {
                    case .verified(let transaction):
                        call.resolve(["status": "purchased", "jws": result.jwsRepresentation,
                                      "productId": transaction.productID])
                        await transaction.finish()
                        ShengjiStorePlugin.log.info("purchased \(id, privacy: .public)")
                    case .unverified:
                        ShengjiStorePlugin.log.error("purchase unverified \(id, privacy: .public)")
                        call.resolve(["status": "unverified"])
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

    private static func currentEntitlements() async -> [[String: Any]] {
        var list: [[String: Any]] = []
        for await result in Transaction.currentEntitlements {
            guard case .verified(let transaction) = result, transaction.revocationDate == nil else { continue }
            list.append(["jws": result.jwsRepresentation, "productId": transaction.productID])
        }
        return list
    }
}
