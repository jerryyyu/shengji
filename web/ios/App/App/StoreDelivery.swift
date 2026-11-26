import Foundation

/// One verified App Store transaction as the page receives it.
struct DeliveredTransaction: Equatable {
    let id: UInt64
    let productId: String
    let jws: String

    /// What the bridge sends: the id the page acknowledges with, as a string
    /// (a JavaScript number cannot hold every UInt64).
    var payload: [String: Any] {
        ["transactionId": String(id), "productId": productId, "jws": jws]
    }
}

/// The App Store's unfinished transactions, as StoreDelivery uses them.
protocol StoreLedger {
    /// Verified transactions not finished yet, which StoreKit delivers again
    /// at every launch until they are.
    func unfinished() async -> [DeliveredTransaction]
    /// Finish the unfinished transaction `id`; false when there is none.
    func finish(id: UInt64) async -> Bool
}

/// The delivery rule of the Shop: a purchase, an update and a restore hand
/// the page a transaction and never finish it. Only the page's
/// acknowledgement, sent after the server has recorded the purchase,
/// finishes it. A transaction the server never recorded (no listener yet,
/// the app quit, no network) stays unfinished, so `pending()` hands it over
/// again at the next launch.
final class StoreDelivery {
    private let ledger: StoreLedger

    init(ledger: StoreLedger) {
        self.ledger = ledger
    }

    /// Every transaction the server may not have recorded yet.
    func pending() async -> [[String: Any]] {
        await ledger.unfinished().map(\.payload)
    }

    /// The page's acknowledgement of `transactionId`: finish it now. False
    /// for an id that is not a number or not unfinished.
    func acknowledge(_ transactionId: String) async -> Bool {
        guard let id = UInt64(transactionId) else { return false }
        return await ledger.finish(id: id)
    }
}

/// Hands each update to the page on the queue the bridge adds and removes
/// listeners on, so a delivery never races a listener's registration or
/// removal (StoreKit's update stream runs on its own task).
final class UpdateForwarder {
    private let queue: DispatchQueue
    private let send: ([String: Any]) -> Void

    init(queue: DispatchQueue, send: @escaping ([String: Any]) -> Void) {
        self.queue = queue
        self.send = send
    }

    func forward(_ transaction: DeliveredTransaction) {
        let payload = transaction.payload
        queue.async { self.send(payload) }
    }
}
