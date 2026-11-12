import Foundation
import UIKit
import Capacitor

/// The embedded served bot (spike): CPython + the `shengji` package, run on a
/// serial background queue. JS sees it as `ShengjiBot` (`start`, `decide`,
/// `bench`). A launch argument `-pybot-bench <worlds> <rounds> [fast]` runs the
/// benchmark at launch and writes Documents/pybot/bench-*.json plus
/// Documents/pybot/summary-*.json (interpreter start, peak memory).
public class ShengjiBotPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiBotPlugin"
    public let jsName = "ShengjiBot"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "decide", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "bench", returnType: CAPPluginReturnPromise)
    ]

    override public func load() {
        // Xcode may pass "-pybot-bench 64 3" as one argument or as three.
        let args = ProcessInfo.processInfo.arguments.flatMap { $0.split(separator: " ").map(String.init) }
        guard let i = args.firstIndex(of: "-pybot-bench") else { return }
        // keep the device awake: a locked screen suspends the benchmark
        DispatchQueue.main.async { UIApplication.shared.isIdleTimerDisabled = true }
        let worlds = args.count > i + 1 ? Int(args[i + 1]) ?? 64 : 64
        let rounds = args.count > i + 2 ? Int(args[i + 2]) ?? 3 : 3
        let fast = args.count > i + 3 && args[i + 3] == "fast"
        PyBot.shared.queue.async { PyBot.shared.runBench(worlds: worlds, rounds: rounds, fast: fast) }
    }

    @objc func start(_ call: CAPPluginCall) {
        let worlds = call.getInt("worlds") ?? 0
        let fast = call.getBool("fast") ?? false
        PyBot.shared.queue.async {
            do {
                call.resolve(["identity": try PyBot.shared.start(worlds: worlds, fast: fast)])
            } catch {
                call.reject("\(error)")
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
                call.resolve(["response": try PyBot.shared.call("decide", args: [request])])
            } catch {
                call.reject("\(error)")
            }
        }
    }

    @objc func bench(_ call: CAPPluginCall) {
        let rounds = call.getInt("rounds") ?? 1
        PyBot.shared.queue.async {
            do {
                call.resolve(["result": try PyBot.shared.call("bench", args: [rounds])])
            } catch {
                call.reject("\(error)")
            }
        }
    }
}

struct PyBotError: Error, CustomStringConvertible {
    let description: String
}

final class PyBot {
    static let shared = PyBot()
    let queue = DispatchQueue(label: "shengji.pybot", qos: .userInitiated)
    private var interpreterSeconds: Double?
    private var identity: String?

    var outDir: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("pybot", isDirectory: true)
    }

    func startInterpreter() throws {
        if interpreterSeconds != nil { return }
        let t0 = Date()
        if let err = pybot_start(Bundle.main.resourcePath!) {
            defer { free(err) }
            throw PyBotError(description: String(cString: err))
        }
        interpreterSeconds = Date().timeIntervalSince(t0)
        NSLog("[pybot] interpreter + offline_bot import: %.3f s", interpreterSeconds!)
    }

    func call(_ name: String, args: [Any]) throws -> String {
        try startInterpreter()
        let data = try JSONSerialization.data(withJSONObject: args)
        let json = String(data: data, encoding: .utf8)!
        guard let raw = pybot_call(name, json) else { throw PyBotError(description: "null result") }
        defer { free(raw) }
        let s = String(cString: raw)
        if s.hasPrefix("ERROR: ") { throw PyBotError(description: s) }
        return s
    }

    func start(worlds: Int, fast: Bool) throws -> String {
        try startInterpreter()
        try FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
        let payload = Bundle.main.resourcePath! + "/python/app"
        let id = try call("init", args: [payload, outDir.path, worlds, fast])
        identity = id
        return id
    }

    func runBench(worlds: Int, rounds: Int, fast: Bool) {
        let tag = "w\(worlds)-\(fast ? "fast" : "pure")"
        let sampler = FootprintSampler()
        sampler.start()
        var summary: [String: Any] = ["tag": tag, "worlds": worlds, "rounds": rounds, "fast": fast,
                                      "device": deviceModel(),
                                      "os": ProcessInfo.processInfo.operatingSystemVersionString]
        do {
            let t0 = Date()
            try startInterpreter()
            summary["interpreter_start_s"] = interpreterSeconds
            summary["footprint_after_interpreter_mb"] = FootprintSampler.current().footprint
            let id = try start(worlds: worlds, fast: fast)
            summary["init_total_s"] = Date().timeIntervalSince(t0)
            summary["identity"] = id
            summary["footprint_after_init_mb"] = FootprintSampler.current().footprint
            NSLog("[pybot] identity %@", id)
            // bench writes bench-<tag>.json itself
            let out = try call("bench", args: [rounds, 20261112, "-" + tag])
            if let d = out.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
                summary["phases"] = obj["phases"]
                summary["fallbacks"] = obj["fallbacks"]
                summary["python_peak_rss_mb"] = obj["peak_rss_mb"]
            }
        } catch {
            summary["error"] = "\(error)"
            NSLog("[pybot] ERROR %@", "\(error)")
        }
        sampler.stop()
        let now = FootprintSampler.current()
        summary["peak_footprint_mb_sampled"] = sampler.peak
        summary["peak_footprint_mb_ledger"] = now.ledgerPeak
        summary["done"] = true
        if let data = try? JSONSerialization.data(withJSONObject: summary, options: [.prettyPrinted, .sortedKeys]) {
            try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
            try? data.write(to: outDir.appendingPathComponent("summary-\(tag).json"))
            NSLog("[pybot] SUMMARY %@", String(data: data, encoding: .utf8) ?? "")
        }
    }

    private func deviceModel() -> String {
        if let sim = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] { return "simulator " + sim }
        var info = utsname()
        uname(&info)
        return withUnsafePointer(to: &info.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
    }
}

/// phys_footprint is what jetsam counts against the app's memory limit.
final class FootprintSampler {
    private(set) var peak: Double = 0
    private var timer: DispatchSourceTimer?

    static func current() -> (footprint: Double, ledgerPeak: Double) {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        guard kr == KERN_SUCCESS else { return (0, 0) }
        let mb = 1024.0 * 1024.0
        return (Double(info.phys_footprint) / mb, Double(info.ledger_phys_footprint_peak) / mb)
    }

    func start() {
        let t = DispatchSource.makeTimerSource(queue: DispatchQueue(label: "shengji.pybot.mem"))
        t.schedule(deadline: .now(), repeating: .milliseconds(100))
        t.setEventHandler { [weak self] in
            let f = FootprintSampler.current().footprint
            if let s = self, f > s.peak { s.peak = f }
        }
        t.resume()
        timer = t
    }

    func stop() {
        timer?.cancel()
        timer = nil
    }
}
