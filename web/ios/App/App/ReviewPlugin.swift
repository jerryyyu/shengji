import Foundation
import Capacitor
import StoreKit
import UIKit
import os

/// Apple's rating sheet for the page (web/src/reviewPrompt.ts decides when):
/// - `request()` asks StoreKit to show it in the app's active window scene and
///   resolves `{requested}`: false when no scene is in the foreground, so
///   nothing was asked. StoreKit alone decides whether the sheet appears
///   (it shows it at most a few times a year, and never in TestFlight).
/// Nothing about the player is read or sent; the log line carries no data.
@objc(ShengjiReviewPlugin)
public class ShengjiReviewPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiReviewPlugin"
    public let jsName = "ShengjiReview"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "request", returnType: CAPPluginReturnPromise)
    ]

    private static let log = Logger(subsystem: "com.jerryyu.shengji", category: "review")

    @objc func request(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            guard let scene = self.bridge?.viewController?.view.window?.windowScene,
                  scene.activationState == .foregroundActive else {
                ShengjiReviewPlugin.log.info("review request skipped: no active scene")
                call.resolve(["requested": false])
                return
            }
            if #available(iOS 16.0, *) {
                AppStore.requestReview(in: scene)
            } else {
                SKStoreReviewController.requestReview(in: scene)
            }
            ShengjiReviewPlugin.log.info("review requested")
            call.resolve(["requested": true])
        }
    }
}
