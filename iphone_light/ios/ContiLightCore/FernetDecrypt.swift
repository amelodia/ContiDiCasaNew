import Foundation
import CryptoKit
import CommonCrypto

enum FernetError: Error {
    case invalidKey
    case invalidToken
    case badVersion
    case hmacMismatch
    case decryptFailed
}

/// Decrittazione token Fernet compatibile con `cryptography.fernet` (Python).
struct FernetDecryptor {
    private let signingKey: Data
    private let encryptionKey: Data

    /// `keyFileContents`: contenuto del file `.key` (stringa Base64 URL-safe a 32 byte decodificati).
    init?(keyFileContents: String) {
        let trimmed = keyFileContents.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let master = Data(base64URLEncoded: trimmed) else { return nil }
        guard master.count == 32 else { return nil }
        signingKey = master.prefix(16)
        encryptionKey = master.suffix(16)
    }

    /// Contenuto file `.enc`: tipicamente ASCII Base64 del token (come `read_bytes()` in Python).
    func decrypt(encFileContents: Data) throws -> Data {
        guard let tokenString = String(data: encFileContents, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            let decoded = Data(base64URLEncoded: tokenString)
        else {
            throw FernetError.invalidToken
        }
        guard decoded.count >= 1 + 8 + 16 + 32 else { throw FernetError.invalidToken }

        // `Data` slice + `for i in indices` in `constantTimeEquals` ha dato loop enormi su alcuni SDK
        // (indici legati al buffer padre). Copia esattamente 32 byte e confronta con range fisso.
        let hmacReceived = Data(decoded.suffix(32))
        let signedPart = decoded.dropLast(32)

        let hmac = HMAC<SHA256>.authenticationCode(for: signedPart, using: SymmetricKey(data: signingKey))
        let hmacComputed = Data(hmac)
        guard Self.equalSHA256HMAC(hmacReceived, hmacComputed) else { throw FernetError.hmacMismatch }

        guard signedPart.first == 0x80 else { throw FernetError.badVersion }

        let afterVersion = signedPart.dropFirst(1)
        let iv = afterVersion.dropFirst(8).prefix(16)
        let ciphertext = afterVersion.dropFirst(8 + 16)

        return try Self.aes128CBCDecrypt(ciphertext: Data(ciphertext), key: Data(encryptionKey), iv: Data(iv))
    }

    /// Confronto HMAC SHA-256 (32 byte) senza iterare `indices` su slice del `Data` padre.
    private static func equalSHA256HMAC(_ a: Data, _ b: Data) -> Bool {
        guard a.count == 32, b.count == 32 else { return false }
        var diff: UInt8 = 0
        var i = 0
        while i < 32 {
            diff |= a[i] ^ b[i]
            i += 1
        }
        return diff == 0
    }

    private static func aes128CBCDecrypt(ciphertext: Data, key: Data, iv: Data) throws -> Data {
        guard key.count == kCCKeySizeAES128, iv.count == kCCBlockSizeAES128 else {
            throw FernetError.decryptFailed
        }
        var outLength = 0
        var outData = Data(count: ciphertext.count + kCCBlockSizeAES128)
        let status = outData.withUnsafeMutableBytes { outBuf in
            ciphertext.withUnsafeBytes { inBuf in
                key.withUnsafeBytes { keyBuf in
                    iv.withUnsafeBytes { ivBuf in
                        CCCrypt(
                            CCOperation(kCCDecrypt),
                            CCAlgorithm(kCCAlgorithmAES128),
                            CCOptions(kCCOptionPKCS7Padding),
                            keyBuf.baseAddress, kCCKeySizeAES128,
                            ivBuf.baseAddress,
                            inBuf.baseAddress, ciphertext.count,
                            outBuf.baseAddress, outBuf.count,
                            &outLength
                        )
                    }
                }
            }
        }
        guard status == kCCSuccess else { throw FernetError.decryptFailed }
        return outData.prefix(outLength)
    }
}
