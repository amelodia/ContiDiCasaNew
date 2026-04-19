import Foundation
import CryptoKit

public struct ContiSession {
    public let isRegistered: Bool
    public let userEmail: String
}

/// Una riga lista per la UI (movimenti da `years[].records[]`).
public struct ContiRecordRow: Identifiable, Hashable, Sendable {
    public let id: String
    public let year: Int
    public let dateIso: String
    /// Data mostrata (es. `dd/MM/yyyy` da ISO).
    public let dateDisplay: String
    /// Nome categoria senza segno iniziale (+/−).
    public let categoryDisplay: String
    public let accountPrimary: String
    public let accountSecondary: String
    /// Valore numerico per colore/format; `nil` se il testo non è interpretabile.
    public let amountValue: Decimal?
    public let amountRawFallback: String
    public let note: String
    public let isCancelled: Bool
    public let sourceIndex: Int
}

/// Saldi per conto: stesse colonne del footer «Saldi» desktop (carte di credito: spese CC sulla colonna di riferimento).
public struct ContiSaldRiga: Identifiable, Hashable, Sendable {
    public let id: String
    public let accountName: String
    public let saldoAssoluto: Decimal
    public let saldoOggi: Decimal
    /// True se il conto è marcato come carta nel piano (ultimo anno).
    public let isCreditCard: Bool
    /// Registrazioni con data successiva al cutoff (stesso significato del desktop).
    public let speseFuture: Decimal
    public let speseCC: Decimal
    /// Per conti non-carta: saldo assoluto + spese future + spese CC; per carta: zero in tabella desktop.
    public let disponibilita: Decimal
}

/// Voce piano categorie per la scheda immissione (ultimo anno), come «Nuove registrazioni» sul desktop.
public struct ContiImmissioneCategoria: Hashable, Sendable {
    public let code: String
    public let displayName: String
    public let planNote: String
}

/// Voce piano conti per la scheda immissione (codice 1…n come sul desktop).
public struct ContiImmissioneConto: Hashable, Sendable {
    public let code: String
    public let name: String
    public let isCreditCard: Bool
    /// Nome conto di riferimento (solo lettura, come sul desktop); vuoto se non carta o senza riferimento.
    public let referenceAccountName: String
}

public enum ContiDBError: Error {
    case cannotReadKey
    case cannotReadEnc
    case cannotDecrypt
    case cannotEncrypt
    case invalidJSON
}

extension ContiDBError: LocalizedError {
    public var errorDescription: String? {
        switch self {
        case .cannotReadKey:
            return "File .key illeggibile o chiave Fernet non valida."
        case .cannotReadEnc:
            return "File .enc illeggibile dal percorso scelto."
        case .cannotDecrypt:
            return "Decrittazione fallita: .enc e .key non corrispondono o file corrotto."
        case .cannotEncrypt:
            return "Crittazione fallita (chiave o dati non validi)."
        case .invalidJSON:
            return "Contenuto decrittato non è JSON valido."
        }
    }
}

/// Caricamento DB e login allineati a `iphone_light/light_auth.py` + `crypto_db.py`.
public enum ContiDatabase {

    /// Oltre questa soglia (JSON in chiaro) il login usa solo `user_profile` (file .enc molto grande).
    /// Il file **sidecar** ``*_light.enc`` del desktop è piccolo: resta sotto soglia e si fa parse completo (Movimenti).
    private static let fullJSONParseThresholdBytes = 25 * 1024 * 1024

    /*
     Stima memoria (ordine di grandezza) se in futuro l’app iOS caricasse/aggiornasse anche il `.enc` **completo**
     (es. ~25.000 registrazioni desktop) oltre al light (~1.200 righe):

     - JSON decrittato su disco: spesso ~15–40 MB per 20–25k movimenti (dipende da note e campi).
     - `JSONSerialization` → `[String: Any]` annidati: tipicamente **2–4×** il peso del JSON grezzo in picco (oggetti Swift/NSDictionary).
     - Durante un salvataggio: in copia potrebbero coesistere **vecchio dizionario + stringa JSON serializzata + token Fernet**: picco spesso **~60–120 MB** aggiuntivi oltre al footprint dell’app, per pochi secondi.
     - Il solo file **light** resta nell’ordine **1–5 MB** in RAM dopo parse: trascurabile rispetto al completo.

     Conclusione: aggiornare il `.enc` pieno da iOS è **fattibile** su iPhone recenti (4+ GB RAM), ma conviene evitare duplicati in memoria (serializzare/streammare) e testare su dispositivi con 2 GB. Non è implementato qui: manca ancora Fernet **encrypt** lato Swift e la politica di merge con Dropbox.
     */

    /// Solo le chiavi necessarie al login (il decoder ignora `years` e il resto senza caricarli in `[String: Any]` annidati).
    private struct LoginOnlyJSON: Decodable {
        struct UserProfileDTO: Decodable {
            let display_name_suffix: String?
            let email: String?
            let password_hash: String?
            let salt: String?
            let registration_verified: FlexibleBool?
            /// Soglia UTC (ISO) per accettare REGISTRA:/REGISTRATO: su IMAP (desktop); opzionale.
            let registration_poll_not_before_iso: String?
        }

        struct SecurityConfigDTO: Decodable {
            let admin_notify_email: String?
            let email_verified_ok: FlexibleBool?
        }

        let user_profile: UserProfileDTO?
        let security_config: SecurityConfigDTO?
    }

    /// Decodifica bool da JSON anche se in passato fosse salvato come 0/1.
    private struct FlexibleBool: Decodable {
        let value: Bool
        init(from decoder: Decoder) throws {
            let c = try decoder.singleValueContainer()
            if let b = try? c.decode(Bool.self) {
                value = b
            } else if let i = try? c.decode(Int.self) {
                value = i != 0
            } else {
                throw DecodingError.dataCorruptedError(in: c, debugDescription: "Expected Bool or Int")
            }
        }
    }

    /// Decrittazione a partire da dati già letti (modalità login: parser completo sotto soglia, ridotto oltre soglia).
    public static func loadEncryptedDB(encData: Data, keyString: String) throws -> [String: Any] {
        try decryptPayload(encData: encData, keyString: keyString, loginOnly: true)
    }

    /// Decrittazione forzando il parse JSON completo (usare per merge/salvataggio del DB completo).
    public static func loadEncryptedDBFull(encData: Data, keyString: String) throws -> [String: Any] {
        try decryptPayload(encData: encData, keyString: keyString, loginOnly: false)
    }

    private static func decryptPayload(encData: Data, keyString: String, loginOnly: Bool) throws -> [String: Any] {
        guard let fernet = FernetDecryptor(keyFileContents: keyString) else {
            throw ContiDBError.cannotReadKey
        }
        let plain: Data
        do {
            plain = try fernet.decrypt(encFileContents: encData)
        } catch {
            throw ContiDBError.cannotDecrypt
        }
        return loginOnly ? (try parseJSONForLogin(plain: plain)) : (try parseJSONFull(plain: plain))
    }

    private static func parseJSONForLogin(plain: Data) throws -> [String: Any] {
        if plain.count <= fullJSONParseThresholdBytes {
            return try autoreleasepool {
                guard let obj = try JSONSerialization.jsonObject(with: plain, options: []) as? [String: Any] else {
                    throw ContiDBError.invalidJSON
                }
                return obj
            }
        }
        let dec = JSONDecoder()
        let login = try dec.decode(LoginOnlyJSON.self, from: plain)
        return dictionaryForLogin(from: login)
    }

    private static func parseJSONFull(plain: Data) throws -> [String: Any] {
        try autoreleasepool {
            guard let obj = try JSONSerialization.jsonObject(with: plain, options: []) as? [String: Any] else {
                throw ContiDBError.invalidJSON
            }
            return obj
        }
    }

    private static func dictionaryForLogin(from decoded: LoginOnlyJSON) -> [String: Any] {
        var db: [String: Any] = [:]
        if let up = decoded.user_profile {
            var upDict: [String: Any] = [:]
            upDict["display_name_suffix"] = up.display_name_suffix ?? ""
            upDict["email"] = up.email ?? ""
            upDict["password_hash"] = up.password_hash ?? ""
            upDict["salt"] = up.salt ?? ""
            upDict["registration_verified"] = up.registration_verified?.value ?? false
            if let iso = up.registration_poll_not_before_iso {
                upDict["registration_poll_not_before_iso"] = iso
            }
            db["user_profile"] = upDict
        }
        if let sc = decoded.security_config {
            db["security_config"] = [
                "admin_notify_email": sc.admin_notify_email ?? "",
                "email_verified_ok": sc.email_verified_ok?.value ?? false,
            ]
        }
        return db
    }

    /// Cartella del file ``.enc`` principale (stessa cartella di ``.key`` e ``*_light.enc``).
    public static func perUserEncBaseDirectory(primaryEnc: URL) -> URL {
        primaryEnc.deletingLastPathComponent()
    }

    public static func perUserEncURL(primaryEnc: URL, email: String) -> URL {
        let em = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let digest = SHA256.hash(data: Data(em.utf8))
        let hex = digest.map { String(format: "%02x", $0) }.joined().prefix(20)
        return perUserEncBaseDirectory(primaryEnc: primaryEnc)
            .appendingPathComponent("conti_utente_\(hex).enc", isDirectory: false)
    }

    /// Stem `conti_utente_<20 hex>` (stesso criterio di `perUserEncURL`, senza `.enc`).
    public static func userEncFilenameStem(forEmail email: String) -> String {
        let em = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let digest = SHA256.hash(data: Data(em.utf8))
        let hex = digest.map { String(format: "%02x", $0) }.joined().prefix(20)
        return "conti_utente_\(hex)"
    }

    /// Solo sidecar **light** (mai il `.enc` pieno), nella stessa cartella del `.key`.
    public static func userDatabaseEncURLCandidates(inFolder folder: URL, email: String) -> [URL] {
        let stem = userEncFilenameStem(forEmail: email)
        let dir = folder.standardizedFileURL
        return [dir.appendingPathComponent("\(stem)_light.enc", isDirectory: false)]
    }

    public static func firstExistingURL(in candidates: [URL]) -> URL? {
        for u in candidates {
            if FileManager.default.fileExists(atPath: u.path) { return u }
        }
        return nil
    }

    /// File `*_light.enc` per l’email; mai database completi.
    public static func resolvePrimaryEncURL(inFolder folder: URL, email: String) -> URL? {
        firstExistingURL(in: userDatabaseEncURLCandidates(inFolder: folder, email: email))
    }

    /// Un file `.key` nella cartella (preferenza `conti_di_casa.key`).
    public static func preferredKeyFileURL(inFolder folder: URL) -> URL? {
        let fm = FileManager.default
        guard let urls = try? fm.contentsOfDirectory(
            at: folder.standardizedFileURL,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) else { return nil }
        let keys = urls.filter { $0.pathExtension.lowercased() == "key" }
        if let exact = keys.first(where: { $0.lastPathComponent == "conti_di_casa.key" }) {
            return exact
        }
        return keys.sorted {
            $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending
        }.first
    }

    /// Euristica Dropbox (analoga a `cloud_sync_wait.path_looks_under_dropbox` del desktop).
    public static func pathLooksUnderDropbox(_ url: URL) -> Bool {
        let p = url.standardizedFileURL.path.lowercased()
        if p.contains("/cloudstorage/dropbox") { return true }
        if p.contains("/dropbox/") { return true }
        if p.contains("/dropbox-") { return true }
        if p.contains("/dropbox (") { return true }
        return false
    }

    private static func fileFingerprint(_ url: URL) -> (size: NSNumber, mtime: Date)? {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let size = attrs[.size] as? NSNumber,
              let mtime = attrs[.modificationDate] as? Date else { return nil }
        return (size, mtime)
    }

    /// Attende che `(size, mtime)` del file resti invariato per `stableSeconds`.
    /// Torna i secondi di attesa effettivi (0 se non Dropbox o file già stabile).
    @discardableResult
    public static func waitForFileStableIfDropbox(
        _ url: URL,
        stableSeconds: TimeInterval = 1.6,
        pollSeconds: TimeInterval = 0.25,
        maxWaitSeconds: TimeInterval = 180
    ) -> TimeInterval {
        guard pathLooksUnderDropbox(url) else { return 0 }
        let t0 = Date().timeIntervalSinceReferenceDate
        let deadline = t0 + maxWaitSeconds

        while Date().timeIntervalSinceReferenceDate < deadline {
            if FileManager.default.fileExists(atPath: url.path) { break }
            Thread.sleep(forTimeInterval: pollSeconds)
        }
        guard var fp0 = fileFingerprint(url) else {
            return Date().timeIntervalSinceReferenceDate - t0
        }
        var stableSince = Date().timeIntervalSinceReferenceDate
        while Date().timeIntervalSinceReferenceDate < deadline {
            Thread.sleep(forTimeInterval: pollSeconds)
            guard let fp1 = fileFingerprint(url) else {
                stableSince = Date().timeIntervalSinceReferenceDate
                continue
            }
            if fp1.size != fp0.size || fp1.mtime != fp0.mtime {
                fp0 = fp1
                stableSince = Date().timeIntervalSinceReferenceDate
                continue
            }
            if Date().timeIntervalSinceReferenceDate - stableSince >= stableSeconds {
                break
            }
        }
        return Date().timeIntervalSinceReferenceDate - t0
    }

    /// Attesa stabilità su più file Dropbox (es. `.key` e `.enc`), con dedup path.
    @discardableResult
    public static func waitForPathsStableIfDropbox(_ urls: [URL]) -> TimeInterval {
        var seen = Set<String>()
        var total: TimeInterval = 0
        for u in urls {
            let key = u.standardizedFileURL.path
            if seen.contains(key) { continue }
            seen.insert(key)
            total += waitForFileStableIfDropbox(u)
        }
        return total
    }

    /// Legge `.key` come UTF-8 (stringa Base64), `.enc` come dati del token Fernet.
    public static func loadEncryptedDB(encURL: URL, keyURL: URL) throws -> [String: Any] {
        let keyString: String
        do {
            keyString = try String(contentsOf: keyURL, encoding: .utf8)
        } catch {
            throw ContiDBError.cannotReadKey
        }
        let encData: Data
        do {
            encData = try Data(contentsOf: encURL)
        } catch {
            throw ContiDBError.cannotReadEnc
        }
        return try decryptPayload(encData: encData, keyString: keyString, loginOnly: true)
    }

    /// Come `loadEncryptedDB`, ma forzando parse completo.
    public static func loadEncryptedDBFull(encURL: URL, keyURL: URL) throws -> [String: Any] {
        let keyString: String
        do {
            keyString = try String(contentsOf: keyURL, encoding: .utf8)
        } catch {
            throw ContiDBError.cannotReadKey
        }
        let encData: Data
        do {
            encData = try Data(contentsOf: encURL)
        } catch {
            throw ContiDBError.cannotReadEnc
        }
        return try decryptPayload(encData: encData, keyString: keyString, loginOnly: false)
    }

    /// Decrittazione del solo file già scelto (sidecar light). Non carica mai il `.enc` pieno per-utente.
    public static func loadDBForEmail(
        primaryEncData: Data,
        keyString: String,
        primaryEncURL: URL
    ) throws -> ([String: Any], URL) {
        let db = try decryptPayload(encData: primaryEncData, keyString: keyString, loginOnly: true)
        return (db, primaryEncURL)
    }

    /// Come sopra, partendo da percorsi su disco.
    public static func loadDBForEmail(primaryEncURL: URL, keyURL: URL) throws -> ([String: Any], URL) {
        let db = try loadEncryptedDB(encURL: primaryEncURL, keyURL: keyURL)
        return (db, primaryEncURL)
    }

    /// Come `try_login` in `light_auth.py`.
    public static func tryLogin(db: [String: Any], email: String, password: String) -> ContiSession? {
        var work = db
        ensureSecurity(&work)
        guard let up = work["user_profile"] as? [String: Any] else { return nil }
        let em = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !em.isEmpty else { return nil }
        let hash = (up["password_hash"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !hash.isEmpty else { return nil }
        let profileEmail = ((up["email"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard em == profileEmail else { return nil }
        let pwd = password.trimmingCharacters(in: .whitespacesAndNewlines)
        guard verifyPassword(userProfile: up, plain: pwd) else { return nil }
        let verified = jsonBool(up["registration_verified"])
        return ContiSession(isRegistered: verified, userEmail: em)
    }

    /// Dopo `JSONSerialization` i booleani possono arrivare come `NSNumber`.
    private static func jsonBool(_ v: Any?) -> Bool {
        if let b = v as? Bool { return b }
        if let n = v as? NSNumber { return n.boolValue }
        return false
    }

    private static func verifyPassword(userProfile: [String: Any], plain: String) -> Bool {
        let h = (userProfile["password_hash"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let s = (userProfile["salt"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !h.isEmpty, !s.isEmpty else { return false }
        guard let computed = PBKDF2.hashPasswordSHA256(password: plain, saltHex: s) else { return false }
        return computed.constantTimeEqualsString(h.lowercased())
    }

    /// Copia minima di `ensure_security` (solo merge chiavi mancanti su una copia mutabile).
    private static func ensureSecurity(_ db: inout [String: Any]) {
        var up = (db["user_profile"] as? [String: Any]) ?? [:]
        for (k, v) in defaultUserProfileDefaults() where up[k] == nil {
            up[k] = v
        }
        db["user_profile"] = up
        var sc = (db["security_config"] as? [String: Any]) ?? [:]
        for (k, v) in defaultSecurityConfigDefaults() where sc[k] == nil {
            sc[k] = v
        }
        db["security_config"] = sc
    }

    private static func defaultUserProfileDefaults() -> [String: Any] {
        [
            "display_name_suffix": "",
            "email": "",
            "password_hash": "",
            "salt": "",
            "registration_verified": false,
            "registration_poll_not_before_iso": "",
        ]
    }

    private static func defaultSecurityConfigDefaults() -> [String: Any] {
        ["admin_notify_email": "", "email_verified_ok": false]
    }

    public static func countRecords(in db: [String: Any]) -> Int {
        guard let years = db["years"] as? [[String: Any]] else { return 0 }
        return years.reduce(0) { acc, y in
            acc + ((y["records"] as? [Any])?.count ?? 0)
        }
    }

    /// Appiattisce `years` → righe ordinate dalla **data più recente** alla più vecchia.
    public static func displayRecords(from db: [String: Any]) -> [ContiRecordRow] {
        guard let years = db["years"] as? [[String: Any]] else { return [] }
        var rows: [ContiRecordRow] = []
        for yd in years {
            let year = intFromJSON(yd["year"])
            guard let recs = yd["records"] as? [[String: Any]] else { continue }
            for r in recs {
                if isDotazioneRecord(r) { continue }
                let si = intFromJSON(r["source_index"])
                let key = (r["legacy_registration_key"] as? String) ?? ""
                let id = key.isEmpty ? "\(year)-\(si)-\(rows.count)" : "\(year)-\(key)"
                let dateIso = String(stringFromJSON(r["date_iso"]).prefix(10))
                let rawAmount = stringFromJSON(r["display_amount"]).isEmpty ? stringFromJSON(r["amount_eur"]) : stringFromJSON(r["display_amount"])
                let catRaw = stripLeadingSignAndSpace(stringFromJSON(r["category_name"]))
                let catShow = Self.isHiddenDotazioneCategoryName(catRaw) ? "" : catRaw
                rows.append(
                    ContiRecordRow(
                        id: id,
                        year: year,
                        dateIso: dateIso,
                        dateDisplay: italianDateDisplay(fromIsoDate: dateIso),
                        categoryDisplay: catShow,
                        accountPrimary: stringFromJSON(r["account_primary_name"]),
                        accountSecondary: stringFromJSON(r["account_secondary_name"]),
                        amountValue: parseLooseDecimal(rawAmount),
                        amountRawFallback: rawAmount,
                        note: stringFromJSON(r["note"]),
                        isCancelled: boolFromJSON(r["is_cancelled"]),
                        sourceIndex: si
                    )
                )
            }
        }
        rows.sort {
            if $0.dateIso != $1.dateIso { return $0.dateIso > $1.dateIso }
            if $0.sourceIndex != $1.sourceIndex { return $0.sourceIndex > $1.sourceIndex }
            return $0.id > $1.id
        }
        return rows
    }

    /// Data locale `yyyy-MM-dd` (stessa logica del cutoff «saldi oggi» sul desktop).
    public static func todayIsoLocal() -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = .current
        let c = cal.dateComponents([.year, .month, .day], from: Date())
        guard let y = c.year, let m = c.month, let d = c.day else { return "" }
        return String(format: "%04d-%02d-%02d", y, m, d)
    }

    /// Testo intestazione: suffisso nome utente se presente, altrimenti email.
    public static func displayNameForHeader(db: [String: Any], email: String) -> String {
        let up = db["user_profile"] as? [String: Any]
        let suffix = (up?["display_name_suffix"] as? String)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !suffix.isEmpty { return suffix }
        return email.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func dictionaryFromAnyRoot(_ root: Any?) -> [String: Any]? {
        guard let root else { return nil }
        if let d = root as? [String: Any] { return d }
        guard let ns = root as? NSDictionary else { return nil }
        if let swift = ns as? [String: Any] { return swift }
        var out: [String: Any] = [:]
        for key in ns.allKeys {
            guard let ks = key as? String else { continue }
            if let v = ns.object(forKey: key) {
                out[ks] = v
            }
        }
        return out
    }

    /// Dopo `JSONSerialization` o `NSDictionary` annidati, `as? [[String:Any]]` può fallire: normalizza qui.
    private static func coerceToArrayOfStringKeyedDicts(_ value: Any?) -> [[String: Any]] {
        guard let value, !(value is NSNull) else { return [] }
        if let arr = value as? [[String: Any]] { return arr }
        if let arr = value as? [Any] {
            return arr.compactMap { el -> [String: Any]? in
                if let d = el as? [String: Any] { return d }
                if let d = el as? NSDictionary { return d as? [String: Any] }
                return nil
            }
        }
        if let ns = value as? NSArray {
            return (0 ..< ns.count).compactMap { i -> [String: Any]? in
                let el = ns[i]
                if let d = el as? [String: Any] { return d }
                if let d = el as? NSDictionary { return d as? [String: Any] }
                return nil
            }
        }
        return []
    }

    /// Saldi da qualsiasi radice JSON (`[String:Any]`, `NSDictionary` dopo login).
    public static func saldiDueForme(sessionDb: Any?, todayIso: String) -> [ContiSaldRiga] {
        guard let db = dictionaryFromAnyRoot(sessionDb) else { return [] }
        return saldiDueForme(db: db, todayIso: todayIso)
    }

    /// Metadati del blocco ``light_saldi`` (se presente), scritto dal desktop sul DB completo.
    public static func lightSaldiSnapshotMeta(sessionDb: Any?) -> (dateIso: String, yearBasis: Int)? {
        guard let db = dictionaryFromAnyRoot(sessionDb) else { return nil }
        guard let block = dictionaryFromAnyRoot(db["light_saldi"]) else { return nil }
        let rows = coerceToArrayOfStringKeyedDicts(block["rows"])
        guard !rows.isEmpty else { return nil }
        let d = stringFromJSON(block["snapshot_date_iso"])
        if d.isEmpty { return nil }
        return (d, intFromJSON(block["year_basis"]))
    }

    /// Totali riga «non carta» dal blocco ``light_saldi`` (opzionale, file generato da desktop/iOS recente).
    public static func lightSaldiTotalsNonCc(sessionDb: Any?) -> (abs: Decimal, sf: Decimal, scc: Decimal, disp: Decimal)? {
        guard let db = dictionaryFromAnyRoot(sessionDb) else { return nil }
        guard let block = dictionaryFromAnyRoot(db["light_saldi"]),
              let t = dictionaryFromAnyRoot(block["totals"])
        else { return nil }
        guard let abs = parseLooseDecimal(stringFromJSON(t["saldo_assoluti_non_cc"])),
              let sf = parseLooseDecimal(stringFromJSON(t["spese_future_non_cc"])),
              let scc = parseLooseDecimal(stringFromJSON(t["spese_cc_non_cc"])),
              let disp = parseLooseDecimal(stringFromJSON(t["disponibilita_non_cc"]))
        else { return nil }
        return (abs, sf, scc, disp)
    }

    /// Aggiorna ``light_saldi`` in memoria dopo una nuova registrazione (stesse regole del desktop). Da chiamare al salvataggio iOS prima di ricifrare.
    public static func applyNewRecordToLightSaldi(db: inout [String: Any], record: [String: Any], cutoffDateIso: String) {
        guard var block = dictionaryFromAnyRoot(db["light_saldi"]) else { return }
        let rowDicts = coerceToArrayOfStringKeyedDicts(block["rows"])
        let n = rowDicts.count
        guard n > 0 else { return }

        func rowIndexMatchingAccountCode(_ code: String) -> Int? {
            let t = code.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty else { return nil }
            for i in 0 ..< n {
                let rc = stringFromJSON(rowDicts[i]["account_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
                if rc == t { return i }
                if let a = Int(rc), let b = Int(t), a == b { return i }
            }
            return nil
        }

        var absB = (0 ..< n).map { parseLooseDecimal(stringFromJSON(rowDicts[$0]["saldo_assoluto"])) ?? .zero }
        var dayB = (0 ..< n).map { parseLooseDecimal(stringFromJSON(rowDicts[$0]["saldo_alla_data"])) ?? .zero }

        if boolFromJSON(record["is_cancelled"]) { return }
        let y = intFromJSON(record["year"])
        if isDotazioneRecord(record), y != legacyDotazioneYear { return }

        let amount = parseLooseDecimal(stringFromJSON(record["amount_eur"])) ?? .zero
        let c1 = stringFromJSON(record["account_primary_code"])
        let c2 = stringFromJSON(record["account_secondary_code"])
        let i1 = rowIndexMatchingAccountCode(c1)
        let i2 = rowIndexMatchingAccountCode(c2)

        func applyAmount(_ arr: inout [Decimal]) {
            if let ix = i1, ix >= 0, ix < n { arr[ix] += amount }
            if isGirocontoRecord(record), let ix = i2, ix >= 0, ix < n { arr[ix] -= amount }
        }

        applyAmount(&absB)
        let rDate = stringFromJSON(record["date_iso"])
        if rDate.isEmpty || rDate <= cutoffDateIso {
            applyAmount(&dayB)
        }

        var newRows: [[String: Any]] = []
        for i in 0 ..< n {
            let code = stringFromJSON(rowDicts[i]["account_code"])
            let nm = stringFromJSON(rowDicts[i]["account_name"])
            var row: [String: Any] = [
                "account_code": code.isEmpty ? String(i + 1) : code,
                "account_name": nm,
                "saldo_assoluto": decimalStringForLightJson(absB[i]),
                "saldo_alla_data": decimalStringForLightJson(dayB[i]),
            ]
            if rowDicts[i]["credit_card"] != nil { row["credit_card"] = boolFromJSON(rowDicts[i]["credit_card"]) }
            if rowDicts[i]["spese_cc"] != nil { row["spese_cc"] = stringFromJSON(rowDicts[i]["spese_cc"]) }
            if rowDicts[i]["spese_future"] != nil { row["spese_future"] = stringFromJSON(rowDicts[i]["spese_future"]) }
            if rowDicts[i]["disponibilita"] != nil { row["disponibilita"] = stringFromJSON(rowDicts[i]["disponibilita"]) }
            newRows.append(row)
        }
        block["rows"] = newRows
        refreshLightSaldiRowDerivedFromAbsDay(&block)
        db["light_saldi"] = block
    }

    // MARK: - Sync dual .enc + saldi (allineato a light_enc_sidecar.py / main_app)

    public static let contiLightRecordIdKey = "conti_light_record_id"

    /// Finestra mobile: oggi − 365 giorni (come `light_window_start_iso`).
    public static func lightWindowStartIsoForExport() -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = .current
        guard let d = cal.date(byAdding: .day, value: -365, to: Date()) else { return "" }
        let c = cal.dateComponents([.year, .month, .day], from: d)
        guard let y = c.year, let m = c.month, let da = c.day else { return "" }
        return String(format: "%04d-%02d-%02d", y, m, da)
    }

    private static func recordInLightWindowExport(_ rec: [String: Any], windowStart: String) -> Bool {
        let d = String(stringFromJSON(rec["date_iso"]).prefix(10))
        guard d.count == 10 else { return false }
        return d >= String(windowStart.prefix(10))
    }

    private static func recordSortKeyNewestFirst(_ rec: [String: Any]) -> (String, Int) {
        let d = String(stringFromJSON(rec["date_iso"]).prefix(10))
        let si = intFromJSON(rec["source_index"])
        return (d, si)
    }

    private static func recordMergeSortKey(_ r: [String: Any]) -> (Int, Int, String, String, Int) {
        let y = intFromJSON(r["year"])
        let folder = stringFromJSON(r["source_folder"])
        let rank = folder == "APP" ? 1 : 0
        let file = stringFromJSON(r["source_file"])
        let idx = intFromJSON(r["source_index"])
        return (y, rank, folder, file, idx)
    }

    private static let legacyDotazioneYear = 1990
    private static let planReferenceYear = 2026

    /// Ricalcola ``light_saldi`` dal DB **completo** (stesso modello di ``saldi_footer_amount_vectors`` / ``compute_light_saldi_snapshot`` in ``main_app.py``).
    public static func recomputeLightSaldiFromFullDb(_ db: inout [String: Any]) {
        guard let snap = buildLightSaldiSnapshotDict(from: db) else { return }
        db["light_saldi"] = snap
    }

    private static func yearBucketForCalendar(db: [String: Any], year: Int) -> [String: Any]? {
        guard let years = db["years"] as? [[String: Any]] else { return nil }
        return years.first { intFromJSON($0["year"]) == year }
    }

    private static func mergedPlanAccounts(db: [String: Any]) -> [[String: Any]] {
        if let yb = yearBucketForCalendar(db: db, year: planReferenceYear) {
            return coerceToArrayOfStringKeyedDicts(yb["accounts"])
        }
        guard let years = db["years"] as? [[String: Any]], !years.isEmpty else { return [] }
        let latest = years.max { intFromJSON($0["year"]) < intFromJSON($1["year"]) }!
        return coerceToArrayOfStringKeyedDicts(latest["accounts"])
    }

    private static func saldiVisibleIndices(
        db: [String: Any],
        latestAccounts: [[String: Any]],
        namesFull: [String]
    ) -> [Int] {
        let frozenCodes = Set(
            mergedPlanAccounts(db: db).compactMap { a -> String? in
                guard boolFromJSON(a["frozen"]) else { return nil }
                let c = stringFromJSON(a["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
                return c.isEmpty ? nil : c
            }
        )
        var out: [Int] = []
        for i in 0 ..< min(namesFull.count, latestAccounts.count) {
            let code = stringFromJSON(latestAccounts[i]["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            if frozenCodes.contains(code) { continue }
            out.append(i)
        }
        return out
    }

    private static func importedRecordBalanceTwinKey(_ rec: [String: Any]) -> (String, String, String, String) {
        let d = String(stringFromJSON(rec["date_iso"]).prefix(10))
        let c1 = stringFromJSON(rec["account_primary_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
        let c2 = stringFromJSON(rec["account_secondary_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
        var amtS = stringFromJSON(rec["amount_eur"]).trimmingCharacters(in: .whitespacesAndNewlines)
        if amtS.isEmpty, let v = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) {
            amtS = NSDecimalNumber(decimal: v).stringValue
        }
        return (d, c1, c2, amtS)
    }

    private static func importCancelTwinBalanceKeys(db: [String: Any]) -> Set<String> {
        var imp: [[String: Any]] = []
        guard let years = db["years"] as? [[String: Any]] else { return [] }
        for yd in years {
            for rec in coerceToArrayOfStringKeyedDicts(yd["records"]) {
                if !stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    imp.append(rec)
                }
            }
        }
        var cKeys = Set<String>()
        var aKeys = Set<String>()
        for r in imp {
            let k = importedRecordBalanceTwinKey(r)
            let tag = "\(k.0)|\(k.1)|\(k.2)|\(k.3)"
            if boolFromJSON(r["is_cancelled"]) {
                cKeys.insert(tag)
            } else {
                aKeys.insert(tag)
            }
        }
        return cKeys.intersection(aKeys)
    }

    private static func twinKeyTag(_ k: (String, String, String, String)) -> String {
        "\(k.0)|\(k.1)|\(k.2)|\(k.3)"
    }

    /// Allineato a ``account_column_index_in_latest_chart`` in ``main_app.py``: colonna = codice nel piano, non posizione ``codice-1``.
    private static func accountColumnIndexInLatestChart(_ chartAccounts: [[String: Any]], _ codeRaw: String) -> Int {
        let r = codeRaw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !r.isEmpty else { return -1 }
        return accountChartIndexForReferenceCode(accs: chartAccounts, refCode: r) ?? -1
    }

    private static func indicesTouchedByImportTwinActives(
        db: [String: Any],
        twinTags: Set<String>,
        nAccounts: Int,
        chartAccounts: [[String: Any]]
    ) -> Set<Int> {
        guard !twinTags.isEmpty else { return Set() }
        var out = Set<Int>()
        guard let years = db["years"] as? [[String: Any]] else { return out }
        for yd in years {
            for rec in coerceToArrayOfStringKeyedDicts(yd["records"]) {
                if boolFromJSON(rec["is_cancelled"]) { continue }
                if stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
                let tag = twinKeyTag(importedRecordBalanceTwinKey(rec))
                if !twinTags.contains(tag) { continue }
                let amount = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero
                let c1 = stringFromJSON(rec["account_primary_code"])
                let c2 = stringFromJSON(rec["account_secondary_code"])
                let i1 = accountColumnIndexInLatestChart(chartAccounts, c1)
                let i2 = accountColumnIndexInLatestChart(chartAccounts, c2)
                if i1 >= 0, i1 < nAccounts, amount != .zero { out.insert(i1) }
                if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts, amount != .zero { out.insert(i2) }
            }
        }
        return out
    }

    private static func accountCodesEqualForRecords(_ a: String, _ b: String) -> Bool {
        let x = a.trimmingCharacters(in: .whitespacesAndNewlines)
        let y = b.trimmingCharacters(in: .whitespacesAndNewlines)
        if x.isEmpty || y.isEmpty { return false }
        if x == y { return true }
        if x.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
           y.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
           let ix = Int(x), let iy = Int(y), ix == iy {
            return true
        }
        return false
    }

    private static func accountHasNonCancelledMovementTouchingCode(db: [String: Any], accountCode: String) -> Bool {
        let code = accountCode.trimmingCharacters(in: .whitespacesAndNewlines)
        if code.isEmpty { return false }
        guard let years = db["years"] as? [[String: Any]] else { return false }
        for yd in years {
            for rec in coerceToArrayOfStringKeyedDicts(yd["records"]) {
                if boolFromJSON(rec["is_cancelled"]) { continue }
                if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
                let c1 = stringFromJSON(rec["account_primary_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
                if accountCodesEqualForRecords(c1, code) { return true }
                if isGirocontoRecord(rec) {
                    let c2 = stringFromJSON(rec["account_secondary_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
                    if accountCodesEqualForRecords(c2, code) { return true }
                }
            }
        }
        return false
    }

    private static let legacyDatRecordLen = 121

    private static func canonicalLegacySaldoCodeKey(_ ck: String) -> String {
        let s = ck.trimmingCharacters(in: .whitespacesAndNewlines)
        if s.isEmpty { return "" }
        if s.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }), let n = Int(s) {
            return String(n)
        }
        return s
    }

    /// Saldi *sld.aco* (snapshot all’import) rimappati per **codice conto** all’ultimo anno.
    private static func legacyAbsoluteAmounts(db: [String: Any], nAccounts: Int) -> [Decimal]? {
        guard let yb = yearBucketForCalendar(db: db, year: planReferenceYear) else { return nil }
        guard let ls = dictionaryFromAnyRoot(yb["legacy_saldi"]),
              let raw = ls["amounts"] as? [Any],
              !raw.isEmpty
        else { return nil }
        let accsRef = coerceToArrayOfStringKeyedDicts(yb["accounts"])
        var legacyByCode: [String: Decimal] = [:]
        for j in 0 ..< min(accsRef.count, raw.count) {
            let ck = stringFromJSON(accsRef[j]["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            guard !ck.isEmpty else { continue }
            let key = canonicalLegacySaldoCodeKey(ck)
            guard !key.isEmpty else { continue }
            legacyByCode[key] = parseLooseDecimal(stringFromJSON(raw[j])) ?? .zero
        }
        guard let years = db["years"] as? [[String: Any]], !years.isEmpty else { return nil }
        let latestYear = years.map { intFromJSON($0["year"]) }.max() ?? 0
        guard let yearData = years.first(where: { intFromJSON($0["year"]) == latestYear }) else { return nil }
        let accountsLatest = coerceToArrayOfStringKeyedDicts(yearData["accounts"])
        var out: [Decimal] = []
        for i in 0 ..< nAccounts {
            if i >= accountsLatest.count {
                out.append(.zero)
                continue
            }
            var ck = stringFromJSON(accountsLatest[i]["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            if ck.isEmpty { ck = String(i + 1) }
            out.append(legacyByCode[canonicalLegacySaldoCodeKey(ck)] ?? .zero)
        }
        return out
    }

    /// Effetto delle sole righe **create in app** (``raw_record`` vuoto), inclusa ogni loro modifica/annullo.
    private static func computeNewRecordsEffect(db: [String: Any], nAccounts: Int, chartAccounts: [[String: Any]]) -> [Decimal] {
        var balances = Array(repeating: Decimal.zero, count: nAccounts)
        guard let years = db["years"] as? [[String: Any]] else { return balances }
        for yd in years {
            for rec in coerceToArrayOfStringKeyedDicts(yd["records"]) {
                if boolFromJSON(rec["is_cancelled"]) { continue }
                if !stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
                if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
                let y = intFromJSON(rec["year"])
                if isDotazioneRecord(rec), y != legacyDotazioneYear { continue }
                let amount = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero
                let i1 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_primary_code"]))
                let i2 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_secondary_code"]))
                if i1 >= 0, i1 < nAccounts { balances[i1] += amount }
                if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts { balances[i2] -= amount }
            }
        }
        return balances
    }

    /// Compensa nel *sld* l’effetto delle righe **importate annullate** in app.
    private static func computeCancelledImportedAdjustment(
        db: [String: Any],
        latestYear: Int,
        nAccounts: Int,
        cutoff: String,
        chartAccounts: [[String: Any]]
    ) -> [Decimal] {
        var adj = Array(repeating: Decimal.zero, count: nAccounts)
        guard let years = db["years"] as? [[String: Any]] else { return adj }
        var pool: [[String: Any]] = []
        for yd in years {
            let y = intFromJSON(yd["year"])
            if y > latestYear { continue }
            pool.append(contentsOf: coerceToArrayOfStringKeyedDicts(yd["records"]))
        }
        pool.sort { recordMergeSortKey($0) < recordMergeSortKey($1) }
        for rec in pool {
            if !boolFromJSON(rec["is_cancelled"]) { continue }
            if stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { continue }
            if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
            let y = intFromJSON(rec["year"])
            if isDotazioneRecord(rec), y != legacyDotazioneYear { continue }
            let rDate = stringFromJSON(rec["date_iso"])
            if !rDate.isEmpty, rDate > cutoff { continue }
            let amount = -(parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero)
            let i1 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_primary_code"]))
            let i2 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_secondary_code"]))
            if i1 >= 0, i1 < nAccounts { adj[i1] += amount }
            if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts { adj[i2] -= amount }
        }
        return adj
    }

    private static func parseAmountLegacyDatField(_ value: String) -> Decimal? {
        let clean = value.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "E", with: "")
            .replacingOccurrences(of: "L", with: "")
        if clean.isEmpty { return .zero }
        let pattern = "[+-]?\\d[\\d\\.]*([,\\.]\\d+)?"
        guard let re = try? NSRegularExpression(pattern: pattern, options: []),
              let m = re.firstMatch(in: clean, options: [], range: NSRange(location: 0, length: clean.utf16.count)),
              let sr = Range(m.range, in: clean) else { return nil }
        let num = String(clean[sr])
            .replacingOccurrences(of: ".", with: "")
            .replacingOccurrences(of: ",", with: ".")
        if num.isEmpty { return nil }
        return Decimal(string: num)
    }

    private static func syntheticRecordFromLegacyDatRaw(_ rawLine: String, hostYear: Int) -> [String: Any]? {
        let line = rawLine
        guard line.count >= legacyDatRecordLen else { return nil }
        let i23 = line.index(line.startIndex, offsetBy: 23)
        let i37 = line.index(line.startIndex, offsetBy: 37)
        let i39 = line.index(line.startIndex, offsetBy: 39)
        let i40 = line.index(line.startIndex, offsetBy: 40)
        let i42 = line.index(line.startIndex, offsetBy: 42)
        let i43 = line.index(line.startIndex, offsetBy: 43)
        guard let amt = parseAmountLegacyDatField(String(line[i23..<i37])) else { return nil }
        let catRaw = String(line[i37..<i39]).trimmingCharacters(in: .whitespacesAndNewlines)
        let acc1 = String(line[i39..<i40]).trimmingCharacters(in: .whitespacesAndNewlines)
        let acc2 = String(line[i42..<i43]).trimmingCharacters(in: .whitespacesAndNewlines)
        let catStr = (!catRaw.isEmpty && catRaw.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) })) ? catRaw : "0"
        let acc1c = acc1.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }) ? acc1 : ""
        let acc2c = acc2.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }) ? acc2 : ""
        return [
            "year": hostYear,
            "amount_eur": decimalStringForLightJson(amt),
            "category_code": catStr,
            "category_name": "",
            "account_primary_code": acc1c,
            "account_secondary_code": acc2c,
        ]
    }

    private static func recordContributionToBalanceVector(
        _ rec: [String: Any], nAccounts: Int, chartAccounts: [[String: Any]]
    ) -> [Decimal] {
        var out = Array(repeating: Decimal.zero, count: nAccounts)
        let y = intFromJSON(rec["year"])
        if isDotazioneRecord(rec), y != legacyDotazioneYear { return out }
        let amount = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero
        let i1 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_primary_code"]))
        let i2 = accountColumnIndexInLatestChart(chartAccounts, stringFromJSON(rec["account_secondary_code"]))
        if i1 >= 0, i1 < nAccounts { out[i1] += amount }
        if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts { out[i2] -= amount }
        return out
    }

    /// Differenza ``contrib(stato attuale) − contrib(blocco .dat originale)`` per ogni riga importata ancora attiva
    /// e modificata in app: rende visibili nei saldi le modifiche su righe legacy senza ricalcolare il *sld*.
    private static func computeImportedActiveEditAdjustment(
        db: [String: Any], latestYear: Int, nAccounts: Int, chartAccounts: [[String: Any]]
    ) -> [Decimal] {
        var adj = Array(repeating: Decimal.zero, count: nAccounts)
        guard let years = db["years"] as? [[String: Any]] else { return adj }
        for yd in years {
            let y = intFromJSON(yd["year"])
            if y > latestYear { continue }
            for rec in coerceToArrayOfStringKeyedDicts(yd["records"]) {
                if boolFromJSON(rec["is_cancelled"]) { continue }
                if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
                let raw = stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines)
                if raw.isEmpty { continue }
                if raw.count < legacyDatRecordLen { continue }
                guard let synth = syntheticRecordFromLegacyDatRaw(raw, hostYear: y) else { continue }
                let v0 = recordContributionToBalanceVector(synth, nAccounts: nAccounts, chartAccounts: chartAccounts)
                let v1 = recordContributionToBalanceVector(rec, nAccounts: nAccounts, chartAccounts: chartAccounts)
                for i in 0 ..< nAccounts { adj[i] += v1[i] - v0[i] }
            }
        }
        return adj
    }

    /// Saldo assoluto = ``*sld.aco`` + righe app + annulli su righe import + correzione modifiche su righe import.
    /// Per le colonne con twin import (riga annullata + ancora attiva) si sostituisce col replay che esclude il duplicato.
    private static func hybridAbsoluteBalancesForSaldi(db: [String: Any], todayCancelCutoff: String) -> [Decimal]? {
        guard let years = db["years"] as? [[String: Any]], !years.isEmpty else { return nil }
        let latestYear = years.map { intFromJSON($0["year"]) }.max() ?? 0
        guard let yearData = years.first(where: { intFromJSON($0["year"]) == latestYear }) else { return nil }
        let accounts = coerceToArrayOfStringKeyedDicts(yearData["accounts"])
        let n = accounts.count
        guard n > 0 else { return nil }
        let todayC = String(todayCancelCutoff.prefix(10))

        guard let la = legacyAbsoluteAmounts(db: db, nAccounts: n) else {
            let tk = importCancelTwinBalanceKeys(db: db)
            return computeBalancesAsOf(
                db: db, latestYear: latestYear, nAccounts: n, cutoff: todayC,
                excludeImportTwinActives: !tk.isEmpty, chartAccounts: accounts
            )
        }
        let nfx = computeNewRecordsEffect(db: db, nAccounts: n, chartAccounts: accounts)
        let canc = computeCancelledImportedAdjustment(
            db: db, latestYear: latestYear, nAccounts: n, cutoff: todayC, chartAccounts: accounts
        )
        let editAdj = computeImportedActiveEditAdjustment(
            db: db, latestYear: latestYear, nAccounts: n, chartAccounts: accounts
        )
        var out: [Decimal] = []
        out.reserveCapacity(n)
        for i in 0 ..< n {
            var v: Decimal = la[i]
            if i < nfx.count { v += nfx[i] }
            if i < canc.count { v += canc[i] }
            if i < editAdj.count { v += editAdj[i] }
            out.append(v)
        }
        let twinTags = importCancelTwinBalanceKeys(db: db)
        guard !twinTags.isEmpty else { return out }
        let aff = indicesTouchedByImportTwinActives(db: db, twinTags: twinTags, nAccounts: n, chartAccounts: accounts)
        guard !aff.isEmpty else { return out }
        let replayExcl = computeBalancesAsOf(
            db: db, latestYear: latestYear, nAccounts: n, cutoff: "9999-12-31",
            excludeImportTwinActives: true, chartAccounts: accounts
        )
        for i in aff where i < out.count && i < replayExcl.count {
            out[i] = replayExcl[i]
        }
        return out
    }

    private static func computeBalancesAsOf(
        db: [String: Any],
        latestYear: Int,
        nAccounts: Int,
        cutoff: String,
        excludeImportTwinActives: Bool = false,
        chartAccounts: [[String: Any]]
    ) -> [Decimal] {
        let twinTagSet: Set<String> = excludeImportTwinActives ? importCancelTwinBalanceKeys(db: db) : Set()
        var pool: [[String: Any]] = []
        if let years = db["years"] as? [[String: Any]] {
            for yd in years {
                let y = intFromJSON(yd["year"])
                if y > latestYear { continue }
                pool.append(contentsOf: coerceToArrayOfStringKeyedDicts(yd["records"]))
            }
        }
        pool.sort { recordMergeSortKey($0) < recordMergeSortKey($1) }
        var balances = Array(repeating: Decimal.zero, count: nAccounts)
        for rec in pool {
            if boolFromJSON(rec["is_cancelled"]) { continue }
            if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
            if !twinTagSet.isEmpty,
               !stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
               twinTagSet.contains(twinKeyTag(importedRecordBalanceTwinKey(rec))) {
                continue
            }
            let y = intFromJSON(rec["year"])
            if isDotazioneRecord(rec), y != legacyDotazioneYear { continue }
            let rDate = stringFromJSON(rec["date_iso"])
            if !rDate.isEmpty, rDate > cutoff { continue }
            let amount = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero
            let c1 = stringFromJSON(rec["account_primary_code"])
            let c2 = stringFromJSON(rec["account_secondary_code"])
            let i1 = accountColumnIndexInLatestChart(chartAccounts, c1)
            let i2 = accountColumnIndexInLatestChart(chartAccounts, c2)
            if i1 >= 0, i1 < nAccounts { balances[i1] += amount }
            if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts { balances[i2] -= amount }
        }
        return balances
    }

    private static func computeFutureDatedOnly(
        db: [String: Any],
        latestYear: Int,
        nAccounts: Int,
        today: String,
        excludeImportTwinActives: Bool = false,
        chartAccounts: [[String: Any]]
    ) -> [Decimal] {
        let twinTagSet: Set<String> = excludeImportTwinActives ? importCancelTwinBalanceKeys(db: db) : Set()
        var pool: [[String: Any]] = []
        if let years = db["years"] as? [[String: Any]] {
            for yd in years {
                let y = intFromJSON(yd["year"])
                if y > latestYear { continue }
                pool.append(contentsOf: coerceToArrayOfStringKeyedDicts(yd["records"]))
            }
        }
        pool.sort { recordMergeSortKey($0) < recordMergeSortKey($1) }
        var balances = Array(repeating: Decimal.zero, count: nAccounts)
        for rec in pool {
            if boolFromJSON(rec["is_cancelled"]) { continue }
            if boolFromJSON(rec["is_virtuale_discharge"]) { continue }
            if !twinTagSet.isEmpty,
               !stringFromJSON(rec["raw_record"]).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
               twinTagSet.contains(twinKeyTag(importedRecordBalanceTwinKey(rec))) {
                continue
            }
            let y = intFromJSON(rec["year"])
            if isDotazioneRecord(rec), y != legacyDotazioneYear { continue }
            let rDate = stringFromJSON(rec["date_iso"])
            if rDate.isEmpty || rDate <= today { continue }
            let amount = parseLooseDecimal(stringFromJSON(rec["amount_eur"])) ?? .zero
            let c1 = stringFromJSON(rec["account_primary_code"])
            let c2 = stringFromJSON(rec["account_secondary_code"])
            let i1 = accountColumnIndexInLatestChart(chartAccounts, c1)
            let i2 = accountColumnIndexInLatestChart(chartAccounts, c2)
            if i1 >= 0, i1 < nAccounts { balances[i1] += amount }
            if isGirocontoRecord(rec), i2 >= 0, i2 < nAccounts { balances[i2] -= amount }
        }
        return balances
    }

    private static func accountChartIndexForReferenceCode(accs: [[String: Any]], refCode: String) -> Int? {
        let r = refCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !r.isEmpty else { return nil }
        for (ix, acc) in accs.enumerated() {
            let c = stringFromJSON(acc["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            if c.isEmpty { continue }
            if c == r { return ix }
            if c.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
               r.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
               let ic = Int(c), let ir = Int(r), ic == ir {
                return ix
            }
        }
        return nil
    }

    private static func computeSpeseCcFooterAmounts(
        db: [String: Any],
        saldoAssoluti: [Decimal],
        accounts: [[String: Any]]
    ) -> [Decimal] {
        let n = saldoAssoluti.count
        var out = (0 ..< n).map { _ in Decimal.zero }
        guard n > 0 else { return out }
        for i in 0 ..< min(n, accounts.count) {
            if !boolFromJSON(accounts[i]["credit_card"]) { continue }
            let ref = stringFromJSON(accounts[i]["credit_card_reference_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            guard !ref.isEmpty else { continue }
            guard let j = accountChartIndexForReferenceCode(accs: accounts, refCode: ref), j >= 0, j < n, j != i else { continue }
            let cardCode = stringFromJSON(accounts[i]["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            if !accountHasNonCancelledMovementTouchingCode(db: db, accountCode: cardCode) { continue }
            out[j] = out[j] + saldoAssoluti[i]
        }
        return out
    }

    private static func refreshLightSaldiRowDerivedFromAbsDay(_ block: inout [String: Any]) {
        var rows = coerceToArrayOfStringKeyedDicts(block["rows"])
        guard !rows.isEmpty else { return }
        var newRows: [[String: Any]] = []
        for var m in rows {
            let a = parseLooseDecimal(stringFromJSON(m["saldo_assoluto"])) ?? .zero
            let d = parseLooseDecimal(stringFromJSON(m["saldo_alla_data"])) ?? .zero
            let sf = a - d
            m["spese_future"] = decimalStringForLightJson(sf)
            let isCc = boolFromJSON(m["credit_card"])
            let scc = parseLooseDecimal(stringFromJSON(m["spese_cc"])) ?? .zero
            let disp = isCc ? Decimal.zero : (a + sf + scc)
            m["disponibilita"] = decimalStringForLightJson(disp)
            newRows.append(m)
        }
        rows = newRows
        let isCcFlags = rows.map { boolFromJSON($0["credit_card"]) }
        let absVals = rows.map { parseLooseDecimal(stringFromJSON($0["saldo_assoluto"])) ?? .zero }
        let sfVals = rows.map { parseLooseDecimal(stringFromJSON($0["spese_future"])) ?? .zero }
        let sccVals = rows.map { parseLooseDecimal(stringFromJSON($0["spese_cc"])) ?? .zero }
        var tAbs = Decimal.zero
        var tSf = Decimal.zero
        var tScc = Decimal.zero
        for i in 0 ..< rows.count where !isCcFlags[i] {
            tAbs += absVals[i]
            tSf += sfVals[i]
            tScc += sccVals[i]
        }
        block["rows"] = rows
        block["totals"] = [
            "saldo_assoluti_non_cc": decimalStringForLightJson(tAbs),
            "spese_future_non_cc": decimalStringForLightJson(tSf),
            "spese_cc_non_cc": decimalStringForLightJson(tScc),
            "disponibilita_non_cc": decimalStringForLightJson(tAbs + tSf + tScc),
        ]
    }

    private static func buildLightSaldiSnapshotDict(from db: [String: Any]) -> [String: Any]? {
        guard let years = db["years"] as? [[String: Any]], !years.isEmpty else { return nil }
        let latestYear = years.map { intFromJSON($0["year"]) }.max() ?? 0
        guard let yearData = years.first(where: { intFromJSON($0["year"]) == latestYear }),
              let accounts = yearData["accounts"] as? [[String: Any]] else { return nil }
        let n = accounts.count
        guard n > 0 else { return nil }
        let today = todayIsoLocal()
        let namesFull = accounts.map { stringFromJSON($0["name"]) }
        let twinTags = importCancelTwinBalanceKeys(db: db)
        let excludeTwin = !twinTags.isEmpty
        let fut = computeFutureDatedOnly(
            db: db, latestYear: latestYear, nAccounts: n, today: today, excludeImportTwinActives: excludeTwin,
            chartAccounts: accounts
        )
        guard fut.count == n else { return nil }
        guard let saldoAbsFull = hybridAbsoluteBalancesForSaldi(db: db, todayCancelCutoff: today), saldoAbsFull.count == n else { return nil }

        let speseCcFull = computeSpeseCcFooterAmounts(db: db, saldoAssoluti: saldoAbsFull, accounts: accounts)
        let ccFlags = (0 ..< n).map { i in i < accounts.count ? boolFromJSON(accounts[i]["credit_card"]) : false }
        let keep = saldiVisibleIndices(db: db, latestAccounts: accounts, namesFull: namesFull)

        var rows: [[String: Any]] = []
        for i in keep {
            let a = saldoAbsFull[i]
            let sf = fut[i]
            let scc = i < speseCcFull.count ? speseCcFull[i] : .zero
            let cc = i < ccFlags.count ? ccFlags[i] : false
            let oggi = a - sf
            let disp = cc ? Decimal.zero : (a + sf + scc)
            let code = stringFromJSON(accounts[i]["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            rows.append([
                "account_code": code.isEmpty ? String(i + 1) : code,
                "account_name": namesFull[i],
                "saldo_assoluto": decimalStringForLightJson(a),
                "saldo_alla_data": decimalStringForLightJson(oggi),
                "spese_future": decimalStringForLightJson(sf),
                "spese_cc": decimalStringForLightJson(scc),
                "disponibilita": decimalStringForLightJson(disp),
                "credit_card": cc,
            ])
        }
        var tAbs = Decimal.zero
        var tSf = Decimal.zero
        var tScc = Decimal.zero
        for i in keep {
            let cc = i < ccFlags.count ? ccFlags[i] : false
            if cc { continue }
            tAbs += saldoAbsFull[i]
            tSf += fut[i]
            tScc += i < speseCcFull.count ? speseCcFull[i] : .zero
        }
        return [
            "snapshot_date_iso": today,
            "year_basis": latestYear,
            "rows": rows,
            "totals": [
                "saldo_assoluti_non_cc": decimalStringForLightJson(tAbs),
                "spese_future_non_cc": decimalStringForLightJson(tSf),
                "spese_cc_non_cc": decimalStringForLightJson(tScc),
                "disponibilita_non_cc": decimalStringForLightJson(tAbs + tSf + tScc),
            ],
        ]
    }

    private static func attachLightSaldiFromFull(into lightDb: inout [String: Any], fullDb: [String: Any]) {
        guard let snap = buildLightSaldiSnapshotDict(from: fullDb) else { return }
        lightDb["light_saldi"] = snap
    }

    /// Costruisce il JSON da scrivere in ``*_light.enc`` (finestra mobile + ``light_saldi`` dal completo).
    public static func buildLightDatabaseForExport(from fullDb: [String: Any]) throws -> [String: Any] {
        guard let data = try? JSONSerialization.data(withJSONObject: fullDb, options: []),
              var out = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ContiDBError.invalidJSON
        }
        let window = lightWindowStartIsoForExport()
        guard let yearsIn = out["years"] as? [[String: Any]], !yearsIn.isEmpty else {
            attachLightSaldiFromFull(into: &out, fullDb: fullDb)
            return out
        }
        let maxYear = yearsIn.map { intFromJSON($0["year"]) }.max() ?? 0
        var yearsOut: [[String: Any]] = []
        var seenMax = false
        for y in yearsIn {
            let yn = intFromJSON(y["year"])
            let recs = coerceToArrayOfStringKeyedDicts(y["records"])
            let filtered = recs.filter { recordInLightWindowExport($0, windowStart: window) }
            var sorted = filtered
            sorted.sort { a, b in
                let ka = recordSortKeyNewestFirst(a)
                let kb = recordSortKeyNewestFirst(b)
                if ka.0 != kb.0 { return ka.0 > kb.0 }
                return ka.1 > kb.1
            }
            if yn != maxYear, sorted.isEmpty { continue }
            var yc = y
            yc["records"] = sorted
            yearsOut.append(yc)
            if yn == maxYear { seenMax = true }
        }
        if !seenMax {
            guard let tmpl = yearsIn.first(where: { intFromJSON($0["year"]) == maxYear }) else {
                throw ContiDBError.invalidJSON
            }
            var yc: [String: Any] = [
                "year": maxYear,
                "accounts": tmpl["accounts"] as Any,
                "categories": tmpl["categories"] as Any,
                "records": [] as [[String: Any]],
            ]
            for (k, v) in tmpl where yc[k] == nil {
                yc[k] = v
            }
            yearsOut.append(yc)
        }
        yearsOut.sort { intFromJSON($0["year"]) < intFromJSON($1["year"]) }
        out["years"] = yearsOut
        let head = String(todayIsoLocal().prefix(10))
        out["light_sidecar_generated_at"] = head
        out["light_sidecar_window_start"] = window
        attachLightSaldiFromFull(into: &out, fullDb: fullDb)
        return out
    }

    private static func maxRegistrationNumber(_ db: [String: Any]) -> Int {
        guard let years = db["years"] as? [[String: Any]] else { return 0 }
        var m = 0
        for y in years {
            for r in coerceToArrayOfStringKeyedDicts(y["records"]) {
                let v = intFromJSON(r["registration_number"])
                if v > m { m = v }
            }
        }
        return m
    }

    private static func collectLightIds(_ db: [String: Any]) -> Set<String> {
        guard let years = db["years"] as? [[String: Any]] else { return Set() }
        var s = Set<String>()
        for y in years {
            for r in coerceToArrayOfStringKeyedDicts(y["records"]) {
                let rid = stringFromJSON(r[contiLightRecordIdKey]).trimmingCharacters(in: .whitespacesAndNewlines)
                if !rid.isEmpty { s.insert(rid) }
            }
        }
        return s
    }

    private static func ensureYearBucketForMerge(db: inout [String: Any], targetYear: Int) throws -> [String: Any] {
        var years = db["years"] as? [[String: Any]] ?? []
        if let y = years.first(where: { intFromJSON($0["year"]) == targetYear }) {
            return y
        }
        guard let latest = years.max(by: { intFromJSON($0["year"]) < intFromJSON($1["year"]) }) else {
            throw ContiDBError.invalidJSON
        }
        var newY: [String: Any] = [
            "year": targetYear,
            "accounts": latest["accounts"] as Any,
            "categories": latest["categories"] as Any,
            "records": [] as [[String: Any]],
        ]
        for (k, v) in latest where newY[k] == nil {
            newY[k] = v
        }
        years.append(newY)
        years.sort { intFromJSON($0["year"]) < intFromJSON($1["year"]) }
        db["years"] = years
        return newY
    }

    /// Come ``merge_light_new_records_into_main`` in ``light_enc_sidecar.py``.
    public static func mergeLightNewRecordsIntoMain(main: inout [String: Any], light: [String: Any]) -> Int {
        guard let lightYears = light["years"] as? [[String: Any]] else { return 0 }
        var existing = collectLightIds(main)
        var nextReg = maxRegistrationNumber(main) + 1
        var added = 0
        for yl in lightYears {
            let ynum = intFromJSON(yl["year"])
            for rec in coerceToArrayOfStringKeyedDicts(yl["records"]) {
                let rid = stringFromJSON(rec[contiLightRecordIdKey]).trimmingCharacters(in: .whitespacesAndNewlines)
                guard !rid.isEmpty, !existing.contains(rid) else { continue }
                guard let jsonData = try? JSONSerialization.data(withJSONObject: rec, options: []),
                      var recCopy = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any] else { continue }
                do {
                    _ = try ensureYearBucketForMerge(db: &main, targetYear: ynum)
                } catch {
                    continue
                }
                guard var allYears = main["years"] as? [[String: Any]],
                      let idx = allYears.firstIndex(where: { intFromJSON($0["year"]) == ynum }) else { continue }
                var yb = allYears[idx]
                var recs = coerceToArrayOfStringKeyedDicts(yb["records"])
                let nextSi = (recs.map { intFromJSON($0["source_index"]) }.max() ?? 0) + 1
                recCopy["source_index"] = nextSi
                recCopy["legacy_registration_number"] = nextSi
                recCopy["legacy_registration_key"] = "APP:conti_light:\(ynum):\(rid)"
                recCopy["registration_number"] = nextReg
                nextReg += 1
                recs.append(recCopy)
                yb["records"] = recs
                allYears[idx] = yb
                main["years"] = allYears
                existing.insert(rid)
                added += 1
            }
        }
        return added
    }

    /// Scrive un database cifrato (stesso formato del desktop).
    public static func saveEncryptedDbToDisk(db: [String: Any], encURL: URL, keyString: String) throws {
        guard let enc = FernetEncryptor(keyFileContents: keyString) else {
            throw ContiDBError.cannotEncrypt
        }
        let opts: JSONSerialization.WritingOptions = [.prettyPrinted]
        let jsonData = try JSONSerialization.data(withJSONObject: db, options: opts)
        let tokenUtf8 = try enc.encryptToUTF8String(plaintext: jsonData)
        try FileManager.default.createDirectory(
            at: encURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        guard let outData = tokenUtf8.data(using: .utf8) else { throw ContiDBError.cannotEncrypt }
        try outData.write(to: encURL, options: .atomic)
    }

    /**
     All’accesso: fonde il light in memoria nel ``conti_utente_*.enc`` completo (se presente), ricalcola saldi,
     riscrive **entrambi** i file. Ritorna il DB light da usare in sessione (lista Movimenti / Saldi).
     */
    public static func syncDualEncAtStartup(
        lightDb: [String: Any],
        lightEncURL: URL,
        keyURL: URL,
        email: String,
        password: String
    ) throws -> (sessionLight: [String: Any], mergedRows: Int, note: String) {
        let em = email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let fullURL = perUserEncURL(primaryEnc: lightEncURL, email: em)
        guard FileManager.default.fileExists(atPath: fullURL.path) else {
            return (lightDb, 0, "Nessun file completo \(fullURL.lastPathComponent); uso solo il light.")
        }
        _ = waitForPathsStableIfDropbox([keyURL, fullURL, lightEncURL])
        let keyString = try String(contentsOf: keyURL, encoding: .utf8)
        var fullDb = try loadEncryptedDBFull(encURL: fullURL, keyURL: keyURL)
        guard tryLogin(db: fullDb, email: em, password: password) != nil else {
            return (lightDb, 0, "File completo presente ma accesso non riuscito; uso solo il light.")
        }
        let pwd = password.trimmingCharacters(in: .whitespacesAndNewlines)
        var main = fullDb
        let n = mergeLightNewRecordsIntoMain(main: &main, light: lightDb)
        recomputeLightSaldiFromFullDb(&main)
        let lightExport = try buildLightDatabaseForExport(from: main)
        try saveEncryptedDbToDisk(db: main, encURL: fullURL, keyString: keyString)
        try saveEncryptedDbToDisk(db: lightExport, encURL: lightEncURL, keyString: keyString)
        var msg = "Database allineato: saldi ricalcolati; salvati file completo e light."
        if n > 0 {
            msg = "Importate \(n) registrazioni dall’app light nel file completo. " + msg
        }
        return (lightExport, n, msg)
    }

    /// Solo dal blocco ``light_saldi`` scritto dal desktop sul DB completo. Nessun ricalcolo dai movimenti nel file light.
    public static func saldiDueForme(db: [String: Any], todayIso: String) -> [ContiSaldRiga] {
        _ = todayIso
        return saldiRigheFromLightSaldiJson(db: db) ?? []
    }

    private static func saldiRigheFromLightSaldiJson(db: [String: Any]) -> [ContiSaldRiga]? {
        guard let block = dictionaryFromAnyRoot(db["light_saldi"]) else { return nil }
        let rows = coerceToArrayOfStringKeyedDicts(block["rows"])
        guard !rows.isEmpty else { return nil }
        return rows.enumerated().map { i, r in
            let code = stringFromJSON(r["account_code"])
            let name = stringFromJSON(r["account_name"])
            let abs = parseLooseDecimal(stringFromJSON(r["saldo_assoluto"])) ?? .zero
            let alla = parseLooseDecimal(stringFromJSON(r["saldo_alla_data"]))
                ?? parseLooseDecimal(stringFromJSON(r["saldo_oggi"]))
                ?? .zero
            let isCc = boolFromJSON(r["credit_card"])
            let sf = parseLooseDecimal(stringFromJSON(r["spese_future"])) ?? (abs - alla)
            let scc = parseLooseDecimal(stringFromJSON(r["spese_cc"])) ?? .zero
            let disp = parseLooseDecimal(stringFromJSON(r["disponibilita"])) ?? (isCc ? .zero : (abs + sf + scc))
            let id = code.isEmpty ? "acc-\(i)" : "acc-\(code)"
            return ContiSaldRiga(
                id: id,
                accountName: name,
                saldoAssoluto: abs,
                saldoOggi: alla,
                isCreditCard: isCc,
                speseFuture: sf,
                speseCC: scc,
                disponibilita: disp
            )
        }
    }

    private static func decimalStringForLightJson(_ value: Decimal) -> String {
        NSDecimalNumber(decimal: value).stringValue
    }

    private static func categoryCodeInt(_ r: [String: Any]) -> Int? {
        let raw = stringFromJSON(r["category_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty, raw.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }) else { return nil }
        return Int(raw)
    }

    /// Solo legacy (import): categoria codice 0. Non è prevista per l’uso corrente — valorizzare un conto con una girata conto/conto.
    private static func isDotazioneRecord(_ r: [String: Any]) -> Bool {
        categoryCodeInt(r) == 0
    }

    private static func isGirocontoRecord(_ r: [String: Any]) -> Bool {
        if categoryCodeInt(r) == 1 { return true }
        let cat = stringFromJSON(r["category_name"]).uppercased()
        return cat.contains("GIRATA.CONTO/CONTO") || cat.contains("GIRATA CONTO/CONTO")
    }

    /// Come `category_display_name` in `main_app.py` (nome piano senza prefisso segno categoria).
    public static func categoryPlanDisplayName(_ raw: String) -> String {
        let base = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let c0 = base.first else { return "" }
        if "+-=".contains(c0) {
            return String(base.dropFirst()).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return base
    }

    /// Come `is_hidden_dotazione_category_name` in `main_app.py`: mai mostrare «dotazione iniziale».
    public static func isHiddenDotazioneCategoryName(_ raw: String) -> Bool {
        let d = categoryPlanDisplayName(raw).lowercased()
        let n = d.replacingOccurrences(of: ".", with: " ")
        return n.contains("dotazione")
    }

    /// `gg/mm/aaaa` da prefisso `yyyy-MM-dd` (o stringa già corta).
    public static func italianDateDisplayFromIso(_ iso: String) -> String {
        let head = String(iso.prefix(10))
        return italianDateDisplay(fromIsoDate: head)
    }

    /// Accetta `gg/mm/aaaa` o `yyyy-MM-dd` → `yyyy-MM-dd`.
    public static func parseItalianOrIsoDateToIso(_ s: String) -> String? {
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return nil }
        if t.contains("-") {
            let parts = t.split(separator: "-", omittingEmptySubsequences: false)
            guard parts.count >= 3, parts[0].count == 4,
                  let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]),
                  (1 ... 12).contains(m), (1 ... 31).contains(d)
            else { return nil }
            return String(format: "%04d-%02d-%02d", y, m, d)
        }
        let parts = t.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 3,
              let d = Int(parts[0]), let m = Int(parts[1]), let y = Int(parts[2]),
              (1 ... 12).contains(m), (1 ... 31).contains(d)
        else { return nil }
        return String(format: "%04d-%02d-%02d", y, m, d)
    }

    /// Categorie e conti dell’**ultimo anno** nel DB (es. form «Nuove registrazioni»). Esclude categoria codice `0`.
    public static func immissionePickLists(from db: [String: Any]) -> (categorie: [ContiImmissioneCategoria], conti: [ContiImmissioneConto])? {
        guard let years = db["years"] as? [[String: Any]], !years.isEmpty else { return nil }
        let yearInts = years.compactMap { intFromJSON($0["year"]) }
        guard let yMax = yearInts.max(),
              let yd = years.first(where: { intFromJSON($0["year"]) == yMax })
        else { return nil }

        let cats = yd["categories"] as? [[String: Any]] ?? []
        let accs = yd["accounts"] as? [[String: Any]] ?? []

        var categorie: [ContiImmissioneCategoria] = []
        for (i, c) in cats.enumerated() {
            let codeRaw = stringFromJSON(c["code"])
            let code = codeRaw.isEmpty ? "\(i)" : codeRaw
            if code == "0" { continue }
            let rawName = stringFromJSON(c["name"])
            if Self.isHiddenDotazioneCategoryName(rawName) { continue }
            let n1 = stringFromJSON(c["note"])
            let n2 = stringFromJSON(c["category_note"])
            let noteRaw = n1.isEmpty ? n2 : n1
            let noteTrim = noteRaw.trimmingCharacters(in: .whitespacesAndNewlines)
            let planNote = noteTrim.isEmpty ? "-" : noteTrim
            categorie.append(
                ContiImmissioneCategoria(
                    code: code,
                    displayName: categoryPlanDisplayName(rawName),
                    planNote: planNote
                )
            )
        }

        func catRank(_ name: String) -> Int {
            let n = name.lowercased()
            if n.contains("consumi ordinari") { return 0 }
            if n.contains("girata"), n.contains("conto") { return 1 }
            return 2
        }
        categorie.sort { a, b in
            let ra = catRank(a.displayName), rb = catRank(b.displayName)
            if ra != rb { return ra < rb }
            return a.displayName.localizedStandardCompare(b.displayName) == .orderedAscending
        }

        func accountNameForCode(_ refCode: String) -> String {
            let rc = refCode.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !rc.isEmpty else { return "" }
            for a in accs {
                let c = stringFromJSON(a["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
                if c == rc { return stringFromJSON(a["name"]).trimmingCharacters(in: .whitespacesAndNewlines) }
                if c.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
                   rc.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }),
                   let ic = Int(c), let ir = Int(rc), ic == ir {
                    return stringFromJSON(a["name"]).trimmingCharacters(in: .whitespacesAndNewlines)
                }
            }
            return ""
        }

        var conti: [ContiImmissioneConto] = []
        for (i, a) in accs.enumerated() {
            let codeRaw = stringFromJSON(a["code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            let code = codeRaw.isEmpty ? String(i + 1) : codeRaw
            let name = stringFromJSON(a["name"]).trimmingCharacters(in: .whitespacesAndNewlines)
            let isCc = boolFromJSON(a["credit_card"])
            let refCode = stringFromJSON(a["credit_card_reference_code"]).trimmingCharacters(in: .whitespacesAndNewlines)
            let refName = isCc ? accountNameForCode(refCode) : ""
            conti.append(
                ContiImmissioneConto(code: code, name: name, isCreditCard: isCc, referenceAccountName: refName)
            )
        }
        conti.sort { a, b in
            if a.name.lowercased() == "cassa" { return true }
            if b.name.lowercased() == "cassa" { return false }
            return a.name.localizedStandardCompare(b.name) == .orderedAscending
        }

        return (categorie, conti)
    }

    /// Euro italiano con esattamente 2 decimali (es. `-1.234,56`).
    public static func formatEuroTwoDecimals(_ value: Decimal) -> String {
        let n = NSDecimalNumber(decimal: value)
        let f = NumberFormatter()
        f.locale = Locale(identifier: "it_IT")
        f.numberStyle = .decimal
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = 2
        return f.string(from: n) ?? "\(value)"
    }

    private static func italianDateDisplay(fromIsoDate iso: String) -> String {
        let parts = iso.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count >= 3,
              parts[0].count == 4,
              let y = Int(parts[0]),
              let m = Int(parts[1]),
              let d = Int(parts[2])
        else { return iso }
        return String(format: "%02d/%02d/%04d", d, m, y)
    }

    /// Come `category_display_name` in `main_app.py`: toglie prefissi `+`, `-`, `=` (e spazi iniziali).
    private static func stripLeadingSignAndSpace(_ s: String) -> String {
        var t = s
        while let c = t.first {
            if c.isWhitespace || c == "+" || c == "-" || c == "−" || c == "=" { t.removeFirst() } else { break }
        }
        return t
    }

    /// Interpreta stringhe tipo `1234.567` (Python), `1.234,56` / `-12,50` (IT).
    private static func parseLooseDecimal(_ raw: String) -> Decimal? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        var s = trimmed
        var negative = false
        if s.first == "−" || s.first == "-" {
            negative = true
            s.removeFirst()
        }
        s = s.replacingOccurrences(of: " ", with: "")
        s = s.replacingOccurrences(of: "−", with: "-")
        let hasComma = s.contains(",")
        let hasDot = s.contains(".")
        if hasComma, hasDot {
            if let li = s.lastIndex(of: ","), let lj = s.lastIndex(of: ".") {
                if li > lj {
                    s = s.replacingOccurrences(of: ".", with: "")
                    s = s.replacingOccurrences(of: ",", with: ".")
                } else {
                    s = s.replacingOccurrences(of: ",", with: "")
                }
            }
        } else if hasComma {
            s = s.replacingOccurrences(of: ".", with: "")
            s = s.replacingOccurrences(of: ",", with: ".")
        }
        guard let d = Decimal(string: s, locale: Locale(identifier: "en_US_POSIX")) else { return nil }
        return negative ? -d : d
    }

    private static func stringFromJSON(_ v: Any?) -> String {
        if let s = v as? String { return s }
        if let n = v as? NSNumber { return n.stringValue }
        return ""
    }

    private static func intFromJSON(_ v: Any?) -> Int {
        if let i = v as? Int { return i }
        if let n = v as? NSNumber { return n.intValue }
        if let s = v as? String, let i = Int(s) { return i }
        return 0
    }

    private static func boolFromJSON(_ v: Any?) -> Bool {
        if let b = v as? Bool { return b }
        if let n = v as? NSNumber { return n.boolValue }
        return false
    }
}

private extension String {
    func constantTimeEqualsString(_ other: String) -> Bool {
        let a = Array(self.utf8)
        let b = Array(other.utf8)
        guard a.count == b.count else { return false }
        var d: UInt8 = 0
        for i in a.indices { d |= a[i] ^ b[i] }
        return d == 0
    }
}
