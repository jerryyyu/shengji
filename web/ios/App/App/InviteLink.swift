import Foundation

/// Where an invite link opens in the app. The server's apple-app-site-association
/// file sends only invite links here: `/?code=<code>` (and the older
/// `/?room=<code>`) on the server's host. The page reads the code from its own
/// query on load, as it does for the same link in a browser, so the app loads
/// that address in the WebView: the server's root with the link's query.
/// Anything else is not an invite and returns nil, leaving the page alone.
enum InviteLink {
    static func target(for link: URL, server: URL) -> URL? {
        guard link.scheme?.lowercased() == "https",
              let host = link.host?.lowercased(), host == server.host?.lowercased(),
              link.port == server.port,
              let parts = URLComponents(url: link, resolvingAgainstBaseURL: false),
              parts.path.isEmpty || parts.path == "/",
              let items = parts.queryItems,
              items.contains(where: { ($0.name == "code" || $0.name == "room") && !($0.value ?? "").isEmpty }),
              var target = URLComponents(url: server, resolvingAgainstBaseURL: false)
        else { return nil }
        target.path = "/"
        target.percentEncodedQuery = parts.percentEncodedQuery
        target.fragment = nil
        return target.url
    }
}
