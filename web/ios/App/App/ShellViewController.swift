import UIKit
import Capacitor

/// The app's root view controller: Capacitor's bridge plus the shell's own
/// plugin. CAPBridgeViewController keeps the orientation mask in
/// `supportedOrientations`, which the ScreenOrientation plugin also writes, so
/// both plugins steer the same state.
///
/// A swipe from the left edge goes back through the WebView's history (and
/// from the right edge forward), as in Safari: the web app's sub-pages (How
/// to play, a saved game and its replays, Privacy, Support) are history
/// entries. The web turns the gesture off at the table.
class ShellViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        webView?.allowsBackForwardNavigationGestures = true
        bridge?.registerPluginInstance(ShengjiShellPlugin())
    }
}

/// Shell facts and controls the web client cannot get from a viewport:
/// - `idiom()`: "phone" or "pad", so the web locks orientation on an iPhone
///   only (an iPad in Split View can be as narrow as a phone);
/// - `lockOrientation({orientation})`: "landscape" allows BOTH landscape
///   sides, which ScreenOrientation's lock cannot (its "landscape" is one
///   side), so the table turns with the phone; "portrait" and "any" too;
/// - `setBackGesture({enabled})`: the edge swipe back and forward, off while
///   a game is on the table.
@objc(ShengjiShellPlugin)
public class ShengjiShellPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiShellPlugin"
    public let jsName = "ShengjiShell"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "idiom", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "lockOrientation", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setBackGesture", returnType: CAPPluginReturnPromise)
    ]

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
