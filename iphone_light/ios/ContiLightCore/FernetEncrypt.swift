import Foundation
import CryptoKit
import CommonCrypto

/// Crittografia token Fernet compatibile con `cryptography.fernet` (Python).
struct FernetEncryptor {
    private let signingKey: Data
    private let encryptionKey: Data

    init?(keyFileContents: String) {
        let trimmed = keyFileContents.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let master = Data(base64URLEncoded: trimmed) else { return nil }
        guard master.count == 32 else { return nil }
        signingKey = master.prefix(16)
        encryptionKey = master.suffix(16)
    }

    /// Produce testo come file `.enc` sul desktop: UTF-8 della stringa Base64 URL-safe del token.
    func encryptToUTF8String(plaintext: Data) throws -> String {
        var iv = Data(count: kCCBlockSizeAES128)
        let rnd = iv.withUnsafeMutableBytes { buf in
            SecRandomCopyBytes(kSecRandomDefault, kCCBlockSizeAES128, buf.baseAddress!)
        }
        guard rnd == errSecSuccess else { throw ContiDBError.cannotEncrypt }

        let ciphertext = try Self.aes128CBCEncryptPKCS7(
            plaintext: plaintext,
            key: Data(encryptionKey),
            iv: iv
        )

        let t = Int64(Date().timeIntervalSince1970)
        var be = t.bigEndian
        let tsData = Data(bytes: &be, count: 8)

        var signingInput = Data([0x80])
        signingInput.append(tsData)
        signingInput.append(iv)
        signingInput.append(ciphertext)

        let mac = HMAC<SHA256>.authenticationCode(for: signingInput, using: SymmetricKey(data: signingKey))
        let tokenBinary = signingInput + Data(mac)

        return tokenBinary.base64URLEncodedFernetString()
    }

    private static func aes128CBCEncryptPKCS7(plaintext: Data, key: Data, iv: Data) throws -> Data {
        guard key.count == kCCKeySizeAES128, iv.count == kCCBlockSizeAES128 else {
            throw ContiDBError.cannotEncrypt
        }
        var outLength = 0
        var outData = Data(count: plaintext.count + kCCBlockSizeAES128 * 2)
        let status = outData.withUnsafeMutableBytes { outBuf in
            plaintext.withUnsafeBytes { inBuf in
                key.withUnsafeBytes { keyBuf in
                    iv.withUnsafeBytes { ivBuf in
                        CCCrypt(
                            CCOperation(kCCEncrypt),
                            CCAlgorithm(kCCAlgorithmAES128),
                            CCOptions(kCCOptionPKCS7Padding),
                            keyBuf.baseAddress, kCCKeySizeAES128,
                            ivBuf.baseAddress,
                            inBuf.baseAddress, plaintext.count,
                            outBuf.baseAddress, outBuf.count,
                            &outLength
                        )
                    }
                }
            }
        }
        guard status == kCCSuccess else { throw ContiDBError.cannotEncrypt }
        return outData.prefix(outLength)
    }
}

private extension Data {
    func base64URLEncodedFernetString() -> String {
        let s = base64EncodedString()
        return s
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
    }
}
