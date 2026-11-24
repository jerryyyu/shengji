// The pure part of App/OriginMove.swift, checked without Xcode:
//   swiftc -o /tmp/origin_move_check web/ios/App/App/OriginMove.swift \
//     web/ios/App/AppChecks/OriginMove/main.swift && /tmp/origin_move_check
import Foundation
import JavaScriptCore

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

// the handoff script, run as a page would run it: what a document at `origin` sees
func handoffSeen(by origin: String, _ script: String) -> [String: Any]? {
    let js = JSContext()!
    js.evaluateScript("var window = this; var location = { origin: \(String(reflecting: origin)) };")
    js.evaluateScript(script)
    check(js.exception == nil, "the script runs: \(js.exception?.toString() ?? "")")
    let v = js.evaluateScript("JSON.stringify(window.__shengjiOriginMove === undefined ? null : window.__shengjiOriginMove)")
    guard let text = v?.toString(), let obj = try? JSONSerialization.jsonObject(with: Data(text.utf8)) else { return nil }
    return obj as? [String: Any]
}

let tricky = ["k\"</script>": "v\n\u{2028}", "shengji.room": "AB12"]
if let s = OriginMove.handoffScript(origin: "https://playshengji.com", entries: tricky, session: true) {
    check(!s.contains("\n"), "no raw newline in the script")
    let seen = handoffSeen(by: "https://playshengji.com", s)
    check(seen?["origin"] as? String == "https://playshengji.com", "origin round-trips")
    check(seen?["session"] as? Bool == true, "session round-trips")
    check((seen?["entries"] as? [String: String]) == tricky, "entries round-trip")
    // a top-level page at any other origin never gets the snapshot
    for other in ["https://shengji.fly.dev", "capacitor://localhost", "https://playshengji.com.evil.example",
                  "https://evil.example", "http://playshengji.com", "https://playshengji.com:8443", "null"] {
        check(handoffSeen(by: other, s) == nil, "no payload at \(other)")
    }
} else {
    check(false, "the handoff script was not made")
}
if let empty = OriginMove.handoffScript(origin: "https://playshengji.com", entries: [:], session: false) {
    let seen = handoffSeen(by: "https://playshengji.com", empty)
    check((seen?["entries"] as? [String: String]) == [:] && seen?["session"] as? Bool == false, "the empty handoff")
}

// the page's confirmation
check(OriginMove.confirms(body: "imported", isMainFrame: true, scheme: "https", host: "playshengji.com", port: 0),
      "the new origin's main frame confirms")
check(OriginMove.confirms(body: "imported", isMainFrame: true, scheme: "https", host: "PlayShengJi.com", port: 443),
      "port 443 and case are the same origin")
check(!OriginMove.confirms(body: "imported", isMainFrame: false, scheme: "https", host: "playshengji.com", port: 0),
      "a subframe does not confirm")
check(!OriginMove.confirms(body: "imported", isMainFrame: true, scheme: "https", host: "shengji.fly.dev", port: 0),
      "the old origin does not confirm")
check(!OriginMove.confirms(body: "imported", isMainFrame: true, scheme: "capacitor", host: "localhost", port: 0),
      "the offline page does not confirm")
check(!OriginMove.confirms(body: "imported", isMainFrame: true, scheme: "https", host: "playshengji.com", port: 8443),
      "another port does not confirm")
check(!OriginMove.confirms(body: "yes", isMainFrame: true, scheme: "https", host: "playshengji.com", port: 0),
      "another body does not confirm")

// the ledger across launches
final class Flags: OriginMoveFlags {
    var values: [String: Bool] = [:]
    func bool(forKey key: String) -> Bool { values[key] ?? false }
    func set(_ value: Bool, forKey key: String) { values[key] = value }
}
let flags = Flags()
let ledger = OriginMoveLedger(flags: flags)
check(ledger.pending && !ledger.cookiesCopied && !ledger.imported, "a fresh install has the whole move to do")
// launch 1 is killed before the cookie copies finish: nothing is marked
check(ledger.pending && !ledger.cookiesCopied, "a killed first launch leaves the cookies to copy")
// launch 2 starts offline: the cookies copy, the offline page never confirms, the app exits
ledger.markCookiesCopied()
check(ledger.pending && ledger.cookiesCopied && !ledger.imported, "an offline launch leaves the import to do")
// launch 3 is online: the page confirms
ledger.markImported()
check(!ledger.pending, "a confirmed import ends the move")
// launch 4 and on: nothing is offered, so a sign-out or a cleared seat stays
check(!OriginMoveLedger(flags: flags).pending, "a later launch offers nothing")
check(OriginMove.cookiesKey != OriginMove.importedKey, "two flags")
// one attempt per launch, driven as the runner drives it
func launch(_ flags: Flags, _ steps: (inout OriginMoveAttempt) -> Void) -> OriginMoveAttempt {
    var a = OriginMoveAttempt(ledger: OriginMoveLedger(flags: flags))
    steps(&a)
    return a
}
// first launch offline, then the app is closed: cookies copied, the read offered,
// the offline page never confirms; nothing else is marked
let f2 = Flags()
_ = launch(f2) { a in
    check(a.cookiesSet() == .readStorage, "after the cookies the storage is read")
    check(a.read(succeeded: true), "a good read is offered")
    a.release()
    check(!a.confirmed(false), "the offline page's message is no confirmation")
}
check(OriginMoveLedger(flags: f2).pending && OriginMoveLedger(flags: f2).cookiesCopied, "offline: the import is offered again")
// the next launch online recovers: the page confirms
_ = launch(f2) { a in
    check(a.cookiesSet() == .readStorage, "the retry reads again")
    check(a.read(succeeded: true), "and offers again")
    a.release()
    check(a.confirmed(true), "the new origin's page confirms")
    check(!a.confirmed(true), "a second confirmation retires nothing more")
}
check(!OriginMoveLedger(flags: f2).pending, "recovered: nothing left")
_ = launch(f2) { a in check(a.cookiesSet() == .release, "a later launch reads nothing") }
// a launch whose read fails, or lands after the timeout, offers nothing and marks nothing
let f3 = Flags()
_ = launch(f3) { a in
    _ = a.cookiesSet()
    check(!a.read(succeeded: false), "a failed read is not offered")
    a.release()
}
_ = launch(f3) { a in
    _ = a.cookiesSet()
    a.release()                                   // the timeout came first
    check(!a.read(succeeded: true), "a read after the timeout is not offered")
    check(!a.confirmed(true), "nothing offered, nothing confirmed")
}
check(OriginMoveLedger(flags: f3).pending && !OriginMoveLedger(flags: f3).imported, "failed reads leave the import to do")
// a launch terminated before the cookie copies finished marks nothing
let f4 = Flags()
_ = launch(f4) { a in a.release() }
check(!OriginMoveLedger(flags: f4).cookiesCopied, "a killed launch copies the cookies next time")

let us = UserDefaults(suiteName: "origin-move-check")!
us.removePersistentDomain(forName: "origin-move-check")
let real = OriginMoveLedger(flags: us)
real.markCookiesCopied()
check(real.cookiesCopied && !real.imported && us.bool(forKey: OriginMove.cookiesKey), "UserDefaults keeps the flags")
us.removePersistentDomain(forName: "origin-move-check")

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("origin move: all passed")
