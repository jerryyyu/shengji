import Foundation
import Capacitor

/// The release bot for offline play: CPython embedded in the app, running the
/// unmodified `shengji` package with the release's `fly.toml` and weights
/// (bundled under `python/` by the "Install Python (pybot)" build phase).
///
/// JS sees it as `ShengjiBot`:
/// - `start()` starts the interpreter and builds the bot, once; it resolves to
///   the bot's identity (JSON text) and rejects when the bundle has no bot or
///   the build fails. Later calls return the same result.
/// - `decide({request})` answers one decision request (JSON text, see
///   `offline_bot.py`) with `{response}` (JSON text), or rejects.
///
/// Python runs on one serial queue, off the main thread, so calls never block
/// the UI and never run two at a time. The page applies the time limits and
/// plays SmartBot's move when a call fails or is late.
public class ShengjiBotPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiBotPlugin"
    public let jsName = "ShengjiBot"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "decide", returnType: CAPPluginReturnPromise)
    ]

    @objc func start(_ call: CAPPluginCall) {
        PyBot.shared.queue.async {
            switch PyBot.shared.start() {
            case .success(let identity): call.resolve(["identity": identity])
            case .failure(let error): call.reject(error.description)
            }
        }
    }

    @objc func decide(_ call: CAPPluginCall) {
        guard let request = call.getString("request") else {
            call.reject("request must be a JSON string")
            return
        }
        PyBot.shared.queue.async {
            do {
                call.resolve(["response": try PyBot.shared.decide(request)])
            } catch let error as PyBotError {
                call.reject(error.description)
            } catch {
                call.reject("\(error)")
            }
        }
    }
}

struct PyBotError: Error, CustomStringConvertible {
    let description: String
}

/// The interpreter and the bot. Every method runs on `queue`.
final class PyBot {
    static let shared = PyBot()
    let queue = DispatchQueue(label: "shengji.pybot", qos: .userInitiated)
    private var started: Result<String, PyBotError>?
    private var decisions = 0

    private var resources: String { Bundle.main.resourcePath ?? "" }

    func start() -> Result<String, PyBotError> {
        if let started = started { return started }
        let result = buildBot()
        started = result
        return result
    }

    private func buildBot() -> Result<String, PyBotError> {
        let payload = resources + "/python/app"
        guard FileManager.default.fileExists(atPath: payload + "/offline_bot.py"),
              FileManager.default.fileExists(atPath: payload + "/fly.toml") else {
            NSLog("[pybot] this build carries no bot")
            return .failure(PyBotError(description: "this build carries no bot"))
        }
        let t0 = Date()
        if let err = pybot_start(resources) {
            defer { free(err) }
            let message = String(cString: err)
            NSLog("[pybot] interpreter failed: %@", message)
            return .failure(PyBotError(description: message))
        }
        let interpreter = Date().timeIntervalSince(t0)
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("pybot", isDirectory: true)
        try? FileManager.default.createDirectory(at: support, withIntermediateDirectories: true)
        // a fresh seed per launch, as the server seeds each room's bot
        let seed = Int.random(in: 0..<(1 << 31))
        do {
            let identity = try call("init", args: [payload, support.path, seed])
            NSLog("[pybot] ready in %.2f s (interpreter %.2f s), footprint %.0f MB: %@",
                  Date().timeIntervalSince(t0), interpreter, footprintMB(), identity)
            return .success(identity)
        } catch let error as PyBotError {
            NSLog("[pybot] bot failed to build: %@", error.description)
            return .failure(error)
        } catch {
            return .failure(PyBotError(description: "\(error)"))
        }
    }

    func decide(_ request: String) throws -> String {
        guard case .success = started else { throw PyBotError(description: "the bot is not running") }
        let t0 = Date()
        let response = try call("decide", args: [request])
        decisions += 1
        NSLog("[pybot] decision %d in %.3f s: %@", decisions, Date().timeIntervalSince(t0), response)
        return response
    }

    private func call(_ name: String, args: [Any]) throws -> String {
        let data = try JSONSerialization.data(withJSONObject: args)
        guard let json = String(data: data, encoding: .utf8) else { throw PyBotError(description: "bad arguments") }
        guard let raw = pybot_call(name, json) else { throw PyBotError(description: "no result") }
        defer { free(raw) }
        let out = String(cString: raw)
        if out.hasPrefix("ERROR: ") { throw PyBotError(description: out) }
        return out
    }

    /// phys_footprint, the figure the system's memory limit counts.
    private func footprintMB() -> Double {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return kr == KERN_SUCCESS ? Double(info.phys_footprint) / 1_048_576 : 0
    }
}
