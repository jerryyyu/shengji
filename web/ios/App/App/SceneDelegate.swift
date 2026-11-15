import UIKit
import Capacitor
import GoogleSignIn

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = ShellViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
        // A URL that launched the app cold arrives here, not in openURLContexts.
        routeGoogleReturns(connectionOptions.urlContexts)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        let rest = routeGoogleReturns(URLContexts)
        if !rest.isEmpty {
            SceneDelegateProxy.shared.scene(scene, openURLContexts: rest)
        }
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }

    /// Google's sign-in returns to the app on the reversed iOS client scheme;
    /// GIDSignIn must see that URL to finish the sign-in. Returns the URLs it
    /// did not take, which Capacitor still handles.
    @discardableResult
    private func routeGoogleReturns(_ contexts: Set<UIOpenURLContext>) -> Set<UIOpenURLContext> {
        contexts.filter { !GIDSignIn.sharedInstance.handle($0.url) }
    }
}
