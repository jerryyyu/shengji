import Foundation

/// The app's one move from its first host to its own domain. A WKWebView keeps
/// cookies and localStorage per origin, so the page at the new host starts
/// with neither. Once, before the first page loads, the shell copies the old
/// host's cookies onto the new host (the session token is not tied to a host)
/// and hands the page the old host's localStorage, which the page writes back
/// where a key is still unset (`web/src/originMove.ts`). Each part is done
/// only when it is known to be done: the cookies once every copy is set, the
/// storage once a page at the new origin confirms it kept the handoff. A
/// launch that times out, fails to read or exits first offers the rest again
/// next launch; a confirmed import is never offered again, so a sign-out or a
/// cleared seat after it stays. The old host keeps serving builds that still
/// load it, and its invite links still open the app.
enum OriginMove {
    /// The host every build up to 1.0.1 loaded.
    static let previousHost = "shengji.fly.dev"
    /// The hosts the move goes to; a test server (CAP_SERVER_URL) moves nothing.
    static let targetHosts: Set<String> = ["playshengji.com"]
    /// The server's session cookie (server/shengji/api/accounts.py COOKIE).
    static let sessionCookie = "sj_session"
    /// The UserDefaults flags: the cookies were copied; a page confirmed the import.
    static let cookiesKey = "shengji.originMove.cookies.v1"
    static let importedKey = "shengji.originMove.v1"
    /// The page's confirmation: the script message handler's name and body.
    static let confirmHandler = "shengjiOriginMove"
    static let confirmBody = "imported"

    /// Whether a script message is the page's confirmation: that body, from
    /// the main frame of a page at `https://<host>` on the default port.
    static func confirms(body: Any, isMainFrame: Bool, scheme: String, host: String, port: Int) -> Bool {
        isMainFrame && (body as? String) == confirmBody && scheme.lowercased() == "https"
            && targetHosts.contains(host.lowercased()) && (port == 0 || port == 443)
    }

    /// Whether a launch at `server` should move this install's data.
    static func applies(to server: URL?) -> Bool {
        guard let server = server, server.scheme?.lowercased() == "https",
              let host = server.host?.lowercased() else { return false }
        return targetHosts.contains(host) && host != previousHost
    }

    /// Whether `domain` (a cookie's, with or without the leading dot) is `host`.
    static func domain(_ domain: String, is host: String) -> Bool {
        let d = domain.lowercased()
        return (d.hasPrefix(".") ? String(d.dropFirst()) : d) == host.lowercased()
    }

    /// The old host's cookies as the same cookies on `host`: the same name,
    /// value, path, expiry, Secure, HttpOnly and SameSite. A name `host`
    /// already has is left alone, and an expired cookie is not carried.
    static func movedCookies(_ all: [HTTPCookie], to host: String, now: Date = Date()) -> [HTTPCookie] {
        let have = Set(all.filter { domain($0.domain, is: host) }.map(\.name))
        return all.compactMap { old in
            guard domain(old.domain, is: previousHost), !have.contains(old.name) else { return nil }
            if let expires = old.expiresDate, expires <= now { return nil }
            var props: [HTTPCookiePropertyKey: Any] = [
                .name: old.name, .value: old.value, .domain: host, .path: old.path.isEmpty ? "/" : old.path,
            ]
            if let expires = old.expiresDate { props[.expires] = expires }
            if old.isSecure { props[.secure] = "TRUE" }
            if old.isHTTPOnly { props[HTTPCookiePropertyKey("HttpOnly")] = "TRUE" }
            if let policy = old.sameSitePolicy { props[.sameSitePolicy] = policy.rawValue }
            return HTTPCookie(properties: props)
        }
    }

    /// Whether the old host held a live session cookie.
    static func hadSession(_ all: [HTTPCookie], now: Date = Date()) -> Bool {
        all.contains { c in
            c.name == sessionCookie && domain(c.domain, is: previousHost)
                && (c.expiresDate.map { $0 > now } ?? true)
        }
    }

    /// The page script that reads the old host's localStorage as a JSON object
    /// of strings (run in a page whose origin is the old host).
    static let readStorageScript = """
        (function () { var o = {}; for (var i = 0; i < localStorage.length; i++) { \
        var k = localStorage.key(i); if (k !== null) o[k] = localStorage.getItem(k); } \
        return JSON.stringify(o); })()
        """

    /// The keys and values `readStorageScript` returned, keeping string values
    /// only; empty for anything that is not such an object.
    static func storageEntries(_ result: Any?) -> [String: String] {
        guard let text = result as? String, let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return object.compactMapValues { $0 as? String }
    }

    /// The document-start script that hands the page what moved:
    /// `window.__shengjiOriginMove = {origin, entries, session}`, assigned only
    /// in a document whose origin is exactly `origin`, so a page at any other
    /// origin (the offline page, a link followed elsewhere) never sees the
    /// snapshot. Nil when the values cannot be written as JSON.
    static func handoffScript(origin: String, entries: [String: String], session: Bool) -> String? {
        let payload: [String: Any] = ["origin": origin, "entries": entries, "session": session]
        guard JSONSerialization.isValidJSONObject(payload), JSONSerialization.isValidJSONObject([origin]),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8),
              let originData = try? JSONSerialization.data(withJSONObject: [origin]),
              let originList = String(data: originData, encoding: .utf8) else { return nil }
        return "if (location.origin === \(originList)[0]) { window.__shengjiOriginMove = \(json); }"
    }
}

/// Where the move's two flags are kept (UserDefaults in the app).
protocol OriginMoveFlags: AnyObject {
    func bool(forKey key: String) -> Bool
    func set(_ value: Bool, forKey key: String)
}

extension UserDefaults: OriginMoveFlags {}

/// What is left of the move on this install.
struct OriginMoveLedger {
    let flags: OriginMoveFlags

    var cookiesCopied: Bool { flags.bool(forKey: OriginMove.cookiesKey) }
    var imported: Bool { flags.bool(forKey: OriginMove.importedKey) }
    /// Some part is not yet known to be done: this launch offers it.
    var pending: Bool { !cookiesCopied || !imported }

    func markCookiesCopied() { flags.set(true, forKey: OriginMove.cookiesKey) }
    func markImported() { flags.set(true, forKey: OriginMove.importedKey) }
}

/// One launch's attempt, as the runner drives it: which step comes next and
/// what may be marked done. Only `cookiesSet` and a valid `confirmed` mark
/// anything; a timeout, a failed read or an exit marks nothing.
struct OriginMoveAttempt {
    enum Next: Equatable { case readStorage, release }

    let ledger: OriginMoveLedger
    /// The start page may load: no handoff is offered after this.
    private(set) var released = false
    /// A handoff is in place for pages at the new origin.
    private(set) var offered = false

    init(ledger: OriginMoveLedger) { self.ledger = ledger }

    /// Every cookie copy is set (or none was due).
    mutating func cookiesSet() -> Next {
        if !ledger.cookiesCopied { ledger.markCookiesCopied() }
        return ledger.imported || released ? .release : .readStorage
    }

    /// The read came back: whether to offer its handoff. A failed read, or one
    /// after the start page was released, offers nothing.
    mutating func read(succeeded: Bool) -> Bool {
        guard succeeded, !released, !offered, !ledger.imported else { return false }
        offered = true
        return true
    }

    /// The launch's timeout, or the read's end: the start page loads.
    mutating func release() { released = true }

    /// A script message arrived: whether it confirms the import (and so the
    /// handoff is retired).
    mutating func confirmed(_ valid: Bool) -> Bool {
        guard valid, offered else { return false }
        ledger.markImported()
        offered = false
        return true
    }
}
