import Foundation

extension Data {
    /// Decodifica Base64 URL-safe come in Fernet (Python cryptography).
    init?(base64URLEncoded string: String) {
        var s = string.trimmingCharacters(in: .whitespacesAndNewlines)
        s = s.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        let pad = (4 - s.count % 4) % 4
        if pad > 0 { s += String(repeating: "=", count: pad) }
        self.init(base64Encoded: s)
    }
}

extension Data {
    var hexLowercased: String {
        map { String(format: "%02x", $0) }.joined()
    }

    static func fromHex(_ hex: String) -> Data? {
        let t = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.count % 2 == 0 else { return nil }
        var data = Data(capacity: t.count / 2)
        var i = t.startIndex
        while i < t.endIndex {
            let j = t.index(i, offsetBy: 2)
            guard let b = UInt8(t[i..<j], radix: 16) else { return nil }
            data.append(b)
            i = j
        }
        return data
    }

    /// Confronto a tempo costante (come secrets.compare_digest).
    func constantTimeEquals(_ other: Data) -> Bool {
        guard count == other.count else { return false }
        var diff: UInt8 = 0
        for i in indices {
            diff |= self[i] ^ other[i]
        }
        return diff == 0
    }
}
