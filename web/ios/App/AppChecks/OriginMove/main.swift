// The pure part of App/OriginMove.swift, checked without Xcode:
//   swiftc -o /tmp/origin_move_check web/ios/App/App/OriginMove.swift \
//     web/ios/App/AppChecks/OriginMove/main.swift && /tmp/origin_move_check
import Foundation

var failures = 0

func check(_ ok: Bool, _ what: String, line: Int = #line) {
    if !ok {
        failures += 1
        print("line \(line): \(what)")
    }
}

let now = Date()  // a cookie's expiry is capped relative to the clock (about 400 days)
let later = now.addingTimeInterval(86400 * 20)

func cookie(_ name: String, _ value: String, _ domain: String, expires: Date? = later,
            secure: Bool = true, httpOnly: Bool = true, sameSite: String? = "lax") -> HTTPCookie {
    var p: [HTTPCookiePropertyKey: Any] = [.name: name, .value: value, .domain: domain, .path: "/"]
    if let expires = expires { p[.expires] = expires }
    if secure { p[.secure] = "TRUE" }
    if httpOnly { p[HTTPCookiePropertyKey("HttpOnly")] = "TRUE" }
    if let sameSite = sameSite { p[.sameSitePolicy] = sameSite }
    return HTTPCookie(properties: p)!
}

// which launches move
check(OriginMove.applies(to: URL(string: "https://playshengji.com")), "playshengji.com moves")
check(OriginMove.applies(to: URL(string: "https://PlayShengJi.com/")), "the host is case-blind")
check(!OriginMove.applies(to: URL(string: "https://shengji.fly.dev")), "the old host does not move")
check(!OriginMove.applies(to: URL(string: "http://playshengji.com")), "http does not move")
check(!OriginMove.applies(to: URL(string: "http://192.168.1.20:8765")), "a test server does not move")
check(!OriginMove.applies(to: nil), "the bundled page does not move")

// the session cookie moves with its value and attributes
let session = cookie("sj_session", "tok-123", "shengji.fly.dev")
let moved = OriginMove.movedCookies([session], to: "playshengji.com", now: now)
check(moved.count == 1, "one cookie moves")
if let c = moved.first {
    check(c.name == "sj_session" && c.value == "tok-123", "same name and value")
    check(OriginMove.domain(c.domain, is: "playshengji.com"), "on the new host, got \(c.domain)")
    check(c.path == "/", "same path")
    check(c.isSecure && c.isHTTPOnly, "still Secure and HttpOnly")
    check(c.sameSitePolicy == .sameSiteLax, "still SameSite=Lax")
    check(abs((c.expiresDate ?? .distantPast).timeIntervalSince(later)) < 1, "same expiry")
}
// a dotted domain is the same host
check(OriginMove.movedCookies([cookie("a", "1", ".shengji.fly.dev")], to: "playshengji.com", now: now).count == 1,
      "a dotted old-host cookie moves")
// another host's cookies stay where they are
check(OriginMove.movedCookies([cookie("a", "1", "other.example"), cookie("b", "2", "fly.dev"),
                               cookie("c", "3", "x.shengji.fly.dev")], to: "playshengji.com", now: now).isEmpty,
      "no other host's cookie moves")
// a name the new host already has is kept
let kept = OriginMove.movedCookies([session, cookie("sj_session", "new", "playshengji.com")],
                                   to: "playshengji.com", now: now)
check(kept.isEmpty, "the new host's own session is not replaced")
// an expired cookie is not carried; a session-only one is
check(OriginMove.movedCookies([cookie("a", "1", "shengji.fly.dev", expires: now.addingTimeInterval(-1))],
                              to: "playshengji.com", now: now).isEmpty, "an expired cookie stays")
let sessionOnly = OriginMove.movedCookies([cookie("a", "1", "shengji.fly.dev", expires: nil, secure: false,
                                                  httpOnly: false, sameSite: nil)], to: "playshengji.com", now: now)
check(sessionOnly.count == 1 && sessionOnly[0].expiresDate == nil && !sessionOnly[0].isSecure
      && !sessionOnly[0].isHTTPOnly, "a plain session-only cookie moves as it is")

// whether the old host was signed in
check(OriginMove.hadSession([session], now: now), "a live session")
check(!OriginMove.hadSession([cookie("sj_session", "t", "shengji.fly.dev", expires: now)], now: now),
      "an expired session is none")
check(!OriginMove.hadSession([cookie("sj_session", "t", "playshengji.com")], now: now),
      "only the old host's session counts")
check(!OriginMove.hadSession([cookie("other", "t", "shengji.fly.dev")], now: now), "another cookie is none")

// what the storage read returned
check(OriginMove.storageEntries("{\"a\":\"1\",\"b\":\"x y\"}") == ["a": "1", "b": "x y"], "string entries")
check(OriginMove.storageEntries("{\"a\":\"1\",\"n\":2,\"o\":{}}") == ["a": "1"], "strings only")
check(OriginMove.storageEntries("[1]").isEmpty, "an array is nothing")
check(OriginMove.storageEntries("not json").isEmpty, "garbage is nothing")
check(OriginMove.storageEntries(nil).isEmpty, "no result is nothing")
check(OriginMove.storageEntries(7).isEmpty, "a number is nothing")

// the handoff is one assignment of valid JSON, quotes and newlines escaped
if let s = OriginMove.handoffScript(origin: "https://playshengji.com",
                                    entries: ["k\"</script>": "v\n\u{2028}"], session: true) {
    let prefix = "window.__shengjiOriginMove = ", suffix = ";"
    check(s.hasPrefix(prefix) && s.hasSuffix(suffix), "one assignment: \(s)")
    let json = String(s.dropFirst(prefix.count).dropLast(suffix.count))
    let back = (try? JSONSerialization.jsonObject(with: Data(json.utf8))) as? [String: Any]
    check(back?["origin"] as? String == "https://playshengji.com", "origin round-trips")
    check(back?["session"] as? Bool == true, "session round-trips")
    check((back?["entries"] as? [String: String]) == ["k\"</script>": "v\n\u{2028}"], "entries round-trip")
    check(!json.contains("\n"), "no raw newline in the script")
} else {
    check(false, "the handoff script was not made")
}
check(OriginMove.handoffScript(origin: "https://playshengji.com", entries: [:], session: false) ==
      "window.__shengjiOriginMove = {\"entries\":{},\"origin\":\"https:\\/\\/playshengji.com\",\"session\":false};",
      "the empty handoff")

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("origin move: all passed")
