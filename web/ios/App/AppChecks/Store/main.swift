// The Shop's delivery rule (App/StoreDelivery.swift), checked without Xcode:
//   swiftc -o /tmp/store_delivery_check web/ios/App/App/StoreDelivery.swift \
//     web/ios/App/AppChecks/Store/main.swift && /tmp/store_delivery_check
import Foundation

/// StoreKit's ledger in memory: a transaction stays until it is finished,
/// across "launches" (a new StoreDelivery over the same ledger).
final class FakeLedger: StoreLedger {
    var open: [DeliveredTransaction] = []
    func unfinished() async -> [DeliveredTransaction] { open }
    func finish(id: UInt64) async -> Bool {
        guard let i = open.firstIndex(where: { $0.id == id }) else { return false }
        open.remove(at: i)
        return true
    }
}

var failures = 0
func expect(_ ok: Bool, _ what: String, line: Int = #line) {
    if !ok {
        failures += 1
        print("line \(line): \(what)")
    }
}
func ids(_ list: [[String: Any]]) -> [String] { list.compactMap { $0["transactionId"] as? String } }

let semaphore = DispatchSemaphore(value: 0)
Task {
    let ledger = FakeLedger()
    let goat = DeliveredTransaction(id: 2_000_000_111, productId: "com.jerryyu.shengji.companion.goat", jws: "a.b.c")
    let panda = DeliveredTransaction(id: 18_446_744_073_709_551_000, productId: "com.jerryyu.shengji.companion.panda", jws: "d.e.f")

    // an update arrives while no page listens: nothing finishes it
    ledger.open.append(goat)
    var delivery = StoreDelivery(ledger: ledger)
    // a purchase whose grant is interrupted (the app quits before the server answers)
    ledger.open.append(panda)
    expect(goat.payload["transactionId"] as? String == "2000000111", "the id travels as a string")
    expect(panda.payload["transactionId"] as? String == "18446744073709551000", "a large id keeps every digit")

    // relaunch: both are handed over again
    delivery = StoreDelivery(ledger: ledger)
    expect(ids(await delivery.pending()) == ["2000000111", "18446744073709551000"], "unacknowledged ones come back")

    // the server records the goat; the page acknowledges it
    expect(await delivery.acknowledge("2000000111"), "an acknowledged transaction finishes")
    expect(ids(await delivery.pending()) == ["18446744073709551000"], "only the unacknowledged one is left")
    expect(!(await delivery.acknowledge("2000000111")), "a second acknowledgement finds nothing")
    expect(!(await delivery.acknowledge("not-a-number")), "a malformed id finishes nothing")

    // the next launch recovers the panda and finishes it after its grant
    delivery = StoreDelivery(ledger: ledger)
    expect(ids(await delivery.pending()) == ["18446744073709551000"], "recovery at relaunch")
    expect(await delivery.acknowledge("18446744073709551000"), "recovered and acknowledged")
    expect(await delivery.pending().isEmpty, "nothing left")
    semaphore.signal()
}
semaphore.wait()

// Updates arriving from StoreKit's task while the page adds and removes its
// listener: every delivery runs on the bridge's queue, never beside a change
// to the listener list.
final class Listeners {
    let key = DispatchSpecificKey<Int>()
    let queue = DispatchQueue(label: "bridge")
    var list: [Int] = []
    var offQueue = 0
    var delivered = 0
    init() { queue.setSpecific(key: key, value: 1) }
    private func onQueue() -> Bool { DispatchQueue.getSpecific(key: key) == 1 }
    func add(_ id: Int) { if !onQueue() { offQueue += 1 }; list.append(id) }
    func remove(_ id: Int) { if !onQueue() { offQueue += 1 }; list.removeAll { $0 == id } }
    func notify(_ payload: [String: Any]) {
        if !onQueue() { offQueue += 1 }
        _ = list.count
        if payload["transactionId"] != nil { delivered += 1 }
    }
}

func race(_ forward: @escaping (Listeners, DeliveredTransaction) -> Void) -> Listeners {
    let hub = Listeners()
    let group = DispatchGroup()
    let workers = DispatchQueue(label: "storekit", attributes: .concurrent)
    for i in 0..<400 {
        let t = DeliveredTransaction(id: UInt64(i + 1), productId: "p", jws: "j")
        group.enter()
        workers.async { forward(hub, t); group.leave() }
        group.enter()
        hub.queue.async { if i % 2 == 0 { hub.add(i) } else { hub.remove(i - 1) }; group.leave() }
    }
    group.wait()
    hub.queue.sync {}
    return hub
}

let serialized = race { hub, t in UpdateForwarder(queue: hub.queue, send: hub.notify).forward(t) }
expect(serialized.offQueue == 0, "an update is delivered off the bridge queue \(serialized.offQueue) times")
expect(serialized.delivered == 400, "every update reaches the page (\(serialized.delivered) of 400)")
// the check sees the race it guards against: a delivery straight from the StoreKit task
let direct = race { hub, t in hub.notify(t.payload) }
expect(direct.offQueue > 0, "a direct delivery is seen off the bridge queue")
if failures > 0 {
    print("FAIL: \(failures)")
    exit(1)
}
print("store delivery: ok")
