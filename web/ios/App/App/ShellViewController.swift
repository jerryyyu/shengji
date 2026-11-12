import UIKit
import Capacitor
import WebKit

/// The app's root view controller: Capacitor's bridge plus the shell's own
/// plugin. CAPBridgeViewController keeps the orientation mask in
/// `supportedOrientations`, which the ScreenOrientation plugin also writes, so
/// both plugins steer the same state.
///
/// A swipe from the left edge goes back through the WebView's history (and
/// from the right edge forward), as in Safari: the web app's sub-pages (How
/// to play, a saved game and its replays, Privacy, Support) are history
/// entries. The web turns the gesture off at the table.
///
/// A tap on the status bar reaches the page as a window `statusTap` event, so
/// the page can scroll its own scroller to the top (the WebView's outer scroll
/// view never scrolls). In game mode the bottom edge defers the system's home
/// gesture, so a card drag near the edge needs a second swipe to leave.
class ShellViewController: CAPBridgeViewController {
    private var navigationGate: OfflineFallbackGate?
    private var statusTapObserver: NSObjectProtocol?

    var inGame = false {
        didSet {
            guard inGame != oldValue else { return }
            setNeedsUpdateOfScreenEdgesDeferringSystemGestures()
            setNeedsUpdateOfHomeIndicatorAutoHidden()
        }
    }

    override open func capacitorDidLoad() {
        webView?.allowsBackForwardNavigationGestures = true
        bridge?.registerPluginInstance(ShengjiShellPlugin())
        bridge?.registerPluginInstance(ShengjiBotPlugin())
        // WKWebView holds its navigation delegate weakly, so the gate lives here.
        if let webView = webView, let inner = webView.navigationDelegate {
            let gate = OfflineFallbackGate(inner: inner)
            navigationGate = gate
            webView.navigationDelegate = gate
        }
        statusTapObserver = NotificationCenter.default.addObserver(
            forName: .capacitorStatusBarTapped, object: nil, queue: .main
        ) { [weak self] _ in
            self?.webView?.evaluateJavaScript("window.dispatchEvent(new Event('statusTap'))")
        }
    }

    override var preferredScreenEdgesDeferringSystemGestures: UIRectEdge {
        inGame ? .bottom : []
    }

    deinit {
        if let observer = statusTapObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }
}

/// Sits in front of Capacitor's navigation delegate. Capacitor loads the
/// bundled offline page (`server.errorPath`) on every failed navigation,
/// including a load that was merely cancelled or replaced; that would drop an
/// online player into offline mode. The gate passes a failure through only when
/// the server cannot be reached, and forwards every other callback unchanged.
final class OfflineFallbackGate: NSObject, WKNavigationDelegate {
    private let inner: WKNavigationDelegate

    init(inner: WKNavigationDelegate) {
        self.inner = inner
    }

    override func responds(to aSelector: Selector!) -> Bool {
        super.responds(to: aSelector) || inner.responds(to: aSelector)
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? {
        inner.responds(to: aSelector) ? inner : nil
    }

    static func meansUnreachable(_ error: Error) -> Bool {
        let e = error as NSError
        guard e.domain == NSURLErrorDomain else { return false }
        return [NSURLErrorNotConnectedToInternet, NSURLErrorTimedOut, NSURLErrorCannotFindHost,
                NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost, NSURLErrorDNSLookupFailed,
                NSURLErrorInternationalRoamingOff, NSURLErrorDataNotAllowed, NSURLErrorSecureConnectionFailed]
            .contains(e.code)
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if OfflineFallbackGate.meansUnreachable(error) {
            inner.webView?(webView, didFail: navigation, withError: error)
        } else {
            CAPLog.print("⚡️  Navigation ended without a network failure: \(error.localizedDescription)")
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if OfflineFallbackGate.meansUnreachable(error) {
            inner.webView?(webView, didFailProvisionalNavigation: navigation, withError: error)
        } else {
            CAPLog.print("⚡️  Provisional navigation ended without a network failure: \(error.localizedDescription)")
        }
    }
}

/// Shell facts and controls the web client cannot get from a viewport:
/// - `idiom()`: "phone" or "pad", so the web locks orientation on an iPhone
///   only (an iPad in Split View can be as narrow as a phone);
/// - `lockOrientation({orientation})`: "landscape" allows BOTH landscape
///   sides, which ScreenOrientation's lock cannot (its "landscape" is one
///   side), so the table turns with the phone; "portrait" and "any" too;
/// - `setBackGesture({enabled})`: the edge swipe back and forward, off while
///   a game is on the table;
/// - `setGameMode({on})`: at the table the screen stays awake and the bottom
///   edge defers the home gesture; off, the idle timer and the edge are the
///   system's again. The home indicator itself hides through SystemBars.
@objc(ShengjiShellPlugin)
public class ShengjiShellPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiShellPlugin"
    public let jsName = "ShengjiShell"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "idiom", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "lockOrientation", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setBackGesture", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setGameMode", returnType: CAPPluginReturnPromise)
    ]

    @objc func setGameMode(_ call: CAPPluginCall) {
        guard let on = call.getBool("on") else {
            call.reject("on must be true or false")
            return
        }
        DispatchQueue.main.async {
            // A hand can sit idle for a while between turns.
            UIApplication.shared.isIdleTimerDisabled = on
            (self.bridge?.viewController as? ShellViewController)?.inGame = on
            call.resolve()
        }
    }

    @objc func setBackGesture(_ call: CAPPluginCall) {
        guard let enabled = call.getBool("enabled") else {
            call.reject("enabled must be true or false")
            return
        }
        DispatchQueue.main.async {
            guard let webView = self.bridge?.webView else {
                call.reject("no web view")
                return
            }
            webView.allowsBackForwardNavigationGestures = enabled
            call.resolve()
        }
    }

    @objc func idiom(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            let idiom: String
            switch UIDevice.current.userInterfaceIdiom {
            case .phone: idiom = "phone"
            case .pad: idiom = "pad"
            default: idiom = "other"
            }
            call.resolve(["idiom": idiom])
        }
    }

    @objc func lockOrientation(_ call: CAPPluginCall) {
        let kind = call.getString("orientation") ?? "any"
        let orientations: [UIInterfaceOrientation]
        let mask: UIInterfaceOrientationMask
        switch kind {
        case "landscape":
            orientations = [.landscapeLeft, .landscapeRight]
            mask = .landscape
        case "portrait":
            orientations = [.portrait]
            mask = .portrait
        case "any":
            orientations = [.portrait, .portraitUpsideDown, .landscapeLeft, .landscapeRight]
            mask = .all
        default:
            call.reject("orientation must be landscape, portrait or any")
            return
        }
        DispatchQueue.main.async {
            guard let vc = self.bridge?.viewController as? CAPBridgeViewController else {
                call.reject("no bridge view controller")
                return
            }
            vc.supportedOrientations = orientations.map { $0.rawValue }
            if #available(iOS 16.0, *) {
                vc.setNeedsUpdateOfSupportedInterfaceOrientations()
                guard let scene = vc.view.window?.windowScene else {
                    call.resolve()
                    return
                }
                scene.requestGeometryUpdate(.iOS(interfaceOrientations: mask)) { error in
                    CAPLog.print("ShengjiShell.lockOrientation: \(error.localizedDescription)")
                }
                call.resolve()
            } else {
                UIViewController.attemptRotationToDeviceOrientation()
                call.resolve()
            }
        }
    }
}
