import Foundation
import Network
import Security
import CommonCrypto

/// The table key: PBKDF2-HMAC-SHA256 over the table code with the table's
/// salt. A 30-bit code behind a fast KDF falls to an offline search of one
/// recorded handshake, so the derivation is deliberately slow, and the
/// per-table salt makes every table's key different.
enum NearbyKey {
    // TODO-review(M1): tune to ~250 ms on the oldest supported phone
    static let iterations: UInt32 = 200_000
    static let identity = "shengji-nearby-v1"
    static let saltBytes = 16
    /// The online code alphabet: no I, O, 0 or 1.
    static let alphabet = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    static let codeLength = 6

    /// The code as the key sees it, or nil when it is not a nearby code.
    static func normalized(_ code: String) -> String? {
        let up = code.uppercased()
        guard up.count == codeLength, up.allSatisfy({ alphabet.contains($0) }) else { return nil }
        return up
    }

    static func derive(code: String, salt: Data, iterations: UInt32 = iterations) -> Data? {
        let password = code.uppercased().utf8.map { Int8(bitPattern: $0) }
        let saltBytes = [UInt8](salt)
        var key = [UInt8](repeating: 0, count: 32)
        let status = CCKeyDerivationPBKDF(
            CCPBKDFAlgorithm(kCCPBKDF2), password, password.count, saltBytes, saltBytes.count,
            CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), iterations, &key, key.count)
        return status == Int32(kCCSuccess) ? Data(key) : nil
    }

    static func randomBytes(_ n: Int) -> Data {
        var bytes = [UInt8](repeating: 0, count: n)
        let ok = SecRandomCopyBytes(kSecRandomDefault, n, &bytes)
        precondition(ok == errSecSuccess, "no system randomness")
        return Data(bytes)
    }

    /// Random characters from the 32-symbol alphabet; 256 is a multiple of
    /// 32, so masking a byte is unbiased.
    static func randomName(_ n: Int) -> String {
        String(randomBytes(n).map { alphabet[Int($0 & 31)] })
    }
}

#if !NEARBY_KEY_ONLY
import UIKit
import Capacitor

/// Which binaries may run the nearby transport. It is untested on devices,
/// so every method but `capabilities` refuses unless one of these is true.
enum NearbyBuild {
    // TODO-review: true only in the binary App Review sees with nearby play.
    static let reviewed = false
    #if DEBUG
    // TODO-review: DEBUG-only switch for the transport spike; false on main.
    // SHENGJI_NEARBY_SPIKE is defined only on the M1 spike's xcodebuild
    // command line, never by a configuration in the project.
    #if SHENGJI_NEARBY_SPIKE
    static let debugSpike = true
    #else
    static let debugSpike = false
    #endif
    static var enabled: Bool { reviewed || debugSpike }
    #else
    static var enabled: Bool { reviewed }
    #endif
    static let nearbyV = 1
    /// Must equal the NSBonjourServices entry in Info.plist.
    static let serviceType = "_shengji-nearby._tcp"
}

/// Play nearby: one phone hosts a table over Bonjour and peer-to-peer Wi-Fi,
/// up to three others join it with its code. JS sees it as `ShengjiNearby`.
///
/// The page is the live site, so this interface is a trust boundary: it takes
/// a table code and text only, never a host, port or service type, and its
/// events carry opaque random peer ids, never device names or addresses.
///
/// Every link is TCP + TLS 1.2 with a pre-shared key derived from the code
/// (NearbyKey) + WebSocket text frames of at most 16 KB. A device without the
/// code cannot finish the handshake. All state lives on `queue`.
@objc(ShengjiNearbyPlugin)
public class ShengjiNearbyPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiNearbyPlugin"
    public let jsName = "ShengjiNearby"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "capabilities", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "host", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "join", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "send", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "close", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise)
    ] + ShengjiNearbyPlugin.spikeMethods

    static let maxMessage = 16 * 1024
    static let handshakeTimeout: TimeInterval = 10
    static let findTimeout: TimeInterval = 10
    static let maxJoinTries = 8
    static let maxHandshakes = 4
    static let maxConnected = 3
    static let maxPending = 3
    static let failedHandshakeSpacing: TimeInterval = 1

    private final class Link {
        let peer: String
        let connection: NWConnection
        var ready = false
        init(peer: String, connection: NWConnection) {
            self.peer = peer
            self.connection = connection
        }
    }

    private let queue = DispatchQueue(label: "shengji.nearby")
    private var listener: NWListener?
    private var browser: NWBrowser?
    private var links: [String: Link] = [:]
    private var session = 0
    private var hostCall: CAPPluginCall?
    private var lastFailedHandshake = Date.distantPast
    // join side
    private var joinCode = ""
    private var candidates: [NWBrowser.Result] = []
    private var tried: Set<NWEndpoint> = []
    private var tries = 0
    private var attempt: Link?
    private var findDeadline = Date.distantFuture
    // permission mapping
    private var appActive = true
    private var lastBecameActive = Date.distantPast
    private var policyDenied = false
    private var observers: [NSObjectProtocol] = []
    private var live = false

    override public func load() {
        observe(UIApplication.willResignActiveNotification) { $0.appActive = false }
        observe(UIApplication.didBecomeActiveNotification) {
            $0.appActive = true
            $0.lastBecameActive = Date()
            $0.reportDenied()
        }
        observe(UIApplication.didEnterBackgroundNotification) {
            // A table is advertised only while the app is in the foreground.
            guard let listener = $0.listener else { return }
            listener.cancel()
            $0.listener = nil
            $0.emitState("failed", detail: "background")
        }
    }

    private func observe(_ name: Notification.Name, _ handle: @escaping (ShengjiNearbyPlugin) -> Void) {
        observers.append(NotificationCenter.default.addObserver(forName: name, object: nil, queue: nil) {
            [weak self] _ in
            self?.queue.async { [weak self] in if let self = self { handle(self) } }
        })
    }

    deinit {
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
    }

    // MARK: JS methods

    @objc func capabilities(_ call: CAPPluginCall) {
        call.resolve(["reviewed": NearbyBuild.reviewed, "nearbyV": NearbyBuild.nearbyV,
                      "serviceType": NearbyBuild.serviceType])
    }

    private func allowed(_ call: CAPPluginCall) -> Bool {
        if NearbyBuild.enabled { return true }
        call.reject("nearby play is not in this build", "unavailable")
        return false
    }

    @objc func host(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        guard let code = NearbyKey.normalized(call.getString("code") ?? "") else {
            call.reject("not a nearby code", "invalid")
            return
        }
        spikeOptions(call)
        queue.async { [self] in
            self.reset()
            let salt = NearbyKey.randomBytes(NearbyKey.saltBytes)
            guard let psk = NearbyKey.derive(code: code, salt: salt) else {
                call.reject("key derivation failed", "failed")
                return
            }
            let listener: NWListener
            do {
                listener = try NWListener(using: Self.parameters(psk: psk))
            } catch {
                call.reject("\(error)", "failed")
                return
            }
            let txt = NWTXTRecord(["v": "\(NearbyBuild.nearbyV)", "salt": salt.base64EncodedString()])
            listener.service = NWListener.Service(name: NearbyKey.randomName(8), type: NearbyBuild.serviceType,
                                                  domain: nil, txtRecord: txt)
            let session = self.session
            listener.stateUpdateHandler = { [weak self] state in
                guard let self = self, self.session == session else { return }
                self.listenerState(state)
            }
            listener.newConnectionHandler = { [weak self] connection in
                guard let self = self, self.session == session else { return connection.cancel() }
                self.accept(connection)
            }
            self.listener = listener
            self.hostCall = call
            self.setLive(true)
            listener.start(queue: self.queue)
        }
    }

    @objc func join(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        guard let code = NearbyKey.normalized(call.getString("code") ?? "") else {
            call.reject("not a nearby code", "invalid")
            return
        }
        spikeOptions(call)
        queue.async { [self] in
            self.reset()
            self.joinCode = code
            self.findDeadline = Date().addingTimeInterval(Self.findTimeout)
            let params = NWParameters.tcp
            params.includePeerToPeer = true
            let browser = NWBrowser(for: .bonjourWithTXTRecord(type: NearbyBuild.serviceType, domain: nil),
                                    using: params)
            let session = self.session
            browser.stateUpdateHandler = { [weak self] state in
                guard let self = self, self.session == session else { return }
                self.spikeLog("browser \(state)")
            switch state {
                case .ready: self.policyDenied = false
                case .waiting(let error), .failed(let error): self.report(error, failed: state.isFailed)
                default: break
                }
            }
            browser.browseResultsChangedHandler = { [weak self] results, _ in
                guard let self = self, self.session == session else { return }
                self.spikeLog("browse: \(results.count) result(s)")
                for result in results where !self.tried.contains(result.endpoint)
                    && !self.candidates.contains(where: { $0.endpoint == result.endpoint }) {
                    self.candidates.append(result)
                }
                self.tryNext()
            }
            self.browser = browser
            self.setLive(true)
            browser.start(queue: self.queue)
            self.queue.asyncAfter(deadline: .now() + Self.findTimeout) { [weak self] in
                guard let self = self, self.session == session else { return }
                self.checkNotFound()
            }
            call.resolve()
        }
    }

    @objc func send(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        guard let peer = call.getString("peer"), let text = call.getString("text") else {
            call.reject("peer and text are required", "invalid")
            return
        }
        let data = Data(text.utf8)
        guard data.count <= Self.maxMessage else {
            call.reject("message over 16 KB", "tooLarge")
            return
        }
        queue.async {
            guard let link = self.links[peer], link.ready else {
                call.reject("no such peer", "noPeer")
                return
            }
            let meta = NWProtocolWebSocket.Metadata(opcode: .text)
            let context = NWConnection.ContentContext(identifier: "text", metadata: [meta])
            link.connection.send(content: data, contentContext: context, isComplete: true,
                                 completion: .contentProcessed { error in
                if let error = error { call.reject("\(error)", "failed") } else { call.resolve() }
            })
        }
    }

    @objc func close(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        let peer = call.getString("peer") ?? ""
        queue.async {
            self.drop(peer)
            call.resolve()
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        queue.async {
            self.reset()
            call.resolve()
        }
    }

    // MARK: host

    private func listenerState(_ state: NWListener.State) {
        spikeLog("listener \(state)")
        switch state {
        case .ready:
            policyDenied = false
            hostCall?.resolve()
            hostCall = nil
            emitState("ready")
        case .waiting(let error):
            report(error, failed: false)
        case .failed(let error):
            report(error, failed: true)
            hostCall?.reject("\(error)", "failed")
            hostCall = nil
        default:
            break
        }
    }

    /// Inbound limits: each failed handshake tests one guess at the code, so
    /// failures are spaced and concurrent handshakes are capped.
    private func accept(_ connection: NWConnection) {
        let pending = links.values.filter { !$0.ready }.count
        let connected = links.count - pending
        guard pending < min(Self.maxHandshakes, Self.maxPending), connected < Self.maxConnected,
              Date().timeIntervalSince(lastFailedHandshake) >= Self.failedHandshakeSpacing else {
            return connection.cancel()
        }
        var peer = NearbyKey.randomName(12)
        while links[peer] != nil || peer == "host" { peer = NearbyKey.randomName(12) }
        let link = Link(peer: peer, connection: connection)
        links[peer] = link
        connection.stateUpdateHandler = { [weak self, weak link] state in
            guard let self = self, let link = link, self.links[link.peer] === link else { return }
            self.spikeLog("inbound \(link.peer) \(state)")
            switch state {
            case .ready:
                let others = self.links.values.filter { $0.ready }.count
                guard others < Self.maxConnected else { return self.drop(link.peer) }
                link.ready = true
                self.emitPeer(link.peer, "connected")
                self.receive(link)
            case .failed, .cancelled:
                if !link.ready { self.lastFailedHandshake = Date() }
                self.drop(link.peer)
            default:
                break
            }
        }
        startWithTimeout(link)
    }

    // MARK: join

    /// Tries advertised tables newest first; only the one whose key matches
    /// the code completes the handshake.
    private func tryNext() {
        guard attempt == nil, links["host"] == nil, tries < Self.maxJoinTries else { return checkNotFound() }
        guard let result = candidates.popLast() else { return checkNotFound() }
        tried.insert(result.endpoint)
        guard case .bonjour(let txt) = result.metadata, txt["v"] == "\(NearbyBuild.nearbyV)",
              let saltText = txt["salt"], let salt = Data(base64Encoded: saltText),
              salt.count == NearbyKey.saltBytes,
              let psk = NearbyKey.derive(code: joinCode, salt: salt) else { return tryNext() }
        tries += 1
        let connection = NWConnection(to: result.endpoint, using: Self.parameters(psk: psk))
        let link = Link(peer: "host", connection: connection)
        attempt = link
        connection.stateUpdateHandler = { [weak self, weak link] state in
            guard let self = self, let link = link else { return }
            self.spikeLog("outbound try \(self.tries) \(state)")
            switch state {
            case .ready:
                guard self.attempt === link else { return connection.cancel() }
                self.attempt = nil
                link.ready = true
                self.links["host"] = link
                self.browser?.cancel()
                self.browser = nil
                self.emitPeer("host", "connected")
                self.receive(link)
            case .waiting(let error):
                if Self.isPolicyDenied(error) { self.report(error, failed: false) }
            case .failed, .cancelled:
                if self.attempt === link {
                    self.attempt = nil
                    self.tryNext()
                } else if self.links["host"] === link {
                    self.drop("host")
                }
            default:
                break
            }
        }
        startWithTimeout(link)
    }

    private func checkNotFound() {
        guard links["host"] == nil, attempt == nil, browser != nil else { return }
        if tries >= Self.maxJoinTries || (Date() >= findDeadline && candidates.isEmpty) {
            browser?.cancel()
            browser = nil
            emitState("notFound")
        }
    }

    // MARK: links

    private func startWithTimeout(_ link: Link) {
        link.connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + Self.handshakeTimeout) { [weak link] in
            guard let link = link, !link.ready else { return }
            link.connection.cancel()
        }
    }

    private func receive(_ link: Link) {
        link.connection.receiveMessage { [weak self, weak link] content, context, _, error in
            guard let self = self, let link = link, self.links[link.peer] === link else { return }
            if error != nil { return self.drop(link.peer) }
            let meta = context?.protocolMetadata(definition: NWProtocolWebSocket.definition)
                as? NWProtocolWebSocket.Metadata
            switch meta?.opcode {
            case .text?:
                guard let content = content, let text = String(data: content, encoding: .utf8) else {
                    return self.drop(link.peer)
                }
                self.notifyListeners("message", data: ["peer": link.peer, "text": text])
            case .ping?, .pong?:
                break
            default:
                // Binary, continuation and close frames end the link.
                return self.drop(link.peer)
            }
            self.receive(link)
        }
    }

    private func drop(_ peer: String) {
        guard let link = links.removeValue(forKey: peer) else { return }
        link.connection.stateUpdateHandler = nil
        link.connection.cancel()
        if link.ready { emitPeer(peer, "disconnected") }
    }

    /// Ends every session; callbacks from an earlier session are ignored.
    private func reset() {
        session += 1
        listener?.cancel()
        listener = nil
        browser?.cancel()
        browser = nil
        attempt?.connection.stateUpdateHandler = nil
        attempt?.connection.cancel()
        attempt = nil
        for link in links.values {
            link.connection.stateUpdateHandler = nil
            link.connection.cancel()
        }
        links = [:]
        hostCall?.reject("stopped", "stopped")
        hostCall = nil
        candidates = []
        tried = []
        tries = 0
        joinCode = ""
        findDeadline = .distantFuture
        policyDenied = false
        setLive(false)
    }

    // MARK: protocol stack

    // TODO-review(M1): untested on device; TLS 1.3 external PSK is an M1 experiment only
    static func parameters(psk: Data) -> NWParameters {
        let tls = NWProtocolTLS.Options()
        let sec = tls.securityProtocolOptions
        let key = psk.withUnsafeBytes { DispatchData(bytes: $0) }
        let identity = Data(NearbyKey.identity.utf8).withUnsafeBytes { DispatchData(bytes: $0) }
        sec_protocol_options_add_pre_shared_key(sec, key as __DispatchData, identity as __DispatchData)
        if spikeTLS13 {
            sec_protocol_options_set_min_tls_protocol_version(sec, .TLSv13)
            sec_protocol_options_set_max_tls_protocol_version(sec, .TLSv13)
        } else {
            sec_protocol_options_append_tls_ciphersuite(
                sec, tls_ciphersuite_t(rawValue: UInt16(TLS_PSK_WITH_AES_128_GCM_SHA256))!)
            sec_protocol_options_set_min_tls_protocol_version(sec, .TLSv12)
            sec_protocol_options_set_max_tls_protocol_version(sec, .TLSv12)
        }
        let tcp = NWProtocolTCP.Options()
        tcp.enableKeepalive = true
        let params = NWParameters(tls: tls, tcp: tcp)
        params.includePeerToPeer = true
        let ws = NWProtocolWebSocket.Options()
        ws.autoReplyPing = true
        ws.maximumMessageSize = maxMessage
        params.defaultProtocolStack.applicationProtocols.insert(ws, at: 0)
        return params
    }

    // MARK: states and events

    static func isPolicyDenied(_ error: NWError) -> Bool {
        if case .dns(let code) = error { return code == DNSServiceErrorType(kDNSServiceErr_PolicyDenied) }
        return false
    }

    private func report(_ error: NWError, failed: Bool) {
        spikeLog("error (\(failed ? "failed" : "waiting")): \(error.debugDescription) [\(error)]")
        if Self.isPolicyDenied(error) {
            policyDenied = true
            return reportDenied()
        }
        if Self.wifiOff(error) { return emitState("wifiOff") }
        if failed { emitState("failed", detail: error.debugDescription) } else { emitState("waiting") }
    }

    /// The system's Local Network alert makes the app resign active and the
    /// browser or listener reports PolicyDenied while it is on screen, so the
    /// denial counts only once it persists about 1 s after the app is active.
    // TODO-review(M1): confirm on device
    private func reportDenied() {
        guard policyDenied, appActive else { return }
        let settle = lastBecameActive.addingTimeInterval(1).timeIntervalSinceNow
        if settle > 0 {
            let session = self.session
            queue.asyncAfter(deadline: .now() + settle) { [weak self] in
                guard let self = self, self.session == session else { return }
                self.reportDenied()
            }
            return
        }
        policyDenied = false
        emitState("denied")
    }

    // TODO-review(M1): record the exact error for Wi-Fi off on device; network-down
    // codes are the best guess, and Wi-Fi on with no access point must not match.
    static func wifiOff(_ error: NWError) -> Bool {
        if case .posix(let code) = error { return code == .ENETDOWN || code == .ENETUNREACH }
        return false
    }

    private func emitState(_ state: String, detail: String? = nil) {
        var data: [String: Any] = ["state": state]
        if let detail = detail { data["detail"] = detail }
        notifyListeners("state", data: data)
    }

    private func emitPeer(_ peer: String, _ state: String) {
        notifyListeners("peer", data: ["peer": peer, "state": state])
    }

    /// A phone waiting for its turn must not auto-lock and drop its link.
    private func setLive(_ on: Bool) {
        guard on != live else { return }
        live = on
        DispatchQueue.main.async { UIApplication.shared.isIdleTimerDisabled = on }
    }
}

// MARK: M1 spike

#if DEBUG && SHENGJI_NEARBY_SPIKE
/// The M1 transport spike's extras (nearby-spike.html): a raw state log, a
/// PBKDF2 timing and a TLS 1.3 PSK switch. Compiled only with
/// SHENGJI_NEARBY_SPIKE in a Debug build.
extension ShengjiNearbyPlugin {
    static let spikeMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "spikeBench", returnType: CAPPluginReturnPromise)
    ]
    static var spikeTLS13 = false

    func spikeOptions(_ call: CAPPluginCall) {
        Self.spikeTLS13 = call.getBool("tls13") ?? false
        spikeLog("tls \(Self.spikeTLS13 ? "1.3" : "1.2") psk")
    }

    func spikeLog(_ text: String) {
        notifyListeners("spikeLog", data: ["text": text])
    }

    /// Milliseconds for one key derivation at `iterations` (median of `runs`).
    @objc func spikeBench(_ call: CAPPluginCall) {
        let iterations = UInt32(call.getInt("iterations") ?? Int(NearbyKey.iterations))
        let runs = max(1, min(call.getInt("runs") ?? 5, 20))
        DispatchQueue.global(qos: .userInitiated).async {
            let salt = NearbyKey.randomBytes(NearbyKey.saltBytes)
            var times: [Double] = []
            for _ in 0..<runs {
                let start = DispatchTime.now().uptimeNanoseconds
                _ = NearbyKey.derive(code: "ABCDEF", salt: salt, iterations: iterations)
                times.append(Double(DispatchTime.now().uptimeNanoseconds - start) / 1e6)
            }
            times.sort()
            call.resolve(["iterations": Int(iterations), "ms": times[times.count / 2],
                          "all": times, "model": Self.modelName()])
        }
    }

    static func modelName() -> String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { raw in
            String(decoding: raw.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
    }
}
#else
extension ShengjiNearbyPlugin {
    static let spikeMethods: [CAPPluginMethod] = []
    static let spikeTLS13 = false
    func spikeOptions(_ call: CAPPluginCall) {}
    func spikeLog(_ text: @autoclosure () -> String) {}
}
#endif

private extension NWBrowser.State {
    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }
}
#endif
