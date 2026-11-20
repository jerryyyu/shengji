import Foundation
import Network
import Security
import CommonCrypto

/// The table key: PBKDF2-HMAC-SHA256 over the table code with the table's
/// salt. A 25-bit code behind a fast KDF falls to an offline search of one
/// recorded handshake, so the derivation is deliberately slow, and the
/// per-table salt makes every table's key different.
enum NearbyKey {
    // About 44 ms on an iPhone 14 Pro, an estimated 250 ms on the oldest
    // supported phone: slow for an offline search, quick enough for a join.
    static let iterations: UInt32 = 150_000
    static let identity = "shengji-nearby-v1"
    static let saltBytes = 16
    /// The online code alphabet: no I, O, 0 or 1.
    static let alphabet = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    static let codeLength = 5

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

/// Why the screen must stay awake: a game at the table or a live nearby
/// session. The idle timer is the system's again only when neither holds.
struct AwakeReasons {
    var game = false
    var nearby = false
    var any: Bool { game || nearby }
}

/// When a host's listener is made again. One that is waiting (made while
/// the Local Network alert was up, or before the network was there) has
/// nothing that wakes it, so it is made again after a backoff that doubles
/// from `first` to `max`; one that fails before it was ever up is retried
/// `failRetries` times (any number while the permission is the cause)
/// before the host's call rejects; one that fails after it was up was
/// stopped by the system, and is advertised again on the app's return.
struct ListenerRetry {
    static let first: TimeInterval = 1
    static let max: TimeInterval = 8
    static let failRetries = 3
    enum OnFailed: Equatable { case lost, retry, reject }

    private(set) var delay = first
    private(set) var failures = 0

    /// The wait before the next listener, doubling each time.
    mutating func nextDelay() -> TimeInterval {
        let d = delay
        delay = min(delay * 2, Self.max)
        return d
    }

    mutating func ready() {
        delay = Self.first
        failures = 0
    }

    mutating func failed(wasUp: Bool, policyDenied: Bool) -> OnFailed {
        if wasUp { return .lost }
        failures += 1
        return policyDenied || failures <= Self.failRetries ? .retry : .reject
    }
}

/// How a joiner looks for its table. A seat's resume (the page has its
/// token) looks for a short time and the page starts the next look at once,
/// so a network that comes back is noticed within seconds; a first look
/// keeps the longer search. The table the last link went to is tried first.
enum JoinPlan {
    static let findTimeout: TimeInterval = 12
    static let resumeFindTimeout: TimeInterval = 4

    static func findTimeout(resuming: Bool) -> TimeInterval {
        resuming ? resumeFindTimeout : findTimeout
    }

    /// The candidates in try order for a stack popped from its end: the one
    /// named `prefer` (the last host's service) last, so it is tried first;
    /// the rest keep their order.
    static func ordered<T>(_ items: [T], name: (T) -> String?, prefer: String?) -> [T] {
        guard let prefer = prefer else { return items }
        return items.filter { name($0) != prefer } + items.filter { name($0) == prefer }
    }
}

/// The phone's network path, as NWPathMonitor reports it: `update` says
/// whether this report is a regain (satisfied after unsatisfied), when the
/// look must start over on fresh endpoints.
struct PathWatch {
    private(set) var satisfied: Bool?

    mutating func update(_ now: Bool) -> Bool {
        let regained = now && satisfied == false
        satisfied = now
        return regained
    }
}

#if !NEARBY_KEY_ONLY
import UIKit
import Capacitor

/// One idle-timer switch for every reason to keep the screen awake, so one
/// reason ending does not let the phone lock while another still holds.
/// Reasons are kept and applied on the main thread.
enum ScreenAwake {
    private static var reasons = AwakeReasons()

    static func set(game on: Bool) { update { $0.game = on } }
    static func set(nearby on: Bool) { update { $0.nearby = on } }

    private static func update(_ change: @escaping (inout AwakeReasons) -> Void) {
        let apply = {
            change(&reasons)
            UIApplication.shared.isIdleTimerDisabled = reasons.any
        }
        if Thread.isMainThread { apply() } else { DispatchQueue.main.async(execute: apply) }
    }
}

/// Which binaries may run the nearby transport. It is untested on devices,
/// so every method but `capabilities` refuses unless one of these is true.
enum NearbyBuild {
    // TODO-review: true only in the binary App Review sees with nearby play.
    static let reviewed = false
    // A Debug-only switch: SHENGJI_NEARBY_SPIKE and SHENGJI_NEARBY_DEV are
    // defined only on an xcodebuild command line, never by a configuration in
    // the project, and a Release build is always false here.
    #if DEBUG && (SHENGJI_NEARBY_SPIKE || SHENGJI_NEARBY_DEV)
    static let debugBuild = true
    #else
    static let debugBuild = false
    #endif
    static var enabled: Bool { reviewed || debugBuild }
    static let nearbyV = 2
    /// Must equal the NSBonjourServices entry in Info.plist.
    static let serviceType = "_shengji-nearby._tcp"
}

/// Play nearby: one phone hosts a table over Bonjour and peer-to-peer Wi-Fi,
/// up to three others join it with its code. JS sees it as `ShengjiNearby`.
///
/// The page is the live site, so this interface is a trust boundary: it takes
/// a table code and text only, never a host, port or service type, and its
/// events carry opaque random peer and device ids, never device names or
/// addresses.
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
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "openSettings", returnType: CAPPluginReturnPromise)
    ] + ShengjiNearbyPlugin.spikeMethods

    static let maxMessage = 16 * 1024
    /// An inbound link must finish its handshake this soon.
    static let handshakeTimeout: TimeInterval = 5
    /// Each table the joiner tries gets this long; several are tried at once.
    static let joinHandshakeTimeout: TimeInterval = 3
    static let maxParallelTries = 4
    /// Once every table found has refused the code, a wrong code is reported
    /// after this pause unless another table appears.
    static let allFailedGrace: TimeInterval = 1
    /// A host away from the app longer than this ends its table.
    static let hostWindow: TimeInterval = 60
    static let maxJoinTries = 8
    /// Three seats, one joiner whose new link lands before the host closes
    /// its old one, and one more that is only looking at the seats.
    static let maxConnected = 5
    static let maxPending = 4
    /// Handshakes in flight from one remote address.
    static let maxPendingPerAddress = 2
    /// After a failed handshake, that address waits this long before its next
    /// one, so each address tests at most one guess at the code per second.
    /// Other addresses are not held up by it.
    static let failedHandshakeSpacing: TimeInterval = 1

    private final class Link {
        let peer: String
        let connection: NWConnection
        /// The remote address (host side only), never sent to JS.
        let remote: String
        var ready = false
        init(peer: String, connection: NWConnection, remote: String = "") {
            self.peer = peer
            self.connection = connection
            self.remote = remote
        }
    }

    private let queue = DispatchQueue(label: "shengji.nearby")
    private var listener: NWListener?
    private var browser: NWBrowser?
    private var links: [String: Link] = [:]
    private var session = 0
    private var hostCall: CAPPluginCall?
    /// When each remote address last failed a handshake (host side).
    private var failedAt: [String: Date] = [:]
    /// An opaque id per remote address for this table, so the page can tell
    /// two links from one phone apart from two phones.
    private var deviceIds: [String: String] = [:]
    // host side: the table's key and salt, kept so the same table can be
    // advertised again after the system stops the listener
    private var hostCode = ""
    private var hostSalt: Data?
    private var hostPsk: Data?
    private var needsReadvertise = false
    /// The current listener has reported ready (host side).
    private var listenerReady = false
    private var listenerRetry = ListenerRetry()
    private var listenerRetryArmed = false
    private var backgroundedAt: Date?
    /// Main thread only.
    private var backgroundTask = UIBackgroundTaskIdentifier.invalid
    // join side
    private var joinCode = ""
    private var candidates: [NWBrowser.Result] = []
    private var tried: Set<NWEndpoint> = []
    private var tries = 0
    private var attempts: [Link] = []
    private var findDeadline = Date.distantFuture
    private var candidateArrivals = 0
    /// A table answered with another nearby version (and none with this one).
    private var sawOtherVersion = false
    // permission mapping
    private var appActive = true
    private var lastBecameActive = Date.distantPast
    private var policyDenied = false
    /// Once a session reports "denied", it reports no "notFound".
    private var deniedReported = false
    private var observers: [NSObjectProtocol] = []
    private var live = false
    /// This join is a seat's resume: short looks (JoinPlan).
    private var resuming = false
    /// The service name of the table the last link went to, across sessions.
    private var lastHostName: String?
    private let pathMonitor = NWPathMonitor()
    private var pathWatch = PathWatch()

    private var lookTime: TimeInterval { JoinPlan.findTimeout(resuming: resuming) }

    override public func load() {
        observe(UIApplication.willResignActiveNotification) {
            $0.appActive = false
            $0.joinPaused()
        }
        observe(UIApplication.didBecomeActiveNotification) {
            $0.appActive = true
            $0.lastBecameActive = Date()
            $0.reportDenied()
            $0.hostReturned()
            $0.listenerCheck()
            $0.joinResumed()
        }
        observe(UIApplication.willEnterForegroundNotification) { $0.hostReturned() }
        observe(UIApplication.didEnterBackgroundNotification) { $0.hostLeft() }
        pathMonitor.pathUpdateHandler = { [weak self] path in
            // on `queue`, as every other callback
            guard let self = self else { return }
            let satisfied = path.status == .satisfied
            let regained = self.pathWatch.update(satisfied)
            self.spikeLog("path \(path.status)\(regained ? " (regained)" : "")")
            self.notifyListeners("path", data: ["satisfied": satisfied])
            if regained { self.lookAgainOnNewPath() }
        }
        pathMonitor.start(queue: queue)
    }

    /// The network came back during a look: endpoints found or tried on the
    /// old path are stale, so every try is cancelled and the look starts
    /// over with a new browser, as a new join would.
    private func lookAgainOnNewPath() {
        guard !joinCode.isEmpty, links["host"] == nil else { return }
        spikeLog("look again on the new path")
        for link in attempts {
            link.connection.stateUpdateHandler = nil
            link.connection.cancel()
        }
        attempts = []
        browser?.stateUpdateHandler = nil
        browser?.browseResultsChangedHandler = nil
        browser?.cancel()
        browser = nil
        candidates = []
        tried = []
        tries = 0
        candidateArrivals = 0
        sawOtherVersion = false
        startBrowse()
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
        call.resolve(["reviewed": NearbyBuild.reviewed, "debug": NearbyBuild.debugBuild,
                      "nearbyV": NearbyBuild.nearbyV, "serviceType": NearbyBuild.serviceType])
    }

    @objc func openSettings(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        DispatchQueue.main.async {
            if let url = URL(string: UIApplication.openSettingsURLString) {
                UIApplication.shared.open(url)
            }
            call.resolve()
        }
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
            self.hostCode = code
            self.hostSalt = salt
            self.hostPsk = psk
            self.hostCall = call
            self.setLive(true)
            do {
                try self.startListener(psk: psk, salt: salt)
            } catch {
                self.hostCall = nil
                self.reset()
                call.reject("\(error)", "failed")
            }
        }
    }

    @objc func join(_ call: CAPPluginCall) {
        guard allowed(call) else { return }
        guard let code = NearbyKey.normalized(call.getString("code") ?? "") else {
            call.reject("not a nearby code", "invalid")
            return
        }
        spikeOptions(call)
        let resume = call.getBool("resume") ?? false
        queue.async { [self] in
            self.reset()
            self.joinCode = code
            self.resuming = resume
            self.spikeLog("join (\(resume ? "resume, \(JoinPlan.resumeFindTimeout) s look" : "first look"))")
            self.setLive(true)
            self.startBrowse()
            call.resolve()
        }
    }

    /// A new browser for the current look, with the look's time from now.
    private func startBrowse() {
        findDeadline = Date().addingTimeInterval(lookTime)
        let params = NWParameters.tcp
        params.includePeerToPeer = true
        let browser = NWBrowser(for: .bonjourWithTXTRecord(type: NearbyBuild.serviceType, domain: nil),
                                using: params)
        let session = self.session
        browser.stateUpdateHandler = { [weak self, weak browser] state in
            guard let self = self, self.session == session, self.browser === browser else { return }
            self.spikeLog("browser \(state)")
            switch state {
            case .ready: self.policyDenied = false
            case .waiting(let error), .failed(let error): self.report(error, failed: state.isFailed)
            default: break
            }
        }
        browser.browseResultsChangedHandler = { [weak self, weak browser] results, _ in
            guard let self = self, self.session == session, self.browser === browser else { return }
            self.spikeLog("browse: \(results.count) result(s)")
            for result in results where !self.tried.contains(result.endpoint)
                && !self.candidates.contains(where: { $0.endpoint == result.endpoint }) {
                self.candidates.append(result)
                self.candidateArrivals += 1
            }
            self.tryNext()
        }
        self.browser = browser
        browser.start(queue: queue)
        let deadline = findDeadline
        queue.asyncAfter(deadline: .now() + lookTime) { [weak self] in
            guard let self = self, self.session == session, self.findDeadline == deadline else { return }
            self.checkNotFound()
        }
    }

    static func serviceName(_ endpoint: NWEndpoint) -> String? {
        if case .service(let name, _, _, _) = endpoint { return name }
        return nil
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
                self.spikeLog("send \(peer) refused: no ready link")
                call.reject("no such peer", "noPeer")
                return
            }
            let meta = NWProtocolWebSocket.Metadata(opcode: .text)
            let context = NWConnection.ContentContext(identifier: "text", metadata: [meta])
            let started = DispatchTime.now().uptimeNanoseconds
            link.connection.send(content: data, contentContext: context, isComplete: true,
                                 completion: .contentProcessed { error in
                let ms = Double(DispatchTime.now().uptimeNanoseconds - started) / 1e6
                self.spikeLog("send \(peer) \(data.count) B \(error.map { "error \($0)" } ?? "ok") \(String(format: "%.0f", ms)) ms")
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

    private var hosting: Bool { hostPsk != nil }

    /// Advertises the table under a new random instance name, with the salt
    /// in its TXT record; the session is unchanged, so existing links stay.
    private func startListener(psk: Data, salt: Data) throws {
        let listener = try NWListener(using: Self.parameters(psk: psk))
        let txt = NWTXTRecord(["v": "\(NearbyBuild.nearbyV)", "salt": salt.base64EncodedString()])
        listener.service = NWListener.Service(name: NearbyKey.randomName(8), type: NearbyBuild.serviceType,
                                              domain: nil, txtRecord: txt)
        let session = self.session
        listener.stateUpdateHandler = { [weak self, weak listener] state in
            guard let self = self, self.session == session, let listener = listener,
                  self.listener === listener else { return }
            self.listenerState(state)
        }
        listener.newConnectionHandler = { [weak self] connection in
            guard let self = self, self.session == session else { return connection.cancel() }
            self.accept(connection)
        }
        needsReadvertise = false
        listenerReady = false
        self.listener = listener
        spikeLog("listener start")
        listener.start(queue: queue)
    }

    private func listenerState(_ state: NWListener.State) {
        spikeLog("listener \(state)")
        switch state {
        case .ready:
            policyDenied = false
            listenerReady = true
            listenerRetry.ready()
            hostCall?.resolve()
            hostCall = nil
            emitState("ready")
        case .waiting(let error):
            // a listener made while the Local Network alert was up, or before
            // the network was there, can stay waiting with nothing to wake
            // it: it is made again until it is ready
            report(error, failed: false)
            retryListenerSoon()
        case .failed(let error):
            switch listenerRetry.failed(wasUp: hosting && hostCall == nil, policyDenied: Self.isPolicyDenied(error)) {
            case .lost: return listenerLost()
            case .retry:
                report(error, failed: false)
                return retryListenerSoon()
            case .reject: break
            }
            report(error, failed: true)
            hostCall?.reject("\(error)", "failed")
            hostCall = nil
        case .cancelled:
            if hosting && hostCall == nil { listenerLost() }
        default:
            break
        }
    }

    /// Makes the listener again after the current backoff, unless it is
    /// ready by then; the same key and salt, so the code still joins it.
    private func retryListenerSoon() {
        guard hosting, !listenerRetryArmed else { return }
        listenerRetryArmed = true
        let delay = listenerRetry.nextDelay()
        spikeLog("listener retry in \(delay) s")
        let session = self.session
        queue.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self = self, self.session == session else { return }
            self.listenerRetryArmed = false
            self.remakeListener()
        }
    }

    /// Back in the app (the Local Network alert has closed, say): a listener
    /// that is not ready is made again now.
    private func listenerCheck() {
        guard hosting, backgroundedAt == nil, !listenerReady, listener != nil else { return }
        spikeLog("listener not ready on becoming active")
        remakeListener()
    }

    private func remakeListener() {
        guard hosting, !listenerReady, appActive, let psk = hostPsk, let salt = hostSalt else { return }
        if let old = listener {
            old.stateUpdateHandler = nil
            old.newConnectionHandler = nil
            old.cancel()
            listener = nil
        }
        do {
            try startListener(psk: psk, salt: salt)
        } catch {
            spikeLog("listener remake failed: \(error)")
            retryListenerSoon()
        }
    }

    /// The system stopped advertising a table that was up (it does so when
    /// the app leaves the foreground); the table is advertised again when the
    /// app returns.
    private func listenerLost() {
        listenerReady = false
        listener?.stateUpdateHandler = nil
        listener?.cancel()
        listener = nil
        needsReadvertise = true
        emitState("waiting", detail: "background")
        // a failure that lands after the app is already back in the
        // foreground has no return notification still to come: advertise
        // again from here
        guard appActive, backgroundedAt == nil else { return }
        let session = self.session
        queue.asyncAfter(deadline: .now() + 1) { [weak self] in
            guard let self = self, self.session == session, self.hosting, self.appActive,
                  self.needsReadvertise else { return }
            self.hostReturned()
        }
    }

    /// A host leaving the app keeps its listener and links while iOS allows,
    /// under a background task.
    private func hostLeft() {
        guard hosting else { return }
        backgroundedAt = Date()
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.backgroundTask == .invalid else { return }
            self.backgroundTask = UIApplication.shared.beginBackgroundTask(withName: "nearby-host") {
                [weak self] in self?.endBackgroundTaskOnMain()
            }
        }
    }

    /// Back in the app: a host away longer than `hostWindow` ends its table;
    /// otherwise a table the system stopped is advertised again with the same
    /// key and salt, so the same code still joins it.
    private func hostReturned() {
        DispatchQueue.main.async { [weak self] in self?.endBackgroundTaskOnMain() }
        guard hosting else { return }
        let awayAt = backgroundedAt
        backgroundedAt = nil
        if let awayAt = awayAt, Date().timeIntervalSince(awayAt) > Self.hostWindow {
            reset()
            return emitState("ended")
        }
        guard listener == nil || needsReadvertise, let psk = hostPsk, let salt = hostSalt else { return }
        if let old = listener {
            old.stateUpdateHandler = nil
            old.cancel()
            listener = nil
        }
        do {
            try startListener(psk: psk, salt: salt)
        } catch {
            needsReadvertise = true
            emitState("failed", detail: "\(error)")
        }
    }

    private func endBackgroundTaskOnMain() {
        guard backgroundTask != .invalid else { return }
        UIApplication.shared.endBackgroundTask(backgroundTask)
        backgroundTask = .invalid
    }

    /// The remote address of an inbound connection, as a key; never sent to JS.
    static func remoteAddress(_ endpoint: NWEndpoint) -> String {
        if case .hostPort(let host, _) = endpoint { return "\(host)" }
        return "\(endpoint)"
    }

    /// Inbound limits: each failed handshake tests one guess at the code, so
    /// an address that failed waits before its next one, and handshakes in
    /// flight are capped overall and per address. Nothing one address does
    /// holds up another's join.
    private func accept(_ connection: NWConnection) {
        let remote = Self.remoteAddress(connection.endpoint)
        let pending = links.values.filter { !$0.ready }
        let connected = links.count - pending.count
        let now = Date()
        failedAt = failedAt.filter { now.timeIntervalSince($0.value) < Self.failedHandshakeSpacing }
        guard pending.count < Self.maxPending, connected < Self.maxConnected,
              pending.filter({ $0.remote == remote }).count < Self.maxPendingPerAddress,
              failedAt[remote] == nil else {
            spikeLog("inbound refused: pending \(pending.count) connected \(connected) spaced \(failedAt[remote] != nil)")
            return connection.cancel()
        }
        var peer = NearbyKey.randomName(12)
        while links[peer] != nil || peer == "host" { peer = NearbyKey.randomName(12) }
        let link = Link(peer: peer, connection: connection, remote: remote)
        links[peer] = link
        connection.stateUpdateHandler = { [weak self, weak link] state in
            guard let self = self, let link = link, self.links[link.peer] === link else { return }
            self.spikeLog("inbound \(link.peer) \(state)")
            switch state {
            case .ready:
                let others = self.links.values.filter { $0.ready }.count
                guard others < Self.maxConnected else { return self.drop(link.peer) }
                link.ready = true
                self.emitPeer(link.peer, "connected", device: self.deviceId(link.remote))
                self.receive(link)
            case .failed, .cancelled:
                if !link.ready { self.failedAt[link.remote] = Date() }
                self.drop(link.peer)
            default:
                break
            }
        }
        startWithTimeout(link, Self.handshakeTimeout)
    }

    private func deviceId(_ remote: String) -> String {
        if let id = deviceIds[remote] { return id }
        var id = NearbyKey.randomName(12)
        while deviceIds.values.contains(id) { id = NearbyKey.randomName(12) }
        deviceIds[remote] = id
        return id
    }

    // MARK: join

    /// Tries advertised tables newest first, up to `maxParallelTries` at
    /// once, each for `joinHandshakeTimeout`; only the one whose key matches
    /// the code completes the handshake, and the rest are then cancelled. A
    /// table that stalls its handshake holds up only its own try.
    // TODO-review(M3): parallel tries and the 3 s timeout are unconfirmed on device
    private func tryNext() {
        guard links["host"] == nil else { return }
        candidates = JoinPlan.ordered(candidates, name: { Self.serviceName($0.endpoint) }, prefer: lastHostName)
        while attempts.count < Self.maxParallelTries, tries < Self.maxJoinTries, let result = candidates.popLast() {
            tried.insert(result.endpoint)
            guard case .bonjour(let txt) = result.metadata else { continue }
            guard txt["v"] == "\(NearbyBuild.nearbyV)" else {
                sawOtherVersion = true
                continue
            }
            guard let saltText = txt["salt"], let salt = Data(base64Encoded: saltText),
                  salt.count == NearbyKey.saltBytes,
                  let psk = NearbyKey.derive(code: joinCode, salt: salt) else { continue }
            tries += 1
            tryTable(result.endpoint, psk: psk)
        }
        if attempts.isEmpty { checkNotFound() }
    }

    private func tryTable(_ endpoint: NWEndpoint, psk: Data) {
        let connection = NWConnection(to: endpoint, using: Self.parameters(psk: psk))
        let link = Link(peer: "host", connection: connection)
        attempts.append(link)
        connection.stateUpdateHandler = { [weak self, weak link] state in
            guard let self = self, let link = link else { return }
            self.spikeLog("outbound try \(self.tries) \(state)")
            switch state {
            case .ready:
                guard self.attempts.contains(where: { $0 === link }), self.links["host"] == nil else {
                    return connection.cancel()
                }
                self.attempts.removeAll { $0 === link }
                // the other tries are tables that are not this one
                for other in self.attempts {
                    other.connection.stateUpdateHandler = nil
                    other.connection.cancel()
                }
                self.attempts = []
                link.ready = true
                self.links["host"] = link
                self.lastHostName = Self.serviceName(endpoint)
                self.browser?.cancel()
                self.browser = nil
                self.emitPeer("host", "connected")
                self.receive(link)
            case .waiting(let error):
                if Self.isPolicyDenied(error) { self.report(error, failed: false) }
            case .failed, .cancelled:
                if self.attempts.contains(where: { $0 === link }) {
                    self.attempts.removeAll { $0 === link }
                    self.tryNext()
                } else if self.links["host"] === link {
                    self.drop("host")
                }
            default:
                break
            }
        }
        startWithTimeout(link, Self.joinHandshakeTimeout)
    }

    /// The app left the foreground during a join, most often for the
    /// system's Local Network prompt: the page holds its look meanwhile.
    private func joinPaused() {
        guard joining else { return }
        emitState("waiting", detail: "prompt")
    }

    /// Back in the app during a join: the look's time starts over, so a slow
    /// answer to the prompt never reads as no table nearby.
    // TODO-review(M3): confirm the prompt's resign/become-active order on device
    private func joinResumed() {
        guard joining else { return }
        findDeadline = Date().addingTimeInterval(lookTime)
        emitState("waiting", detail: "active")
        let session = self.session
        queue.asyncAfter(deadline: .now() + lookTime) { [weak self] in
            guard let self = self, self.session == session else { return }
            self.checkNotFound()
        }
        tryNext()
    }

    private var joining: Bool { !joinCode.isEmpty && browser != nil && links["host"] == nil }

    private func checkNotFound() {
        guard !deniedReported, links["host"] == nil, attempts.isEmpty, browser != nil else { return }
        // while the prompt is up, or a denial is still settling, nothing is
        // reported; joinResumed starts the look's time over
        guard appActive, !policyDenied else { return }
        if tries >= Self.maxJoinTries || (Date() >= findDeadline && candidates.isEmpty) {
            return emitNotFound()
        }
        if allTriedFailed {
            // Every table found refused the code: a wrong or stale code is
            // reported now unless another table appears within the grace.
            let session = self.session, arrivals = candidateArrivals, tries = self.tries
            queue.asyncAfter(deadline: .now() + Self.allFailedGrace) { [weak self] in
                guard let self = self, self.session == session, self.candidateArrivals == arrivals,
                      self.tries == tries, self.allTriedFailed, !self.deniedReported else { return }
                self.emitNotFound()
            }
        }
    }

    private var allTriedFailed: Bool {
        (tries > 0 || sawOtherVersion) && candidates.isEmpty && attempts.isEmpty && links["host"] == nil
            && browser != nil
    }

    /// Not found; or, when the only tables found run another nearby version,
    /// "version", which asks for the app to be updated.
    private func emitNotFound() {
        guard !deniedReported else { return }
        browser?.cancel()
        browser = nil
        emitState(sawOtherVersion && tries == 0 ? "version" : "notFound")
    }

    // MARK: links

    private func startWithTimeout(_ link: Link, _ timeout: TimeInterval) {
        link.connection.start(queue: queue)
        queue.asyncAfter(deadline: .now() + timeout) { [weak link] in
            guard let link = link, !link.ready else { return }
            link.connection.cancel()
        }
    }

    private func receive(_ link: Link) {
        link.connection.receiveMessage { [weak self, weak link] content, context, _, error in
            guard let self = self, let link = link, self.links[link.peer] === link else { return }
            if let error = error {
                self.spikeLog("recv \(link.peer) error \(error)")
                return self.drop(link.peer)
            }
            let meta = context?.protocolMetadata(definition: NWProtocolWebSocket.definition)
                as? NWProtocolWebSocket.Metadata
            switch meta?.opcode {
            case .text?:
                guard let content = content, let text = String(data: content, encoding: .utf8) else {
                    return self.drop(link.peer)
                }
                self.spikeLog("recv \(link.peer) \(content.count) B")
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
        spikeLog("drop \(peer)\(link.ready ? "" : " (not ready)")")
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
        for link in attempts {
            link.connection.stateUpdateHandler = nil
            link.connection.cancel()
        }
        attempts = []
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
        sawOtherVersion = false
        failedAt = [:]
        deviceIds = [:]
        joinCode = ""
        resuming = false
        findDeadline = .distantFuture
        candidateArrivals = 0
        policyDenied = false
        deniedReported = false
        hostCode = ""
        hostSalt = nil
        hostPsk = nil
        needsReadvertise = false
        listenerReady = false
        listenerRetry = ListenerRetry()
        listenerRetryArmed = false
        backgroundedAt = nil
        DispatchQueue.main.async { [weak self] in self?.endBackgroundTaskOnMain() }
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
        // game frames are small and each one is a move someone waits on
        tcp.noDelay = true
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
        deniedReported = true
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

    private func emitPeer(_ peer: String, _ state: String, device: String? = nil) {
        var data: [String: Any] = ["peer": peer, "state": state]
        if let device = device { data["device"] = device }
        notifyListeners("peer", data: data)
    }

    /// A phone waiting for its turn must not auto-lock and drop its link.
    private func setLive(_ on: Bool) {
        guard on != live else { return }
        live = on
        ScreenAwake.set(nearby: on)
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
        NSLog("nearby: %@", text)
        notifyListeners("spikeLog", data: ["text": text])
        notifyListeners("debugLog", data: ["text": text])
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
    /// The device-test log: in a Debug build made for the device test
    /// (SHENGJI_NEARBY_DEV), each line goes to the console and to the page's
    /// debug pane; in any other build it is never even formatted.
    func spikeLog(_ text: @autoclosure () -> String) {
        guard NearbyBuild.debugBuild else { return }
        let line = text()
        NSLog("nearby: %@", line)
        notifyListeners("debugLog", data: ["text": line])
    }
}
#endif

private extension NWBrowser.State {
    var isFailed: Bool {
        if case .failed = self { return true }
        return false
    }
}
#endif
