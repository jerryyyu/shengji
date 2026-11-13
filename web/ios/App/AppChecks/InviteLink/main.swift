// The URL-to-page mapping of App/InviteLink.swift, checked without Xcode:
//   swiftc -o /tmp/invite_link_check web/ios/App/App/InviteLink.swift \
//     web/ios/App/AppChecks/InviteLink/main.swift && /tmp/invite_link_check
import Foundation

let server = URL(string: "https://shengji.fly.dev")!
var failures = 0

func expect(_ link: String, _ want: String?, line: Int = #line) {
    let got = InviteLink.target(for: URL(string: link)!, server: server)?.absoluteString
    if got != want {
        failures += 1
        print("line \(line): \(link) -> \(got ?? "nil"), want \(want ?? "nil")")
    }
}

// invite links open the server's root with the link's query
expect("https://shengji.fly.dev/?code=AB12", "https://shengji.fly.dev/?code=AB12")
expect("https://shengji.fly.dev?code=AB12", "https://shengji.fly.dev/?code=AB12")
expect("https://shengji.fly.dev/?room=AB12&name=Ann%20B", "https://shengji.fly.dev/?room=AB12&name=Ann%20B")
expect("https://SHENGJI.fly.dev/?code=AB12#x", "https://shengji.fly.dev/?code=AB12")
// anything that is not an invite is left alone
expect("https://shengji.fly.dev/", nil)
expect("https://shengji.fly.dev/?code=", nil)
expect("https://shengji.fly.dev/?name=Ann", nil)
expect("https://shengji.fly.dev/rules?code=AB12", nil)
expect("https://shengji.fly.dev/support", nil)
expect("http://shengji.fly.dev/?code=AB12", nil)
expect("https://evil.example/?code=AB12", nil)
expect("https://shengji.fly.dev.evil.example/?code=AB12", nil)
expect("https://shengji.fly.dev:8443/?code=AB12", nil)

if failures > 0 {
    print("\(failures) failed")
    exit(1)
}
print("invite link mapping: all passed")
