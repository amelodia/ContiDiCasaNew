import Foundation
import LocalAuthentication
import Security

/// Accesso alternativo con Face ID / Touch ID: password nel Keychain con controllo accesso biometrico.
enum ContiLightBiometricLogin {
    private static let service = "com.contidicasa.contilight.credential.v1"
    private static let emailDefaultsKey = "ContiLight.biometricKeychainEmail"

    static func biometricsAvailable() -> Bool {
        let ctx = LAContext()
        var err: NSError?
        return ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err)
    }

    /// Nome hardware per etichette (Face ID, Touch ID, …).
    static func biometricLabel() -> String {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err) else {
            return "Face ID o Touch ID"
        }
        switch ctx.biometryType {
        case .none: return "biometria"
        case .touchID: return "Touch ID"
        case .faceID: return "Face ID"
        case .opticID: return "Optic ID"
        @unknown default: return "biometria"
        }
    }

    private static func normalizedEmail(_ email: String) -> String {
        email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// True se l’email corrente coincide con le credenziali salvate per l’accesso biometrico.
    static func isConfigured(forEmail email: String) -> Bool {
        guard biometricsAvailable() else { return false }
        let norm = normalizedEmail(email)
        guard !norm.isEmpty else { return false }
        let stored = (UserDefaults.standard.string(forKey: emailDefaultsKey) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return !stored.isEmpty && stored == norm
    }

    /// Salva la password nel Keychain; lettura solo dopo autenticazione biometrica.
    static func savePasswordForBiometricUnlock(email: String, password: String) throws {
        let account = normalizedEmail(email)
        guard !account.isEmpty else { return }
        deletePassword(forEmail: email)

        guard let pwData = password.data(using: .utf8) else { return }

        var accessError: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(
            nil,
            kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly,
            .biometryCurrentSet,
            &accessError
        ) else {
            if let unmanaged = accessError {
                throw unmanaged.takeRetainedValue() as Swift.Error
            }
            throw NSError(
                domain: "ContiLightBiometricLogin",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Impossibile creare l’accesso Keychain biometrico."]
            )
        }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: pwData,
            kSecAttrAccessControl as String: access,
        ]

        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw NSError(
                domain: NSOSStatusErrorDomain,
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey: "Keychain: impossibile salvare (codice \(status))."]
            )
        }
        UserDefaults.standard.set(account, forKey: emailDefaultsKey)
    }

    static func deletePassword(forEmail email: String) {
        let account = normalizedEmail(email)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
        if (UserDefaults.standard.string(forKey: emailDefaultsKey) ?? "").lowercased() == account {
            UserDefaults.standard.removeObject(forKey: emailDefaultsKey)
        }
    }

    static func deleteAllBiometricCredentials() {
        if let em = UserDefaults.standard.string(forKey: emailDefaultsKey) {
            deletePassword(forEmail: em)
        }
        UserDefaults.standard.removeObject(forKey: emailDefaultsKey)
    }

    /// Legge la password dal Keychain (mostra il prompt Face ID / Touch ID).
    static func loadPasswordUnlockingWithBiometrics(email: String) throws -> String {
        guard biometricsAvailable() else {
            throw NSError(
                domain: "ContiLightBiometricLogin",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Biometria non disponibile su questo dispositivo."]
            )
        }
        let account = normalizedEmail(email)
        guard isConfigured(forEmail: email) else {
            throw NSError(
                domain: "ContiLightBiometricLogin",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: "Accesso biometrico non configurato per questa email."]
            )
        }

        let ctx = LAContext()
        _ = ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        let hardware = biometricHardwareShortName(ctx)
        ctx.localizedReason = "Accedi a Conti di casa con \(hardware)."

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecUseAuthenticationContext as String: ctx,
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        guard status == errSecSuccess,
              let data = result as? Data,
              let pw = String(data: data, encoding: .utf8) else {
            if status == errSecItemNotFound || status == errSecAuthFailed {
                UserDefaults.standard.removeObject(forKey: emailDefaultsKey)
            }
            throw NSError(
                domain: NSOSStatusErrorDomain,
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey: "Accesso biometrico non riuscito (codice \(status)). Riprova con email e password."]
            )
        }
        return pw
    }

    static func biometricSystemImageName() -> String {
        let ctx = LAContext()
        var err: NSError?
        guard ctx.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err) else {
            return "lock.fill"
        }
        switch ctx.biometryType {
        case .faceID: return "faceid"
        case .touchID: return "touchid"
        case .opticID: return "faceid"
        default: return "lock.fill"
        }
    }

    private static func biometricHardwareShortName(_ ctx: LAContext) -> String {
        switch ctx.biometryType {
        case .none: return "biometria"
        case .touchID: return "Touch ID"
        case .faceID: return "Face ID"
        case .opticID: return "Optic ID"
        @unknown default: return "biometria"
        }
    }
}
