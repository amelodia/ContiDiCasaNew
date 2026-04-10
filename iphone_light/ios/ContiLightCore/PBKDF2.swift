import Foundation
import CommonCrypto

enum PBKDF2 {
    private static func isCCSuccessZero<T: BinaryInteger>(_ code: T) -> Bool {
        code == 0
    }

    /// Allineato a `security_auth._hash_password`: PBKDF2-HMAC-SHA256, 120_000 iterazioni.
    static func hashPasswordSHA256(password: String, saltHex: String) -> String? {
        guard let salt = Data.fromHex(saltHex) else { return nil }
        guard let derived = derive(password: password, salt: salt, iterations: 120_000, keyLength: 32) else {
            return nil
        }
        return derived.hexLowercased
    }

    private static func derive(password: String, salt: Data, iterations: Int, keyLength: Int) -> Data? {
        guard keyLength > 0 else { return nil }
        let passwordData = Data(password.utf8)
        var derived = Data(count: keyLength)
        var success = false
        derived.withUnsafeMutableBytes { derivedPtr in
            guard let outBase = derivedPtr.baseAddress else { return }
            passwordData.withUnsafeBytes { passPtr in
                guard let passBase = passPtr.baseAddress else { return }
                salt.withUnsafeBytes { saltPtr in
                    guard let saltBase = saltPtr.baseAddress else { return }
                    let code = CCKeyDerivationPBKDF(
                        CCPBKDFAlgorithm(kCCPBKDF2),
                        passBase.assumingMemoryBound(to: Int8.self),
                        passwordData.count,
                        saltBase.assumingMemoryBound(to: UInt8.self),
                        salt.count,
                        CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                        UInt32(iterations),
                        outBase.assumingMemoryBound(to: UInt8.self),
                        keyLength
                    )
                    // kCCSuccess == 0; il tipo C restituito varia tra SDK (Int32 / Int): confronto con 0 evita cast fragili.
                    success = Self.isCCSuccessZero(code)
                }
            }
        }
        guard success else { return nil }
        return derived
    }
}
