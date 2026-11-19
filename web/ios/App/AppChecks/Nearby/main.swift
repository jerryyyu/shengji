// The code-to-key derivation of App/NearbyPlugin.swift, checked without Xcode:
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
let full = NearbyKey.derive(code: "K7Q2MX", salt: salt, iterations: 200_000)
expect(hex(full) == "a9f7e5655d67cf662eded9f7475ab2eac064b14f61e2d5a617b30909d5869e4e",
       "known answer at 200,000 iterations, got \(hex(full))")

let key = NearbyKey.derive(code: "K7Q2MX", salt: salt)
expect(key?.count == 32, "a 32-byte key")
expect(key == NearbyKey.derive(code: "K7Q2MX", salt: salt), "the same code and salt give the same key")
expect(key == NearbyKey.derive(code: "k7q2mx", salt: salt), "the code is upper-cased")
expect(key != NearbyKey.derive(code: "K7Q2MX", salt: otherSalt), "a different salt gives a different key")
expect(key != NearbyKey.derive(code: "K7Q2MY", salt: salt), "a different code gives a different key")
expect(key != NearbyKey.derive(code: "K7Q2MX", salt: salt, iterations: NearbyKey.iterations - 1),
       "the iteration count is part of the key")

expect(NearbyKey.normalized("k7q2mx") == "K7Q2MX", "codes are upper-cased")
for bad in ["", "K7Q2M", "K7Q2MXX", "K7Q2M0", "K7Q2MI", "K7Q2M ", "K7Q2M\u{00C9}"] {
    expect(NearbyKey.normalized(bad) == nil, "\(bad.debugDescription) is not a nearby code")
}

let names = (0..<200).map { _ in NearbyKey.randomName(8) }
expect(names.allSatisfy { $0.count == 8 && $0.allSatisfy(NearbyKey.alphabet.contains) },
       "service names are 8 characters of the code alphabet")
expect(Set(names).count == names.count, "service names do not repeat")
expect(NearbyKey.randomBytes(NearbyKey.saltBytes).count == 16, "a 16-byte salt")

let t0 = Date()
_ = NearbyKey.derive(code: "K7Q2MX", salt: salt)
print(String(format: "one derivation at %d iterations: %.0f ms on this machine",
             NearbyKey.iterations, Date().timeIntervalSince(t0) * 1000))

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("nearby key derivation: all passed")
