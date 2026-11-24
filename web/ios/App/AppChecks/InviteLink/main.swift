// The URL-to-page mapping of App/InviteLink.swift, checked without Xcode:
//   swiftc -o /tmp/invite_link_check web/ios/App/App/InviteLink.swift \
//     web/ios/App/App/OriginMove.swift web/ios/App/AppChecks/InviteLink/main.swift \
//     && /tmp/invite_link_check
import Foundation

let server = URL(string: "https://playshengji.com")!
var failures = 0

func expect(_ link: String, _ want: String?, line: Int = #line) {
    let got = InviteLink.target(for: URL(string: link)!, server: server)?.absoluteString
    if got != want {
        failures += 1
        print("line \(line): \(link) -> \(got ?? "nil"), want \(want ?? "nil")")
    }
}

// invite links open the server's root with the link's query
expect("https://playshengji.com/?code=AB12", "https://playshengji.com/?code=AB12")
expect("https://playshengji.com?code=AB12", "https://playshengji.com/?code=AB12")
expect("https://playshengji.com/?room=AB12&name=Ann%20B", "https://playshengji.com/?room=AB12&name=Ann%20B")
expect("https://PLAYSHENGJI.com/?code=AB12#x", "https://playshengji.com/?code=AB12")
// a link on the host older builds load and share opens on the server too
expect("https://shengji.fly.dev/?code=AB12", "https://playshengji.com/?code=AB12")
expect("https://shengji.fly.dev?code=AB12", "https://playshengji.com/?code=AB12")
expect("https://SHENGJI.fly.dev/?room=AB12&name=Ann%20B#x", "https://playshengji.com/?room=AB12&name=Ann%20B")
// anything that is not an invite is left alone
expect("https://playshengji.com/", nil)
expect("https://playshengji.com/?code=", nil)
expect("https://playshengji.com/?name=Ann", nil)
expect("https://playshengji.com/rules?code=AB12", nil)
expect("https://playshengji.com/support", nil)
expect("http://playshengji.com/?code=AB12", nil)
expect("https://shengji.fly.dev/", nil)
expect("https://shengji.fly.dev/rules?code=AB12", nil)
expect("http://shengji.fly.dev/?code=AB12", nil)
expect("https://evil.example/?code=AB12", nil)
expect("https://playshengji.com.evil.example/?code=AB12", nil)
expect("https://shengji.fly.dev.evil.example/?code=AB12", nil)
expect("https://other.fly.dev/?code=AB12", nil)
expect("https://playshengji.com:8443/?code=AB12", nil)
expect("https://shengji.fly.dev:8443/?code=AB12", nil)

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("invite link mapping: all passed")
