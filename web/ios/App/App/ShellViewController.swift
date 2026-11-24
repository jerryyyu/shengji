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
///
/// An invite link that opens the app (a universal link) loads in the WebView
/// as the same link loads in Safari (InviteLink). Capacitor posts the link
/// when the app is already running and, on a cold launch, once the first view
/// has appeared, so one observer serves both; the load replaces the start
/// page, and the cancelled start load is not a network failure.
///
/// The first launch on the app's own domain moves this install's cookies and
/// localStorage from the host it loaded before (OriginMove) before the first
/// page loads; an invite link that arrives meanwhile loads after it.
class ShellViewController: CAPBridgeViewController {
    private var navigationGate: OfflineFallbackGate?
    private var statusTapObserver: NSObjectProtocol?
    private var inviteLinkObserver: NSObjectProtocol?
    private var originMove: OriginMoveRunner?
    private var movingBeforeStart = false
    private var inviteAfterMove: URL?

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
        bridge?.registerPluginInstance(ShengjiKeychainPlugin())
        #if SHENGJI_NEARBY
        // Nearby play is registered only in builds that define SHENGJI_NEARBY.
        bridge?.registerPluginInstance(ShengjiNearbyPlugin())
        #endif
        // Launched from Xcode with -offline-autoplay, the offline game plays the
        // human's seat too, so a whole round of the bots can be watched and timed.
        // A test tool: in Debug and the Beta, never in an App Store build.
        #if DEBUG || SHENGJI_NEARBY_BETA
        if ProcessInfo.processInfo.arguments.contains("-offline-autoplay") {
            webView?.configuration.userContentController.addUserScript(WKUserScript(
                source: "window.__shengjiOfflineAutoplay = true;",
                injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
        #endif
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
        inviteLinkObserver = NotificationCenter.default.addObserver(
            forName: .capacitorOpenUniversalLink, object: nil, queue: .main
        ) { [weak self] note in
            guard let self = self,
                  let link = (note.object as? [String: Any])?["url"] as? URL,
                  let server = self.bridge?.config.serverURL,
                  let target = InviteLink.target(for: link, server: server) else { return }
            if self.movingBeforeStart {
                self.inviteAfterMove = target
            } else {
                _ = self.webView?.load(URLRequest(url: target))
            }
        }
    }

    /// Capacitor's viewDidLoad loads the start page; on a launch that still
    /// has some of the move to the app's own domain to do, it runs once this
    /// launch's attempt is over (done, failed or timed out). The runner stays
    /// to hear the page confirm the import.
    override open func viewDidLoad() {
        let ledger = OriginMoveLedger(flags: UserDefaults.standard)
        guard let webView = webView, let server = bridge?.config.serverURL, OriginMove.applies(to: server),
              ledger.pending else {
            super.viewDidLoad()
            return
        }
        let runner = OriginMoveRunner(webView: webView, server: server, ledger: ledger)
        originMove = runner
        movingBeforeStart = true
        runner.run { [weak self] in self?.loadAfterMove() }
    }

    private func loadAfterMove() {
        movingBeforeStart = false
        super.viewDidLoad()
        if let target = inviteAfterMove {
            inviteAfterMove = nil
            _ = webView?.load(URLRequest(url: target))
        }
    }

    #if DEBUG && SHENGJI_NEARBY_SPIKE
    /// The M1 transport spike opens its bundled test page, not the live site.
    override open func instanceDescriptor() -> InstanceDescriptor {
        let descriptor = super.instanceDescriptor()
        descriptor.serverURL = nil
        descriptor.appStartPath = "nearby-spike.html"
        return descriptor
    }
    #elseif DEBUG && SHENGJI_NEARBY_DEV
    /// A Debug-only switch: the bundled page, which carries the nearby UI in
    /// a dev build, instead of the live site.
    override open func instanceDescriptor() -> InstanceDescriptor {
        let descriptor = super.instanceDescriptor()
        descriptor.serverURL = nil
        return descriptor
    }
    #endif

    override var preferredScreenEdgesDeferringSystemGestures: UIRectEdge {
        inGame ? .bottom : []
    }

    deinit {
        for observer in [statusTapObserver, inviteLinkObserver].compactMap({ $0 }) {
            NotificationCenter.default.removeObserver(observer)
        }
    }
}

/// One launch's attempt at the move (OriginMove), on the bridge's own data
/// store. Cookies not yet copied are copied onto the server's host and marked
/// copied once every copy is set. A storage import not yet confirmed reads the
/// old host's localStorage in a hidden WebView, from a page with that origin
/// made from a string (no network), and hands it to pages at the new origin
/// as a document-start script; the import is marked done only when such a
/// page confirms it kept the handoff, and then the script and the snapshot are
/// dropped. `run`'s completion (the start page may load) is called once, on
/// the main queue, when the read is in place or fails, or after `timeout`
/// seconds; whatever is not done by then is offered again next launch.
final class OriginMoveRunner: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
    private let webView: WKWebView
    private let host: String
    private var attempt: OriginMoveAttempt
    private let timeout: TimeInterval
    private var reader: WKWebView?
    private var handoff: WKUserScript?
    private var hadSession = false
    private var done: (() -> Void)?

    init(webView: WKWebView, server: URL, ledger: OriginMoveLedger, timeout: TimeInterval = 3) {
        self.webView = webView
        self.host = server.host?.lowercased() ?? ""
        self.attempt = OriginMoveAttempt(ledger: ledger)
        self.timeout = timeout
    }

    func run(_ completion: @escaping () -> Void) {
        done = completion
        DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak self] in
            self?.release()
        }
        let cookies = webView.configuration.websiteDataStore.httpCookieStore
        cookies.getAllCookies { [weak self] all in
            guard let self = self else { return }
            self.hadSession = OriginMove.hadSession(all)
            let group = DispatchGroup()
            if !self.attempt.ledger.cookiesCopied {
                for cookie in OriginMove.movedCookies(all, to: self.host) {
                    group.enter()
                    cookies.setCookie(cookie) { group.leave() }
                }
            }
            group.notify(queue: .main) {
                switch self.attempt.cookiesSet() {
                case .readStorage: self.readStorage()
                case .release: self.release()
                }
            }
        }
    }

    private func readStorage() {
        guard done != nil, let base = URL(string: "https://\(OriginMove.previousHost)/") else { return }
        let config = WKWebViewConfiguration()
        config.websiteDataStore = webView.configuration.websiteDataStore
        config.processPool = webView.configuration.processPool
        let reader = WKWebView(frame: .zero, configuration: config)
        reader.navigationDelegate = self
        self.reader = reader
        reader.loadHTMLString("<!doctype html><title></title>", baseURL: base)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webView.evaluateJavaScript(OriginMove.readStorageScript) { [weak self] result, error in
            guard let self = self else { return }
            // a failed read hands nothing over: the next launch reads again
            if self.attempt.read(succeeded: error == nil && result is String) {
                self.offer(OriginMove.storageEntries(result))
            }
            self.release()
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        release()
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        release()
    }

    /// Hand the read to pages at the new origin (a read that lands after the
    /// timeout is not offered: the next launch reads again).
    private func offer(_ entries: [String: String]) {
        guard let source = OriginMove.handoffScript(origin: "https://\(host)", entries: entries, session: hadSession)
        else { return }
        let script = WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        handoff = script
        let controller = webView.configuration.userContentController
        controller.add(self, name: OriginMove.confirmHandler)
        controller.addUserScript(script)
    }

    /// The page kept the handoff: never offer it again, and drop the script
    /// and its snapshot so no later page in this launch gets it.
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        let origin = message.frameInfo.securityOrigin
        let valid = message.name == OriginMove.confirmHandler
            && OriginMove.confirms(body: message.body, isMainFrame: message.frameInfo.isMainFrame,
                                   scheme: origin.protocol, host: origin.host, port: origin.port)
        guard attempt.confirmed(valid) else { return }
        userContentController.removeScriptMessageHandler(forName: OriginMove.confirmHandler)
        if let script = handoff {
            let others = userContentController.userScripts.filter { $0 !== script }
            userContentController.removeAllUserScripts()
            others.forEach(userContentController.addUserScript)
        }
        handoff = nil
    }

    /// This launch's attempt is over: the start page may load.
    private func release() {
        attempt.release()
        reader?.navigationDelegate = nil
        reader?.stopLoading()
        reader = nil
        guard let completion = done else { return }
        done = nil
        completion()
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
            ScreenAwake.set(game: on)
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
