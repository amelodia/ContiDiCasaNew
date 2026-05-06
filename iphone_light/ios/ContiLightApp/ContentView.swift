import SwiftUI
import UIKit
import UniformTypeIdentifiers

// MARK: - Bookmark cartella (Files / Dropbox)

private enum ContiLightFolderBookmark {
    /// Persistenza come l’app Document-based: dati bookmark in `UserDefaults` (restano dopo chiusura app).
    private static let key = "ContiLight.dataFolderSecurityBookmark"

    static func save(_ url: URL) {
        // iOS/iPadOS: `.withSecurityScope` non è disponibile; usare bookmark minimale.
        // macOS: usare bookmark security-scoped.
        #if os(iOS)
        let bookmarkOptions: URL.BookmarkCreationOptions = [.minimalBookmark]
        #else
        let bookmarkOptions: URL.BookmarkCreationOptions = [.withSecurityScope]
        #endif
        guard let data = try? url.bookmarkData(
            options: bookmarkOptions,
            includingResourceValuesForKeys: [.isDirectoryKey],
            relativeTo: nil
        ) else { return }
        UserDefaults.standard.set(data, forKey: Self.key)
    }

    /// Rinnova il bookmark mentre l’accesso security-scoped è attivo (consigliato da Apple se `bookmarkDataIsStale`).
    static func renew(from url: URL) {
        save(url)
    }

    static func restore() -> URL? {
        guard let data = UserDefaults.standard.data(forKey: Self.key) else { return nil }
        var stale = false
        guard let url = try? URL(
            resolvingBookmarkData: data,
            options: [.withoutUI],
            relativeTo: nil,
            bookmarkDataIsStale: &stale
        ) else {
            UserDefaults.standard.removeObject(forKey: Self.key)
            return nil
        }
        if stale {
            UserDefaults.standard.removeObject(forKey: Self.key)
            return nil
        }
        return url
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: Self.key)
    }
}

// MARK: - Ultima email (prefill schermata accesso)

private enum ContiLightLastLoginEmail {
    private static let key = "ContiLight.lastLoginEmail"

    static func save(_ value: String) {
        let t = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty {
            UserDefaults.standard.removeObject(forKey: key)
        } else {
            UserDefaults.standard.set(t, forKey: key)
        }
    }

    static func load() -> String {
        (UserDefaults.standard.string(forKey: key) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

@MainActor
struct ContentView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.scenePhase) private var scenePhase

    /// Cartella che contiene `.key` e i `.enc` (stessa cartella `data/` del desktop).
    @State private var dataFolderURL: URL?
    /// URL selezionato nel document picker salvato nei bookmark (`UserDefaults`): su iPadOS Dropbox l’accesso sicuro vale per quel URL, non per la cartella genitore.
    @State private var securityScopedBookmarkURL: URL?
    @State private var keyStatusText = ""
    @State private var lightFileStatusText = ""
    @State private var fullFileStatusText = ""
    @State private var email = ""
    @State private var password = ""
    /// Messaggi da login / scelta cartella; se vuoto si mostra `loginFootnoteText`.
    @State private var message = ""
    @State private var isBusy = false
    @State private var isRefreshingSession = false
    @State private var loggedInRecords: [ContiRecordRow] = []
    /// DB sessione per saldi, immissioni e salvataggio; bridging `NSDictionary` dal thread di login.
    @State private var loggedInSessionDb: NSDictionary?
    /// Percorsi risolti all’ultimo accesso riuscito (scrittura `.enc` dopo nuove registrazioni).
    @State private var sessionKeyURL: URL?
    @State private var sessionLightEncURL: URL?
    @State private var movimentiDisplayName = ""
    @State private var movimentiPath = NavigationPath()
    @State private var showFiltriSheet = false
    /// `""` = tutte le categorie / tutti i conti.
    @State private var filterCategoryKey = ""
    @State private var filterAccountKey = ""
    @State private var dataFilePickRequest: DataFilePickRequest?
    @State private var folderPickRequest: FolderPickRequest?
    /// Navigazione interna alla sheet Filtri (tap → lista, senza NavigationLink lento).
    @State private var filtriNavigationPath = NavigationPath()
    /// Elenco movimenti: per data o per numero di registrazione (globale).
    @State private var movimentiListSort: ContiMovimentiListSort = .dateNewestFirst
    /// Se attivo, dopo un accesso con password riuscito la password viene salvata nel Keychain per Face ID / Touch ID.
    @AppStorage("ContiLight.savePasswordForBiometrics") private var savePasswordForBiometrics = false
    /// Messaggio lungo (come più ``showinfo`` sul desktop) dopo materializzazione periodiche.
    @State private var periodicStartupAlertText = ""
    @State private var periodicStartupAlertPresented = false
    /// Throttle per ``refreshLightSessionIfLoggedIn`` (solo lettura + decifra; non riscrive `.enc`). Evita hammer al provider file.
    @State private var lastScenePhaseRefreshAt: Date = .distantPast
    /// Tentativi ritardati di refresh post-login (utile quando Dropbox/Files idrata il file con ritardo).
    @State private var postLoginHydrationRefreshTask: Task<Void, Never>?
    /// Sequenza attiva del tasto Aggiorna (doppio passaggio), per evitare sovrapposizioni.
    @State private var isManualRefreshSequenceRunning = false

    private enum MovimentiFiltriPick: Hashable {
        case category
        case account
    }

    var body: some View {
        NavigationStack(path: $movimentiPath) {
            Group {
                if loggedInSessionDb == nil {
                    loginForm
                } else {
                    recordsList
                }
            }
            .navigationDestination(for: MovimentiSchedaRoute.self) { route in
                switch route {
                case .saldi:
                    ContiLightSaldiSchedaView(sessionDb: loggedInSessionDb)
                case .nuoviDati:
                    ContiLightNuovoMovimentoSchedaView(
                        sessionDb: loggedInSessionDb as? [String: Any],
                        dataFolderURL: dataFolderURL,
                        securityScopedBookmarkURL: securityScopedBookmarkURL,
                        keyURL: sessionKeyURL,
                        lightEncURL: sessionLightEncURL,
                        email: email,
                        password: password,
                        onPersisted: { updatedDb, _, note in
                            loggedInSessionDb = updatedDb as NSDictionary
                            if let d = updatedDb as? [String: Any] {
                                loggedInRecords = ContiDatabase.displayRecords(from: d, sort: movimentiListSort)
                            }
                            message = note
                        }
                    )
                case .modifica(let legacyKey):
                    ContiLightNuovoMovimentoSchedaView(
                        sessionDb: loggedInSessionDb as? [String: Any],
                        dataFolderURL: dataFolderURL,
                        securityScopedBookmarkURL: securityScopedBookmarkURL,
                        keyURL: sessionKeyURL,
                        lightEncURL: sessionLightEncURL,
                        email: email,
                        password: password,
                        onPersisted: { updatedDb, _, note in
                            loggedInSessionDb = updatedDb as NSDictionary
                            if let d = updatedDb as? [String: Any] {
                                loggedInRecords = ContiDatabase.displayRecords(from: d, sort: movimentiListSort)
                            }
                            message = note
                        },
                        editingLegacyKey: legacyKey
                    )
                }
            }
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .onChange(of: loggedInSessionDb == nil) { _, noSession in
            if noSession {
                postLoginHydrationRefreshTask?.cancel()
                postLoginHydrationRefreshTask = nil
                movimentiPath = NavigationPath()
                sessionKeyURL = nil
                sessionLightEncURL = nil
                applySavedLoginEmailIfNeeded()
            }
        }
        .onAppear {
            if dataFolderURL == nil, securityScopedBookmarkURL == nil, let restored = ContiLightFolderBookmark.restore() {
                securityScopedBookmarkURL = restored
                let isDir = (try? restored.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true
                dataFolderURL = isDir ? restored : restored.deletingLastPathComponent()
            }
            applySavedLoginEmailIfNeeded()
            refreshKeyStatus()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active, dataFolderURL != nil {
                refreshKeyStatus()
                // Rilegge il `*_light.enc` con path risolto di nuovo e attesa Dropbox (come «Aggiorna»), così dopo sync non resta la copia precedente in memoria.
                Task { @MainActor in
                    if Date().timeIntervalSince(lastScenePhaseRefreshAt) >= 3 {
                        await refreshLightSessionIfLoggedIn()
                    }
                }
            } else if phase == .background {
                postLoginHydrationRefreshTask?.cancel()
                postLoginHydrationRefreshTask = nil
                closeCurrentSessionAndReleaseLock()
            }
        }
        .onChange(of: email) { _, _ in
            if dataFolderURL != nil {
                refreshKeyStatus()
            }
        }
        .onChange(of: savePasswordForBiometrics) { _, enabled in
            if !enabled {
                ContiLightBiometricLogin.deleteAllBiometricCredentials()
            }
        }
        .onChange(of: showFiltriSheet) { _, open in
            if !open {
                filtriNavigationPath = NavigationPath()
            }
        }
        .onChange(of: movimentiListSort) { _, _ in
            guard let d = loggedInSessionDb as? [String: Any] else { return }
            loggedInRecords = ContiDatabase.displayRecords(from: d, sort: movimentiListSort)
        }
        .alert("Registrazioni periodiche", isPresented: $periodicStartupAlertPresented) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(periodicStartupAlertText)
        }
    }

    /// Logo euro (`EuroBrand.imageset`/asset + file `euro_brand.jpg` nel bundle come riserva).
    /// In una `Form`, senza `.renderingMode(.original)`, l’immagine può risultare invisibile (template tint).
    @ViewBuilder
    private var loginBrandMark: some View {
        if let euro = resolvedLoginEuroUIImage() {
            Image(uiImage: euro)
                .renderingMode(.original)
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 92, height: 92)
                .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 4)
                .accessibilityLabel("Marchio euro Conti di casa")
        } else {
            Image(systemName: "eurosign.circle.fill")
                .font(.system(size: 62))
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.secondary)
                .accessibilityLabel("Marchio euro")
        }
    }

    private func resolvedLoginEuroUIImage() -> UIImage? {
        // 1) JPEG esplicitamente nel bundle (aggiungi `euro_brand.jpg` al target in Xcode → Build Phases → Copy Bundle Resources)
        if let p = Bundle.main.path(forResource: "euro_brand", ofType: "jpg"),
           let img = UIImage(contentsOfFile: p)?.withRenderingMode(.alwaysOriginal) {
            return img
        }
        // 2) Asset catalog Imageset «EuroBrand» (nome immagine Xcode)
        if let img = UIImage(named: "EuroBrand")?.withRenderingMode(.alwaysOriginal) {
            return img
        }
        for name in ["euro", "euro.jpg", "AppIcon-1024"] {
            if let img = UIImage(named: name)?.withRenderingMode(.alwaysOriginal) {
                return img
            }
        }
        // 3) Fallback file generici eventualmente inclusi nel target
        for (file, ext) in [("euro", "jpg"), ("euro", "jpeg"), ("euro", "png")] {
            if let path = Bundle.main.path(forResource: file, ofType: ext),
               let img = UIImage(contentsOfFile: path)?.withRenderingMode(.alwaysOriginal) {
                return img
            }
        }
        return nil
    }

    private var loginFootnoteText: String {
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return message }
        if dataFolderURL == nil {
            return """
            Scegli la cartella dati (stesso file .key, file *_light.enc e eventuale .enc completo del desktop nella stessa cartella),
            poi email e password. L'app usa il file .enc light corretto per la tua email.
            """
        }
        return "Cartella dati già memorizzata. Inserisci email e password, poi tocca Accedi."
    }

    private var loginForm: some View {
        Form {
            Section {
                VStack(spacing: 12) {
                    loginBrandMark
                    Text("Conti di casa — accesso al database cifrato")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
            }
            Section("Accesso") {
                TextField("Email", text: $email)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .keyboardType(.emailAddress)
                    .submitLabel(.next)
                SecureField("Password", text: $password)
                    .submitLabel(.go)
                    .onSubmit { loginWithPassword() }
                if ContiLightBiometricLogin.biometricsAvailable() {
                    Toggle(
                        "Salva password per \(ContiLightBiometricLogin.biometricLabel())",
                        isOn: $savePasswordForBiometrics
                    )
                    .font(.subheadline)
                }
                if ContiLightBiometricLogin.isConfigured(forEmail: email), dataFolderURL != nil {
                    Button(action: loginWithBiometrics) {
                        HStack {
                            if isBusy {
                                ProgressView()
                                    .progressViewStyle(.circular)
                            }
                            Label(
                                "Accedi con \(ContiLightBiometricLogin.biometricLabel())",
                                systemImage: ContiLightBiometricLogin.biometricSystemImageName()
                            )
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .disabled(isBusy)
                }
                Button(action: loginWithPassword) {
                    HStack {
                        if isBusy {
                            ProgressView()
                                .progressViewStyle(.circular)
                        }
                        Text(isBusy ? "Accesso…" : "Accedi")
                    }
                    .frame(maxWidth: .infinity)
                }
                .disabled(isBusy || dataFolderURL == nil || email.isEmpty || password.isEmpty)
            }
            if dataFolderURL == nil {
                Section("Cartella dati") {
                    Text(
                        "Preferisci Scegli cartella dati: serve accesso sia al file .key sia al file *_light.enc. Dropbox reinstallato dovrebbe mostrare bene la cartella. Oppure scegli un solo file; per usare .key e *_light.enc insieme scegli la cartella."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    Button("Scegli cartella dati…") {
                        folderPickRequest = FolderPickRequest()
                    }
                    Button("Oppure scegli un file (.key o .enc)…") {
                        dataFilePickRequest = DataFilePickRequest()
                    }
                }
            } else {
                Section("Posizione dati") {
                    LabeledContent("Cartella") {
                        Text(dataFolderURL?.lastPathComponent ?? "—")
                            .lineLimit(2)
                            .multilineTextAlignment(.trailing)
                    }
                    if !keyStatusText.isEmpty {
                        Text(keyStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if !lightFileStatusText.isEmpty {
                        Text(lightFileStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if !fullFileStatusText.isEmpty {
                        Text(fullFileStatusText)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Button("Cambia cartella…") {
                        folderPickRequest = FolderPickRequest()
                    }
                    Button("Oppure ripunta con un file (.key/.enc)…") {
                        dataFilePickRequest = DataFilePickRequest()
                    }
                    Button("Rimuovi cartella salvata", role: .destructive) {
                        ContiLightFolderBookmark.clear()
                        dataFolderURL = nil
                        securityScopedBookmarkURL = nil
                        keyStatusText = ""
                        lightFileStatusText = ""
                        fullFileStatusText = ""
                        message = ""
                    }
                }
            }
            Section {
                Text(loginFootnoteText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.visible)
        .navigationTitle("Conti di casa")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $folderPickRequest) { _ in
            DocumentFolderPickerRepresentable(
                onPick: { url in
                    Task { @MainActor in
                        folderPickRequest = nil
                        let isDirectory = (try? url.resourceValues(forKeys: [.isDirectoryKey]))?.isDirectory == true
                        guard isDirectory else {
                            message = "Nel selettore cartella devi scegliere la cartella stessa dei dati, non un singolo file. Oppure usa Oppure ripunta con un file."
                            return
                        }
                        guard url.startAccessingSecurityScopedResource() else {
                            message = "Accesso alla cartella negato. Riprovare da Dropbox in File oppure usare Oppure ripunta con un file scegliendo *_light.enc o .key nella stessa cartella."
                            return
                        }
                        url.stopAccessingSecurityScopedResource()
                        ContiLightFolderBookmark.save(url)
                        securityScopedBookmarkURL = url
                        dataFolderURL = url
                        refreshKeyStatus()
                        message = "Cartella impostata. Inserisci email e password, poi Accedi."
                    }
                },
                onCancel: {
                    Task { @MainActor in
                        folderPickRequest = nil
                    }
                }
            )
            .ignoresSafeArea()
        }
        .sheet(item: $dataFilePickRequest) { _ in
            DocumentDataFilePickerRepresentable(
                onPick: { url in
                    Task { @MainActor in
                        dataFilePickRequest = nil
                        let ext = url.pathExtension.lowercased()
                        guard ext == "key" || ext == "enc" else {
                            message = "Seleziona un file .key o *_light.enc nella cartella dati Dropbox. Per .key e *_light.enc insieme preferisci Scegli cartella dati."
                            return
                        }
                        guard url.startAccessingSecurityScopedResource() else {
                            message = "Accesso al file negato da iPadOS/Dropbox. Riprova scegliendo di nuovo un file .key o *_light.enc nella cartella dati (stesso account Dropbox del desktop)."
                            return
                        }
                        url.stopAccessingSecurityScopedResource()
                        ContiLightFolderBookmark.save(url)
                        securityScopedBookmarkURL = url
                        dataFolderURL = url.deletingLastPathComponent()
                        refreshKeyStatus()
                        message = "Punto ai file dalla scelta sopra (accesso sicuro solo a questo file). Per .key e *_light.enc insieme preferisci Scegli cartella dati. Inserisci email e password, poi Accedi."
                    }
                },
                onCancel: {
                    Task { @MainActor in
                        dataFilePickRequest = nil
                    }
                }
            )
            .ignoresSafeArea()
        }
    }

    private func refreshKeyStatus() {
        guard let folder = dataFolderURL else {
            keyStatusText = ""
            lightFileStatusText = ""
            fullFileStatusText = ""
            return
        }
        let scope = securityScopedBookmarkURL ?? folder
        guard scope.startAccessingSecurityScopedResource() else {
            keyStatusText = "Accesso ai file negato (permessi iPadOS / Dropbox)."
            lightFileStatusText = ""
            fullFileStatusText = ""
            return
        }
        defer { scope.stopAccessingSecurityScopedResource() }
        if let k = ContiDatabase.preferredKeyFileURL(inFolder: folder) {
            keyStatusText = "Chiave: \(k.lastPathComponent)"
        } else {
            keyStatusText = "Nessun file .key trovato (es. conti_di_casa.key nella cartella dati)."
        }
        let em = email.trimmingCharacters(in: .whitespacesAndNewlines)
        if let light = ContiDatabase.resolvePrimaryEncURL(inFolder: folder, email: em) {
            let attrs = try? FileManager.default.attributesOfItem(atPath: light.path)
            let mtime = attrs?[.modificationDate] as? Date
            if let d = mtime {
                let f = DateFormatter()
                f.locale = Locale(identifier: "it_IT")
                f.timeZone = .current
                f.dateFormat = "dd/MM/yyyy HH:mm:ss"
                lightFileStatusText = "File light: \(light.lastPathComponent) — aggiornato: \(f.string(from: d))"
            } else {
                lightFileStatusText = "File light: \(light.lastPathComponent)"
            }
        } else {
            let stem = ContiDatabase.userEncFilenameStem(forEmail: em)
            lightFileStatusText = "File light non trovato (atteso: \(stem)_light.enc nella cartella)."
        }
        if !em.isEmpty {
            let stemName = ContiDatabase.userEncFilenameStem(forEmail: em)
            let full = folder.appendingPathComponent("\(stemName).enc", isDirectory: false)
            let attrs = try? FileManager.default.attributesOfItem(atPath: full.path)
            let mtime = attrs?[.modificationDate] as? Date
            if let d = mtime {
                let f = DateFormatter()
                f.locale = Locale(identifier: "it_IT")
                f.timeZone = .current
                f.dateFormat = "dd/MM/yyyy HH:mm:ss"
                fullFileStatusText = "File completo: \(full.lastPathComponent) — aggiornato: \(f.string(from: d))"
            } else {
                fullFileStatusText = "File completo non trovato per questa email (\(full.lastPathComponent))."
            }
        } else {
            fullFileStatusText = "File completo: inserisci email per verificare il percorso dedicato."
        }
        // Aggiorna il bookmark su disco: evita che al prossimo avvio iOS lo consideri obsoleto e «perda» la cartella.
        ContiLightFolderBookmark.renew(from: scope)
    }

    /// Categorie distinte (testo mostrato in lista), ordinate.
    private var movimentiCategoryChoices: [String] {
        let s = Set(loggedInRecords.map(\.categoryDisplay).filter { !$0.isEmpty })
        return s.sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }

    /// Nomi conto (principale o secondario) presenti nei movimenti, ordinati.
    private var movimentiAccountChoices: [String] {
        var s = Set<String>()
        for r in loggedInRecords {
            if !r.accountPrimary.isEmpty { s.insert(r.accountPrimary) }
            if !r.accountSecondary.isEmpty { s.insert(r.accountSecondary) }
        }
        return s.sorted { $0.localizedStandardCompare($1) == .orderedAscending }
    }

    private var movimentiFiltersActive: Bool {
        activeCategoryFilter != nil || activeAccountFilter != nil
    }

    private var showMovimentiEditHint: Bool {
        !filteredMovimentiRecords.isEmpty
    }

    /// Filtro categoria effettivo (`nil` se disattivo o valore non più nella lista).
    private var activeCategoryFilter: String? {
        guard !filterCategoryKey.isEmpty, movimentiCategoryChoices.contains(filterCategoryKey) else { return nil }
        return filterCategoryKey
    }

    private var activeAccountFilter: String? {
        guard !filterAccountKey.isEmpty, movimentiAccountChoices.contains(filterAccountKey) else { return nil }
        return filterAccountKey
    }

    private var filteredMovimentiRecords: [ContiRecordRow] {
        loggedInRecords.filter { row in
            if let c = activeCategoryFilter, row.categoryDisplay != c { return false }
            if let a = activeAccountFilter {
                if row.accountPrimary != a, row.accountSecondary != a { return false }
            }
            return true
        }
    }

    @ViewBuilder
    private func movimentiListRowView(
        row: ContiRecordRow,
        rowPrimaryText: Color,
        amountColor: (Decimal) -> Color,
        accountLine: (ContiRecordRow) -> String
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(row.dateDisplay)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(rowPrimaryText)
                Spacer(minLength: 8)
                Text(row.categoryDisplay)
                    .font(.subheadline)
                    .foregroundStyle(.blue)
                    .multilineTextAlignment(.trailing)
            }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(accountLine(row))
                    .font(.subheadline)
                    .foregroundStyle(rowPrimaryText)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 8)
                HStack(alignment: .firstTextBaseline, spacing: 4) {
                    Text("Importo €")
                        .font(.subheadline)
                        .foregroundStyle(Color.secondary)
                    if let v = row.amountValue {
                        Text(ContiDatabase.formatEuroTwoDecimals(v))
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(amountColor(v))
                    } else {
                        Text(row.amountRawFallback)
                            .font(.subheadline.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if !row.note.isEmpty, row.note != "-" {
                Text(row.note)
                    .font(.caption)
                    .foregroundStyle(rowPrimaryText.opacity(0.9))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.vertical, 4)
    }

    private func hapticMovimentiModifica() {
        let g = UIImpactFeedbackGenerator(style: .medium)
        g.prepare()
        g.impactOccurred()
    }

    @ViewBuilder
    private func movimentiRowConnect(row: ContiRecordRow) -> some View {
        if !row.legacyRegistrationKey.isEmpty {
            HStack(alignment: .top, spacing: 8) {
                movimentiListRowView(
                    row: row,
                    rowPrimaryText: rowPrimaryText,
                    amountColor: amountColor,
                    accountLine: accountLine
                )
                .frame(maxWidth: .infinity, alignment: .leading)
                Image(systemName: "hand.point.up.left.fill")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .padding(.top, 2)
                    .accessibilityHidden(true)
            }
            .contentShape(Rectangle())
            .onLongPressGesture(minimumDuration: 0.5) {
                hapticMovimentiModifica()
                movimentiPath.append(MovimentiSchedaRoute.modifica(legacyKey: row.legacyRegistrationKey))
            }
            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                Button {
                    hapticMovimentiModifica()
                    movimentiPath.append(MovimentiSchedaRoute.modifica(legacyKey: row.legacyRegistrationKey))
                } label: {
                    Label("Modifica", systemImage: "pencil")
                }
                .tint(.indigo)
            }
            .accessibilityElement(children: .combine)
            .accessibilityHint("Tieni premuto mezzo secondo sulla riga, oppure scorri verso sinistra e tocca Modifica, per modificare o annullare.")
        } else {
            movimentiListRowView(
                row: row,
                rowPrimaryText: rowPrimaryText,
                amountColor: amountColor,
                accountLine: accountLine
            )
        }
    }

    private var recordsList: some View {
        List {
            Section {
                if filteredMovimentiRecords.isEmpty {
                    ContentUnavailableView(
                        "Nessun risultato",
                        systemImage: "line.3.horizontal.decrease.circle",
                        description: Text("Prova altri criteri in Filtri o reimposta le selezioni.")
                    )
                    .frame(minHeight: 160)
                    Button("Filtri") { showFiltriSheet = true }
                    .frame(maxWidth: .infinity)
                } else {
                    ForEach(filteredMovimentiRecords) { row in
                        movimentiRowConnect(row: row)
                    }
                }
            } header: {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Conti di casa — \(movimentiDisplayName)")
                        .font(.headline)
                    Text(italianLongToday())
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    if showMovimentiEditHint {
                        Text(
                            "Tieni premuto su una riga (almeno ½ secondo) o scorri a sinistra → Modifica per correggere o annullare una registrazione (anche creata sul desktop). "
                        )
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    }
                    if let summary = movimentiFiltriSummaryLine {
                        Text(summary)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .textCase(nil)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 4)
            }
        }
        .listStyle(.insetGrouped)
        .refreshable {
            await refreshLightSessionIfLoggedIn(forceReResolveEnc: true)
        }
        .navigationTitle("Movimenti")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("Esci", role: .none) {
                    closeCurrentSessionAndReleaseLock()
                }
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                // Ordine pensato per iPhone verticale: prima immissione; filtri+ordinamento in un menu; Saldi; ricarica per ultima.
                Button {
                    movimentiPath.append(MovimentiSchedaRoute.nuoviDati)
                } label: {
                    Image(systemName: "plus.circle.fill")
                }
                .accessibilityLabel("Nuove registrazioni")
                Menu {
                    Button {
                        showFiltriSheet = true
                    } label: {
                        Label("Filtri categoria e conto…", systemImage: "line.3.horizontal.decrease.circle")
                    }
                    Divider()
                    Picker("Ordinamento elenco", selection: $movimentiListSort) {
                        Text("Data (più recenti prima)").tag(ContiMovimentiListSort.dateNewestFirst)
                        Text("N. registrazione (più recenti)").tag(ContiMovimentiListSort.registrationNewestFirst)
                    }
                } label: {
                    Image(
                        systemName: movimentiFiltersActive
                            ? "line.3.horizontal.decrease.circle.fill"
                            : "line.3.horizontal.decrease.circle"
                    )
                }
                .accessibilityLabel("Filtri e ordinamento elenco")
                Button("Saldi") {
                    movimentiPath.append(MovimentiSchedaRoute.saldi)
                }
                .accessibilityLabel("Saldi")
                Button {
                    Task { @MainActor in
                        await refreshFromToolbarUpdateButton()
                    }
                } label: {
                    if isRefreshingSession {
                        ProgressView()
                            .progressViewStyle(.circular)
                    } else {
                        Image(systemName: "arrow.clockwise")
                    }
                }
                .disabled(isRefreshingSession || isBusy || isManualRefreshSequenceRunning)
                .accessibilityLabel("Aggiorna dati dal file")
            }
        }
        .sheet(isPresented: $showFiltriSheet) {
            NavigationStack(path: $filtriNavigationPath) {
                List {
                    Section {
                        Text(
                            "Mostra solo i movimenti la cui categoria e/o almeno uno dei due conti coincidono con la selezione. " +
                                "Tocca «Categoria» o «Conto» per aprire l’elenco (foglio a scorrimento da basso)."
                        )
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    }
                    Section("Criteri") {
                        Button {
                            filtriNavigationPath.append(MovimentiFiltriPick.category)
                        } label: {
                            LabeledContent("Categoria") {
                                Text(filterCategoryKey.isEmpty ? "Tutte" : filterCategoryKey)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.trailing)
                                    .lineLimit(2)
                            }
                        }
                        .buttonStyle(.plain)

                        Button {
                            filtriNavigationPath.append(MovimentiFiltriPick.account)
                        } label: {
                            LabeledContent("Conto") {
                                Text(filterAccountKey.isEmpty ? "Tutti" : filterAccountKey)
                                    .foregroundStyle(.secondary)
                                    .multilineTextAlignment(.trailing)
                                    .lineLimit(2)
                            }
                        }
                        .buttonStyle(.plain)
                    }
                    Section {
                        Text("Visibili: \(filteredMovimentiRecords.count) di \(loggedInRecords.count)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        if !filterCategoryKey.isEmpty || !filterAccountKey.isEmpty {
                            Button("Reimposta filtri") {
                                filterCategoryKey = ""
                                filterAccountKey = ""
                            }
                        }
                    }
                }
                .onAppear {
                    if !filterCategoryKey.isEmpty, !movimentiCategoryChoices.contains(filterCategoryKey) {
                        filterCategoryKey = ""
                    }
                    if !filterAccountKey.isEmpty, !movimentiAccountChoices.contains(filterAccountKey) {
                        filterAccountKey = ""
                    }
                }
                .navigationTitle("Filtri")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Fine") { showFiltriSheet = false }
                    }
                }
                .navigationDestination(for: MovimentiFiltriPick.self) { pick in
                    switch pick {
                    case .category:
                        MovimentiFilterStringPickView(
                            title: "Categoria",
                            noneLabel: "Tutte",
                            choices: movimentiCategoryChoices,
                            selection: $filterCategoryKey,
                            afterSelect: {
                                if filtriNavigationPath.count > 0 {
                                    filtriNavigationPath.removeLast()
                                }
                            }
                        )
                    case .account:
                        MovimentiFilterStringPickView(
                            title: "Conto",
                            noneLabel: "Tutti",
                            choices: movimentiAccountChoices,
                            selection: $filterAccountKey,
                            afterSelect: {
                                if filtriNavigationPath.count > 0 {
                                    filtriNavigationPath.removeLast()
                                }
                            }
                        )
                    }
                }
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    /// Riga riepilogo sotto la data (filtri attivi + conteggio).
    private var movimentiFiltriSummaryLine: String? {
        var parts: [String] = []
        if let c = activeCategoryFilter {
            parts.append("Categoria: \(c)")
        }
        if let a = activeAccountFilter {
            parts.append("Conto: \(a)")
        }
        let base = parts.joined(separator: " · ")
        if filteredMovimentiRecords.count != loggedInRecords.count || !parts.isEmpty {
            let suffix = " — \(filteredMovimentiRecords.count)/\(loggedInRecords.count)"
            return base.isEmpty ? String(suffix.dropFirst(3)) : base + suffix
        }
        return nil
    }

    private func italianLongToday() -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "it_IT")
        f.dateStyle = .long
        f.timeStyle = .none
        f.timeZone = .current
        return f.string(from: Date())
    }

    private var rowPrimaryText: Color {
        colorScheme == .dark ? .white : Color.primary
    }

    private func amountColor(_ value: Decimal) -> Color {
        if value < .zero { return Color.red }
        if value > .zero { return Color.green }
        return Color.secondary
    }

    private func accountLine(_ row: ContiRecordRow) -> String {
        if row.accountSecondary.isEmpty {
            return row.accountPrimary
        }
        return "\(row.accountPrimary) → \(row.accountSecondary)"
    }

    /// Precompila il campo email con l’ultimo accesso riuscito (non sovrascrive testo già inserito).
    private func applySavedLoginEmailIfNeeded() {
        guard email.isEmpty else { return }
        let saved = ContiLightLastLoginEmail.load()
        if !saved.isEmpty {
            email = saved
        }
    }

    private func loginWithPassword() {
        guard let folder = dataFolderURL else { return }
        let scoped = securityScopedBookmarkURL ?? folder
        guard !isBusy else { return }
        let emailTrim = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let passwordTrim = password.trimmingCharacters(in: .whitespacesAndNewlines)
        email = emailTrim
        password = passwordTrim
        guard !emailTrim.isEmpty, !passwordTrim.isEmpty else { return }

        isBusy = true
        // Poi: lettura/decifratura `*_light.enc`, eventuale attesa file (es. Dropbox) e sync con il .enc completo.
        message = "Attendere un momento, per favore"
        let folderURL = folder

        Task { @MainActor in
            defer { isBusy = false }
            let packet = await runLoginPacket(
                emailTrim: emailTrim,
                passwordTrim: passwordTrim,
                folderURL: folderURL,
                scopedAccessURL: scoped,
                lightEncURLIfKnown: nil
            )
            applyLoginPacket(packet, emailTrim: emailTrim, passwordTrim: passwordTrim)
        }
    }

    /// Accesso con Face ID / Touch ID: recupera la password dal Keychain dopo il prompt biometrico.
    private func loginWithBiometrics() {
        guard let folder = dataFolderURL else { return }
        let scoped = securityScopedBookmarkURL ?? folder
        guard !isBusy else { return }
        let emailTrim = email.trimmingCharacters(in: .whitespacesAndNewlines)
        email = emailTrim
        guard !emailTrim.isEmpty else { return }

        isBusy = true
        message = "Autenticazione…"
        Task { @MainActor in
            defer { isBusy = false }
            let passwordTrim: String
            do {
                passwordTrim = try ContiLightBiometricLogin.loadPasswordUnlockingWithBiometrics(email: emailTrim)
            } catch {
                message = (error as NSError).localizedDescription
                return
            }
            password = passwordTrim
            // Dopo Face ID: lettura/decifratura file, eventuale attesa sincronizzazione (Dropbox) e merge DB.
            message = "Attendere un momento, per favore"
            let packet = await runLoginPacket(
                emailTrim: emailTrim,
                passwordTrim: passwordTrim,
                folderURL: folder,
                scopedAccessURL: scoped,
                lightEncURLIfKnown: nil
            )
            applyLoginPacket(packet, emailTrim: emailTrim, passwordTrim: passwordTrim)
        }
    }

    /// Ricarica silenziosamente il file light dalla cartella (stesso compito del tasto Aggiorna quando `forceReResolveEnc` è attivo).
    /// Default: risolve di nuovo il path `*_light.enc` (Importo allineato al file su disco dopo sync Dropbox / Files).
    private func refreshLightSessionIfLoggedIn(forceReResolveEnc: Bool = true) async {
        guard loggedInSessionDb != nil, let folder = dataFolderURL else { return }
        let scoped = securityScopedBookmarkURL ?? folder
        let emailTrim = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let passwordTrim = password.trimmingCharacters(in: .whitespacesAndNewlines)
        // Niente lettura biometrica qui (eviterebbe prompt a ogni ritorno in primo piano).
        guard !emailTrim.isEmpty, !passwordTrim.isEmpty else { return }
        guard !isBusy, !isRefreshingSession else { return }

        isRefreshingSession = true
        defer { isRefreshingSession = false }

        let encRef: URL?
        if forceReResolveEnc {
            encRef = nil
        } else {
            encRef = sessionLightEncURL
        }

        let packet = await runLoginPacket(
            emailTrim: emailTrim,
            passwordTrim: passwordTrim,
            folderURL: folder,
            scopedAccessURL: scoped,
            lightEncURLIfKnown: encRef,
            skipSessionWorkspaceLock: true
        )
        guard let newDb = packet.sessionDb,
              packet.keyURL != nil,
              packet.lightEncURL != nil else { return }
        loggedInSessionDb = newDb
        if let d = newDb as? [String: Any] {
            loggedInRecords = ContiDatabase.displayRecords(from: d, sort: movimentiListSort)
            movimentiDisplayName = ContiDatabase.displayNameForHeader(db: d, email: emailTrim)
        } else {
            loggedInRecords = packet.records
            movimentiDisplayName = emailTrim
        }
        sessionKeyURL = packet.keyURL
        sessionLightEncURL = packet.lightEncURL
        if let pm = packet.periodicStartupMessage?.trimmingCharacters(in: .whitespacesAndNewlines), !pm.isEmpty {
            periodicStartupAlertText = pm
            periodicStartupAlertPresented = true
        }
        lastScenePhaseRefreshAt = Date()
    }

    private func releaseSessionLockIfOwned() {
        guard let folder = dataFolderURL else {
            ContiDatabase.clearLocalInstanceSessionState()
            return
        }
        let scope = securityScopedBookmarkURL ?? folder
        let access = scope.startAccessingSecurityScopedResource()
        defer {
            if access { scope.stopAccessingSecurityScopedResource() }
        }
        if access {
            ContiDatabase.releaseSessionWorkspaceLockOnClose(in: folder)
        } else {
            ContiDatabase.clearLocalInstanceSessionState()
        }
    }

    private func closeCurrentSessionAndReleaseLock() {
        postLoginHydrationRefreshTask?.cancel()
        postLoginHydrationRefreshTask = nil
        releaseSessionLockIfOwned()
        loggedInSessionDb = nil
        loggedInRecords = []
        movimentiDisplayName = ""
        sessionKeyURL = nil
        sessionLightEncURL = nil
        movimentiPath = NavigationPath()
    }

    /// Carica e decifra il DB in background (come `loginWithPassword`).
    private func runLoginPacket(
        emailTrim: String,
        passwordTrim: String,
        folderURL: URL,
        scopedAccessURL: URL,
        lightEncURLIfKnown: URL?,
        skipSessionWorkspaceLock: Bool = false
    ) async -> LoginResultPacket {
        await withCheckedContinuation { (cont: CheckedContinuation<LoginResultPacket, Never>) in
            DispatchQueue.global(qos: .userInitiated).async {
                let folderAccess = scopedAccessURL.startAccessingSecurityScopedResource()
                defer {
                    if folderAccess {
                        ContiLightFolderBookmark.renew(from: scopedAccessURL)
                        scopedAccessURL.stopAccessingSecurityScopedResource()
                    }
                }
                guard folderAccess else {
                    cont.resume(
                        returning: LoginResultPacket(
                            message: "Impossibile accedere alla cartella (permessi). Scegli di nuovo un file con «Scegli file dati…».",
                            records: [],
                            sessionDb: nil,
                            keyURL: nil,
                            lightEncURL: nil,
                            periodicStartupMessage: nil
                        )
                    )
                    return
                }

                let packet: LoginResultPacket
                if !skipSessionWorkspaceLock {
                    do {
                        try ContiDatabase.assertNoSessionWorkspaceLockBeforeOpen(in: folderURL)
                    } catch {
                        let s = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                        packet = LoginResultPacket(
                            message: s,
                            records: [],
                            sessionDb: nil,
                            keyURL: nil,
                            lightEncURL: nil,
                            periodicStartupMessage: nil
                        )
                        cont.resume(returning: packet)
                        return
                    }
                }
                guard let keyRef = ContiDatabase.preferredKeyFileURL(inFolder: folderURL) else {
                    packet = LoginResultPacket(
                        message: "Nessun file .key nella cartella. Copia qui conti_di_casa.key (stesso del desktop).",
                        records: [],
                        sessionDb: nil,
                        keyURL: nil,
                        lightEncURL: nil,
                        periodicStartupMessage: nil
                    )
                    cont.resume(returning: packet)
                    return
                }
                // Il segnaposto si controlla in ``acquireSessionWorkspaceLockForOpen`` (stesso criteri «materiato»/scrittura).
                let encRef: URL
                if let known = lightEncURLIfKnown {
                    encRef = known
                } else if let resolved = ContiDatabase.resolvePrimaryEncURL(inFolder: folderURL, email: emailTrim) {
                    encRef = resolved
                } else {
                    let stem = ContiDatabase.userEncFilenameStem(forEmail: emailTrim)
                    packet = LoginResultPacket(
                        message: """
                            Nessun file light trovato. Serve solo *_light.enc (mai il database grande).
                            Dal desktop salva e controlla che esista \(stem)_light.enc nella stessa cartella del file .key.
                            """,
                        records: [],
                        sessionDb: nil,
                        keyURL: nil,
                        lightEncURL: nil,
                        periodicStartupMessage: nil
                    )
                    cont.resume(returning: packet)
                    return
                }
                let fullEncURL = ContiDatabase.perUserEncURL(primaryEnc: encRef, email: emailTrim)
                var dropboxWaitPaths: [URL] = [keyRef, encRef]
                if FileManager.default.fileExists(atPath: fullEncURL.path) {
                    dropboxWaitPaths.append(fullEncURL)
                }
                let waited = ContiDatabase.waitForPathsStableIfDropbox(dropboxWaitPaths)
                // Su iOS/Dropbox Files la prima «stabilità» può essere un file ancora non aggiornato dal cloud; breve pausa + seconda passata sull’`.enc`.
                Thread.sleep(forTimeInterval: 0.45)
                let waited2 = ContiDatabase.waitForFileStableIfDropbox(encRef)
                let totalWait = waited + waited2
                let syncWaitNote: String = totalWait >= 1.0
                    ? String(format: "Attesa sincronizzazione Dropbox: %.1fs.", totalWait)
                    : ""

                do {
                    let encData = try ContiDatabase.coordinatedDataContents(of: encRef)
                    let keyString = try ContiDatabase.coordinatedStringContents(of: keyRef, encoding: .utf8)
                    let (db, _) = try ContiDatabase.loadDBForEmail(
                        primaryEncData: encData,
                        keyString: keyString,
                        primaryEncURL: encRef
                    )
                    if ContiDatabase.tryLogin(db: db, email: emailTrim, password: passwordTrim) != nil {
                        if !skipSessionWorkspaceLock {
                            do {
                                try ContiDatabase.acquireSessionWorkspaceLockForOpen(in: folderURL)
                            } catch {
                                let s = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                                packet = LoginResultPacket(
                                    message: s,
                                    records: [],
                                    sessionDb: nil,
                                    keyURL: nil,
                                    lightEncURL: nil,
                                    periodicStartupMessage: nil
                                )
                                cont.resume(returning: packet)
                                return
                            }
                        }
                        // Login/refresh in sola lettura: nessuna riscrittura dei `.enc` in questa fase.
                        // Le scritture restano solo nelle azioni esplicite utente (nuova immissione/modifica/annullamento).
                        let sessionDb: [String: Any] = db
                        let periodicStartupMessage: String? = nil
                        let rows = ContiDatabase.displayRecords(from: sessionDb)
                        let baseMsg = rows.isEmpty
                            ? "Accesso effettuato. Nessun movimento nel file light."
                            : "Accesso effettuato."
                        var notes: [String] = []
                        if !syncWaitNote.isEmpty { notes.append(syncWaitNote) }
                        let msgOut = notes.isEmpty ? baseMsg : baseMsg + "\n\n" + notes.joined(separator: "\n")
                        packet = LoginResultPacket(
                            message: msgOut,
                            records: rows,
                            sessionDb: sessionDb as NSDictionary,
                            keyURL: keyRef,
                            lightEncURL: encRef,
                            periodicStartupMessage: periodicStartupMessage
                        )
                    } else {
                        packet = LoginResultPacket(
                            message: "Accesso negato (email/password o profilo non valido).",
                            records: [],
                            sessionDb: nil,
                            keyURL: nil,
                            lightEncURL: nil,
                            periodicStartupMessage: nil
                        )
                    }
                } catch {
                    let msg: String
                    if let ce = error as? ContiDBError {
                        msg = ce.localizedDescription
                    } else {
                        msg = "Lettura file o elaborazione: \(error.localizedDescription)"
                    }
                    packet = LoginResultPacket(
                        message: msg,
                        records: [],
                        sessionDb: nil,
                        keyURL: nil,
                        lightEncURL: nil,
                        periodicStartupMessage: nil
                    )
                }
                cont.resume(returning: packet)
            }
        }
    }

    private func applyLoginPacket(_ packet: LoginResultPacket, emailTrim: String, passwordTrim: String) {
        var msg = packet.message
        if packet.sessionDb != nil {
            ContiLightLastLoginEmail.save(emailTrim)
            if savePasswordForBiometrics, ContiLightBiometricLogin.biometricsAvailable() {
                do {
                    try ContiLightBiometricLogin.savePasswordForBiometricUnlock(
                        email: emailTrim,
                        password: passwordTrim
                    )
                } catch {
                    msg += "\n\n\(ContiLightBiometricLogin.biometricLabel()): non salvato — \(error.localizedDescription)"
                }
            } else {
                ContiLightBiometricLogin.deletePassword(forEmail: emailTrim)
            }
        }
        message = msg
        if let dbObj = packet.sessionDb {
            // Evita che `.active` immediato dopo il login lanci una seconda lettura in concorrenza col Task ritardato sotto.
            lastScenePhaseRefreshAt = Date()
            movimentiPath = NavigationPath()
            filterCategoryKey = ""
            filterAccountKey = ""
            loggedInSessionDb = dbObj
            sessionKeyURL = packet.keyURL
            sessionLightEncURL = packet.lightEncURL
            if let d = dbObj as? [String: Any] {
                loggedInRecords = ContiDatabase.displayRecords(from: d, sort: movimentiListSort)
                movimentiDisplayName = ContiDatabase.displayNameForHeader(db: d, email: emailTrim)
            } else {
                loggedInRecords = packet.records
                movimentiDisplayName = emailTrim
            }
            if let pm = packet.periodicStartupMessage?.trimmingCharacters(in: .whitespacesAndNewlines), !pm.isEmpty {
                periodicStartupAlertText = pm
                periodicStartupAlertPresented = true
            }
            schedulePostLoginHydrationRefreshes()
        } else {
            closeCurrentSessionAndReleaseLock()
        }
    }

    /// Alcuni provider (Dropbox/Files) consegnano inizialmente una copia locale non ancora aggiornata.
    /// Esegue più refresh ritardati dopo login, evitando il requisito pratico di chiudere/riaprire l'app.
    private func schedulePostLoginHydrationRefreshes() {
        postLoginHydrationRefreshTask?.cancel()
        postLoginHydrationRefreshTask = Task { @MainActor in
            let delaysNs: [UInt64] = [
                4_000_000_000,   // conferma rapida
                10_000_000_000,  // coda tipica provider
                20_000_000_000,  // casi lenti
            ]
            for delay in delaysNs {
                if Task.isCancelled { return }
                try? await Task.sleep(nanoseconds: delay)
                if Task.isCancelled { return }
                await refreshLightSessionIfLoggedIn(forceReResolveEnc: true)
            }
        }
    }

    /// Handler del tasto Aggiorna: doppio refresh per mitigare cache/file-provider non ancora idratato.
    private func refreshFromToolbarUpdateButton() async {
        guard !isManualRefreshSequenceRunning else { return }
        isManualRefreshSequenceRunning = true
        defer { isManualRefreshSequenceRunning = false }
        await refreshLightSessionIfLoggedIn(forceReResolveEnc: true)
        // Seconda passata ravvicinata: spesso Dropbox/Files materializza il blob aggiornato poco dopo.
        try? await Task.sleep(nanoseconds: 1_300_000_000)
        await refreshLightSessionIfLoggedIn(forceReResolveEnc: true)
    }
}

/// Esito login dal thread in background; `sessionDb` solo se autenticazione riuscita (per saldi / immissioni future).
private struct LoginResultPacket: @unchecked Sendable {
    let message: String
    let records: [ContiRecordRow]
    let sessionDb: NSDictionary?
    let keyURL: URL?
    let lightEncURL: URL?
    /// Testo lungo per alert (solo se sono state create occorrenze periodiche).
    let periodicStartupMessage: String?
}

private struct DataFilePickRequest: Identifiable, Hashable {
    let id = UUID()
}

private struct FolderPickRequest: Identifiable, Hashable {
    let id = UUID()
}

// MARK: - Document picker cartella

private struct DocumentFolderPickerRepresentable: UIViewControllerRepresentable {
    var onPick: (URL) -> Void
    var onCancel: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onPick: onPick, onCancel: onCancel)
    }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder], asCopy: false)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        picker.modalPresentationStyle = .formSheet
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        let onCancel: () -> Void
        private var callbackAlreadySent = false

        init(onPick: @escaping (URL) -> Void, onCancel: @escaping () -> Void) {
            self.onPick = onPick
            self.onCancel = onCancel
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard !callbackAlreadySent else { return }
            callbackAlreadySent = true
            guard let u = urls.first else {
                DispatchQueue.main.async { self.onCancel() }
                return
            }
            DispatchQueue.main.async {
                self.onPick(u)
            }
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            guard !callbackAlreadySent else { return }
            callbackAlreadySent = true
            DispatchQueue.main.async {
                self.onCancel()
            }
        }
    }
}

// MARK: - Document picker file dati (fallback: un file; la cartella è preferita)

private struct DocumentDataFilePickerRepresentable: UIViewControllerRepresentable {
    var onPick: (URL) -> Void
    var onCancel: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onPick: onPick, onCancel: onCancel)
    }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.data], asCopy: false)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        picker.modalPresentationStyle = .formSheet
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        let onCancel: () -> Void
        private var callbackAlreadySent = false

        init(onPick: @escaping (URL) -> Void, onCancel: @escaping () -> Void) {
            self.onPick = onPick
            self.onCancel = onCancel
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard !callbackAlreadySent else { return }
            callbackAlreadySent = true
            guard let u = urls.first else {
                DispatchQueue.main.async { self.onCancel() }
                return
            }
            DispatchQueue.main.async {
                self.onPick(u)
            }
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            guard !callbackAlreadySent else { return }
            callbackAlreadySent = true
            DispatchQueue.main.async {
                self.onCancel()
            }
        }
    }
}

#Preview {
    ContentView()
}
