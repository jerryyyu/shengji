import Foundation

/// The app's one move from its first host to its own domain. A WKWebView keeps
/// cookies and localStorage per origin, so the page at the new host starts
/// with neither. Once, before the first page loads, the shell copies the old
/// host's cookies onto the new host (the session token is not tied to a host)
/// and hands the page the old host's localStorage, which the page writes back
/// where a key is still unset (`web/src/originMove.ts`). The old host keeps
/// serving builds that still load it, and its invite links still open the app.
enum OriginMove {
    /// The host every build up to 1.0.1 loaded.
    static let previousHost = "shengji.fly.dev"
    /// The hosts the move goes to; a test server (CAP_SERVER_URL) moves nothing.
    static let targetHosts: Set<String> = ["playshengji.com"]
    /// The server's session cookie (server/shengji/api/accounts.py COOKIE).
    static let sessionCookie = "sj_session"
    /// The UserDefaults flag: the move ran on this install.
    static let doneKey = "shengji.originMove.v1"

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
    /// `window.__shengjiOriginMove = {origin, entries, session}`. `origin` is
    /// the new host's, so a page at any other origin (the offline page) leaves
    /// it alone. Nil when the values cannot be written as JSON.
    static func handoffScript(origin: String, entries: [String: String], session: Bool) -> String? {
        let payload: [String: Any] = ["origin": origin, "entries": entries, "session": session]
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return nil }
        return "window.__shengjiOriginMove = \(json);"
    }
}
