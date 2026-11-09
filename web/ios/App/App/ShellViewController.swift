import UIKit
import Capacitor

/// The app's root view controller: Capacitor's bridge plus the shell's own
/// plugin. CAPBridgeViewController keeps the orientation mask in
/// `supportedOrientations`, which the ScreenOrientation plugin also writes, so
/// both plugins steer the same state.
class ShellViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(ShengjiShellPlugin())
    }
}

/// Two shell facts the web client cannot get from a viewport:
/// - `idiom()`: "phone" or "pad", so the web locks orientation on an iPhone
///   only (an iPad in Split View can be as narrow as a phone);
/// - `lockOrientation({orientation})`: "landscape" allows BOTH landscape
///   sides, which ScreenOrientation's lock cannot (its "landscape" is one
///   side), so the table turns with the phone; "portrait" and "any" too.
@objc(ShengjiShellPlugin)
public class ShengjiShellPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiShellPlugin"
    public let jsName = "ShengjiShell"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "idiom", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "lockOrientation", returnType: CAPPluginReturnPromise)
    ]

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
