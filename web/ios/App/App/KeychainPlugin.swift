import Foundation
import Capacitor
import Security

/// The app's one device secret in the Keychain: a single generic-password item
/// under a fixed service and account. The Keychain keeps it when the app is
/// deleted, so a reinstall reads the same value back. It is readable after the
/// first unlock since boot (a background reconnect can reach it) and never
/// leaves this device: "ThisDeviceOnly" keeps it out of iCloud Keychain and
/// out of a restore onto another phone.
enum DeviceKeychain {
    static let service = "com.jerryyu.shengji.device"
    static let account = "device-credential"

    private static var base: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    /// The stored value, nil when there is none, or the failing OSStatus.
    static func read() -> Result<String?, KeychainError> {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return .success(nil) }
        guard status == errSecSuccess else { return .failure(KeychainError(status: status)) }
        guard let data = item as? Data, let value = String(data: data, encoding: .utf8) else {
            return .failure(KeychainError(status: errSecDecode))
        }
        return .success(value)
    }

    /// Replaces the stored value, or adds it when there is none.
    static func write(_ value: String) -> Result<Void, KeychainError> {
        let data = Data(value.utf8)
        let attributes: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        var status = SecItemUpdate(base as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var add = base
            add.merge(attributes) { _, new in new }
            status = SecItemAdd(add as CFDictionary, nil)
        }
        return status == errSecSuccess ? .success(()) : .failure(KeychainError(status: status))
    }

    /// Deletes the stored value; deleting nothing succeeds.
    static func delete() -> Result<Void, KeychainError> {
        let status = SecItemDelete(base as CFDictionary)
        return status == errSecSuccess || status == errSecItemNotFound
            ? .success(()) : .failure(KeychainError(status: status))
    }
}

struct KeychainError: Error {
    let status: OSStatus
    var code: String { String(status) }
    var message: String { "keychain error \(status)" }
}

/// The device secret for the page:
/// - `get()` resolves `{value}`, the stored string or null;
/// - `set({value})` stores a non-empty string, replacing any earlier one;
/// - `remove()` deletes it.
/// A Keychain failure rejects with the OSStatus as the call's code. The value
/// itself is never logged or put in an error.
@objc(ShengjiKeychainPlugin)
public class ShengjiKeychainPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "ShengjiKeychainPlugin"
    public let jsName = "ShengjiKeychain"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "get", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "set", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "remove", returnType: CAPPluginReturnPromise)
    ]

    @objc func get(_ call: CAPPluginCall) {
        switch DeviceKeychain.read() {
        case .success(let value?): call.resolve(["value": value])
        case .success(nil): call.resolve(["value": NSNull()])
        case .failure(let error): call.reject(error.message, error.code)
        }
    }

    @objc func set(_ call: CAPPluginCall) {
        guard let value = call.getString("value"), !value.isEmpty else {
            call.reject("value must be a non-empty string")
            return
        }
        switch DeviceKeychain.write(value) {
        case .success: call.resolve()
        case .failure(let error): call.reject(error.message, error.code)
        }
    }

    @objc func remove(_ call: CAPPluginCall) {
        switch DeviceKeychain.delete() {
        case .success: call.resolve()
        case .failure(let error): call.reject(error.message, error.code)
        }
    }
}
