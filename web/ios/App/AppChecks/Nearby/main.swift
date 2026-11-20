// The code-to-key derivation and the wake-lock reasons of App/NearbyPlugin.swift,
// checked without Xcode:
//   swiftc -D NEARBY_KEY_ONLY -o /tmp/nearby_key_check web/ios/App/App/NearbyPlugin.swift \
//     web/ios/App/AppChecks/Nearby/main.swift && /tmp/nearby_key_check
import Foundation

var failures = 0

func expect(_ ok: Bool, _ what: String, line: Int = #line) {
    if !ok {
        failures += 1
        print("line \(line): \(what)")
    }
}

func hex(_ data: Data?) -> String { data.map { $0.map { String(format: "%02x", $0) }.joined() } ?? "nil" }

let salt = Data((0..<16).map { UInt8($0) })
let otherSalt = Data((0..<16).map { UInt8(255 - $0) })

// PBKDF2-HMAC-SHA256 of the upper-cased code, against Python's
// hashlib.pbkdf2_hmac("sha256", code, salt, iterations, 32)
let short = NearbyKey.derive(code: "passwd", salt: Data("salt".utf8), iterations: 1)
expect(hex(short) == "7ca4b063fa2da5d7103e47f7ed819f41d98bef22f4b3297d1b8bf41cfcf05df8",
       "known answer at 1 iteration, got \(hex(short))")
let full = NearbyKey.derive(code: "K7Q2M", salt: salt, iterations: 150_000)
expect(hex(full) == "451cefc621a3c5f0eeb1d90f8328e4567d1a715f3ba541625a11356839ad39be",
       "known answer at 150,000 iterations, got \(hex(full))")
expect(NearbyKey.iterations == 150_000, "the key uses 150,000 iterations")

let key = NearbyKey.derive(code: "K7Q2M", salt: salt)
expect(key?.count == 32, "a 32-byte key")
expect(key == NearbyKey.derive(code: "K7Q2M", salt: salt), "the same code and salt give the same key")
expect(key == NearbyKey.derive(code: "k7q2m", salt: salt), "the code is upper-cased")
expect(key != NearbyKey.derive(code: "K7Q2M", salt: otherSalt), "a different salt gives a different key")
expect(key != NearbyKey.derive(code: "K7Q2MY", salt: salt), "a different code gives a different key")
expect(key != NearbyKey.derive(code: "K7Q2M", salt: salt, iterations: NearbyKey.iterations - 1),
       "the iteration count is part of the key")

expect(NearbyKey.normalized("k7q2m") == "K7Q2M", "codes are upper-cased")
for bad in ["", "K7Q2", "K7Q2MX", "K7Q20", "K7Q2I", "K7Q2 ", "K7Q2\u{00C9}"] {
    expect(NearbyKey.normalized(bad) == nil, "\(bad.debugDescription) is not a nearby code")
}

let names = (0..<200).map { _ in NearbyKey.randomName(8) }
expect(names.allSatisfy { $0.count == 8 && $0.allSatisfy(NearbyKey.alphabet.contains) },
       "service names are 8 characters of the code alphabet")
expect(Set(names).count == names.count, "service names do not repeat")
expect(NearbyKey.randomBytes(NearbyKey.saltBytes).count == 16, "a 16-byte salt")

// The screen stays awake while a game or a nearby session is live, and the
// idle timer returns only when both have ended.
var awake = AwakeReasons()
expect(!awake.any, "no reason, no wake lock")
awake.game = true
expect(awake.any, "a game keeps the screen awake")
awake.nearby = true
awake.game = false
expect(awake.any, "a nearby session alone keeps the screen awake")
awake.game = true
expect(awake.any, "both reasons keep the screen awake")
awake.nearby = false
expect(awake.any, "the game still holds after the nearby session ends")
awake.game = false
expect(!awake.any, "the idle timer returns once both have ended")

// A listener left waiting or failing is made again: the waits double from
// 1 s to 8 s, a fresh one starts the waits over, a first listener that keeps
// failing rejects after three retries (never while the permission is the
// cause), and one that was up is advertised again on the app's return.
var retry = ListenerRetry()
expect([retry.nextDelay(), retry.nextDelay(), retry.nextDelay(), retry.nextDelay(), retry.nextDelay()] == [1, 2, 4, 8, 8],
       "listener retries back off 1, 2, 4, 8, 8 s")
retry.ready()
expect(retry.nextDelay() == 1, "a listener that came up starts the waits over")
retry = ListenerRetry()
expect(retry.failed(wasUp: false, policyDenied: false) == .retry, "a first failure retries")
expect(retry.failed(wasUp: false, policyDenied: false) == .retry, "a second failure retries")
expect(retry.failed(wasUp: false, policyDenied: false) == .retry, "a third failure retries")
expect(retry.failed(wasUp: false, policyDenied: false) == .reject, "a fourth failure rejects the host call")
expect(retry.failed(wasUp: false, policyDenied: true) == .retry, "a denied permission keeps retrying until it is granted")
expect(retry.failed(wasUp: true, policyDenied: false) == .lost, "a listener that was up is advertised again on return")
retry.ready()
expect(retry.failed(wasUp: false, policyDenied: false) == .retry, "ready clears the failures")

// A seat's resume looks for 4 s at a time (a first look 12 s), and tries
// the table its last link went to before any other.
expect(JoinPlan.findTimeout(resuming: true) == 4, "a resume looks 4 s at a time")
expect(JoinPlan.findTimeout(resuming: false) == 12, "a first look keeps 12 s")
let found = ["AAAA", "LAST", "BBBB"]
let order = JoinPlan.ordered(found, name: { $0 }, prefer: "LAST")
expect(order.last == "LAST", "the last host is popped (tried) first, got \(order)")
expect(order.dropLast() == ["AAAA", "BBBB"], "the others keep their order")
expect(JoinPlan.ordered(found, name: { $0 }, prefer: nil) == found, "no last host, no change")
expect(JoinPlan.ordered(found, name: { $0 }, prefer: "GONE") == found, "a last host not found, no change")

// The look starts over only when the network comes back: satisfied after
// unsatisfied, not the first report or a repeat.
var path = PathWatch()
expect(!path.update(true), "the first report is no regain")
expect(!path.update(true), "a repeat is no regain")
expect(!path.update(false), "losing the path is no regain")
expect(!path.update(false), "still down")
expect(path.update(true), "back after down is a regain")
expect(!path.update(true), "and only once")

let t0 = Date()
_ = NearbyKey.derive(code: "K7Q2M", salt: salt)
print(String(format: "one derivation at %d iterations: %.0f ms on this machine",
             NearbyKey.iterations, Date().timeIntervalSince(t0) * 1000))

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("nearby key derivation: all passed")
