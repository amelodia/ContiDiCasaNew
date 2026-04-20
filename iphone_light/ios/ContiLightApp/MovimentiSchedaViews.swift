import SwiftUI
import UIKit

/// Destinazioni push da Movimenti (stile schede desktop, non sheet modali).
enum MovimentiSchedaRoute: Hashable {
    case saldi
    case nuoviDati
}

// MARK: - Filtri: lista con tap immediato (evita Picker «a tendina» lento in Form)

struct MovimentiFilterStringPickView: View {
    let title: String
    let noneLabel: String
    let choices: [String]
    @Binding var selection: String
    /// Se valorizzato, viene chiamato al posto di `dismiss()` (es. `pop` nello stack filtri).
    var afterSelect: (() -> Void)?

    @Environment(\.dismiss) private var dismiss

    /// Init esplicito: con `@Environment` l’inizializzatore sintetizzato può omettere `afterSelect` e dare «Extra argument» a compile time.
    init(
        title: String,
        noneLabel: String,
        choices: [String],
        selection: Binding<String>,
        afterSelect: (() -> Void)? = nil
    ) {
        self.title = title
        self.noneLabel = noneLabel
        self.choices = choices
        self._selection = selection
        self.afterSelect = afterSelect
    }

    var body: some View {
        ContiLightUIKitStringPickRepresentable(
            title: title,
            noneLabel: noneLabel,
            choices: choices,
            selection: $selection,
            afterSelect: afterSelect ?? { dismiss() }
        )
    }
}

// MARK: - Saldi

struct ContiLightSaldiSchedaView: View {
    /// `NSDictionary` dal login o dizionario Swift: il core normalizza i tipi annidati.
    let sessionDb: Any?

    private var rows: [ContiSaldRiga] {
        ContiDatabase.saldiDueForme(sessionDb: sessionDb, todayIso: ContiDatabase.todayIsoLocal())
    }

    /// Totali «non carta» come nel footer desktop (se presenti nel JSON light).
    private var totalsNonCc: (abs: Decimal, sf: Decimal, scc: Decimal, disp: Decimal)? {
        ContiDatabase.lightSaldiTotalsNonCc(sessionDb: sessionDb)
    }

    private var saldiIntroText: String {
        if let meta = ContiDatabase.lightSaldiSnapshotMeta(sessionDb: sessionDb) {
            return """
            Stessi importi della pagina Saldi del desktop (incluse colonne legate alle carte di credito). \
            Nessuna funzione di verifica su iPhone. \
            Riferimento \(meta.dateIso), anno piano \(meta.yearBasis). \
            Dopo immissioni su iOS, al salvataggio si aggiornano in locale; salva sul desktop per rigenerare il light.
            """
        }
        return "Dati mancanti: nel file non c’è il blocco «light_saldi». Rigenera il file *_light.enc dal desktop (salvataggio app desktop)."
    }

    private var sommaAssoluti: Decimal {
        if let t = totalsNonCc { return t.abs }
        return rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.saldoAssoluto }
    }

    private var sommaAllaData: Decimal {
        rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.saldoOggi }
    }

    var body: some View {
        List {
            Section {
                Text(saldiIntroText)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            if rows.isEmpty {
                Section {
                    ContentUnavailableView(
                        sessionDb == nil ? "Sessione assente" : "Dati mancanti",
                        systemImage: "exclamationmark.triangle",
                        description: Text(
                            sessionDb == nil
                                ? "Sessione dati assente. Esci e accedi di nuovo."
                                : ContiDatabase.lightSaldiSnapshotMeta(sessionDb: sessionDb) == nil
                                    ? "Il file light non contiene «light_saldi» (saldi calcolati sul database completo). Salva sul desktop per rigenerare il file *_light.enc nella cartella dati."
                                    : "Lo snapshot «light_saldi» non ha righe valide. Rigenera il file light dal desktop."
                        )
                    )
                    .frame(minHeight: 120)
                }
            } else {
                Section("Totali (conti non carta)") {
                    HStack {
                        Text("Somma saldi assoluti")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaAssoluti))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaAssoluti))
                    }
                    .font(.subheadline.weight(.medium))
                    HStack {
                        Text("Somma saldi alla data")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaAllaData))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaAllaData))
                    }
                    .font(.subheadline.weight(.medium))
                    if let t = totalsNonCc {
                        HStack {
                            Text("Di cui, spese future (non carta)")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(ContiDatabase.formatEuroTwoDecimals(t.sf))
                                .monospacedDigit()
                                .foregroundStyle(amountColor(t.sf))
                        }
                        .font(.subheadline.weight(.medium))
                        HStack {
                            Text("Spese per carte (colonne conti)")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(ContiDatabase.formatEuroTwoDecimals(t.scc))
                                .monospacedDigit()
                                .foregroundStyle(amountColor(t.scc))
                        }
                        .font(.subheadline.weight(.medium))
                        HStack {
                            Text("Disponibilità (somma)")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text(ContiDatabase.formatEuroTwoDecimals(t.disp))
                                .monospacedDigit()
                                .foregroundStyle(amountColor(t.disp))
                        }
                        .font(.subheadline.weight(.medium))
                    }
                    Text("Le carte non entrano nella somma «assoluti» (come sul desktop). Disponibilità = saldo assoluto + spese CC (la riga spese future non entra nel totale). Sulle colonne carta: —.")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Section {
                    ForEach(rows) { r in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(alignment: .firstTextBaseline) {
                                Text(r.accountName)
                                    .font(.subheadline.weight(.semibold))
                                if r.isCreditCard {
                                    Text("Carta")
                                        .font(.caption2)
                                        .padding(.horizontal, 6)
                                        .padding(.vertical, 2)
                                        .background(Color.blue.opacity(0.15))
                                        .clipShape(Capsule())
                                }
                            }
                            HStack {
                                Text("Assoluto")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(ContiDatabase.formatEuroTwoDecimals(r.saldoAssoluto))
                                    .monospacedDigit()
                                    .foregroundStyle(amountColor(r.saldoAssoluto))
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Alla data")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(ContiDatabase.formatEuroTwoDecimals(r.saldoOggi))
                                    .monospacedDigit()
                                    .foregroundStyle(amountColor(r.saldoOggi))
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Di cui, spese future")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                if r.isCreditCard {
                                    Text("—")
                                        .foregroundStyle(.tertiary)
                                } else {
                                    Text(ContiDatabase.formatEuroTwoDecimals(r.speseFuture))
                                        .monospacedDigit()
                                        .foregroundStyle(amountColor(r.speseFuture))
                                }
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Spese CC")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                if r.isCreditCard {
                                    Text("—")
                                        .foregroundStyle(.tertiary)
                                } else {
                                    Text(ContiDatabase.formatEuroTwoDecimals(r.speseCC))
                                        .monospacedDigit()
                                        .foregroundStyle(amountColor(r.speseCC))
                                }
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Disponibilità")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                if r.isCreditCard {
                                    Text("—")
                                        .foregroundStyle(.tertiary)
                                } else {
                                    Text(ContiDatabase.formatEuroTwoDecimals(r.disponibilita))
                                        .monospacedDigit()
                                        .foregroundStyle(amountColor(r.disponibilita))
                                }
                            }
                            .font(.subheadline)
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
        }
        .navigationTitle("Saldi")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func amountColor(_ value: Decimal) -> Color {
        if value < .zero { return Color.red }
        if value > .zero { return Color.green }
        return Color.secondary
    }
}

// MARK: - Nuove registrazioni (layout tipo desktop; senza memoria/saldo cassa, v. LIGHT_UI_SPEC)

private struct ImmissioneCodePickView: View {
    let title: String
    let rows: [(code: String, label: String, subtitle: String?)]
    let includeNone: Bool
    let noneLabel: String
    @Binding var selectedCode: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ContiLightUIKitCodePickRepresentable(
            title: title,
            rowItems: rows,
            includeNone: includeNone,
            noneLabel: noneLabel,
            selectedCode: $selectedCode,
            afterSelect: { dismiss() }
        )
    }
}

struct ContiLightNuovoMovimentoSchedaView: View {
    let sessionDb: [String: Any]?
    let dataFolderURL: URL?
    let keyURL: URL?
    let lightEncURL: URL?
    let email: String
    let password: String
    let onPersisted: ([String: Any], [ContiRecordRow], String) -> Void

    @State private var dateText = ""
    @State private var catCode = ""
    @State private var acc1Code = ""
    @State private var acc2Code = ""
    @State private var amountText = ""
    @State private var chequeText = ""
    @State private var noteText = ""
    @State private var isSaving = false
    @State private var showSaveConfirmDialog = false
    @State private var showVirtualeSecondConfirm = false
    @State private var commitPreviewLine = ""
    @State private var pendingLightRecordId = ""
    @State private var showErrorAlert = false
    @State private var errorAlertMessage = ""
    @State private var showSuccessAlert = false
    @State private var successAlertMessage = ""
    @State private var pickedDate: Date = Date()
    @State private var didRunInitialDefaults = false
    @FocusState private var focusedField: ImmissioneField?

    private enum ImmissioneField: Hashable {
        case amount
        case cheque
        case note
    }

    private var lists: (categorie: [ContiImmissioneCategoria], conti: [ContiImmissioneConto])? {
        guard let db = sessionDb else { return nil }
        return ContiDatabase.immissionePickLists(from: db)
    }

    private var catRows: [(code: String, label: String, subtitle: String?)] {
        (lists?.categorie ?? []).map { ($0.code, $0.displayName, nil) }
    }

    private var accRows: [(code: String, label: String, subtitle: String?)] {
        (lists?.conti ?? []).map { c in
            let sub: String?
            if c.isCreditCard {
                sub = c.referenceAccountName.isEmpty
                    ? "Carta di credito"
                    : "Carta · riferimento: \(c.referenceAccountName)"
            } else {
                sub = nil
            }
            return (c.code, c.name, sub)
        }
    }

    private var selectedCatNote: String {
        lists?.categorie.first { $0.code == catCode }?.planNote ?? "—"
    }

    private var catLabel: String {
        lists?.categorie.first { $0.code == catCode }?.displayName ?? "—"
    }

    private var acc1Row: ContiImmissioneConto? {
        lists?.conti.first { $0.code == acc1Code }
    }

    private var acc1Label: String {
        acc1Row?.name ?? "—"
    }

    private var acc1IsCassa: Bool {
        acc1Row?.name.trimmingCharacters(in: .whitespacesAndNewlines).localizedCaseInsensitiveCompare("cassa") == .orderedSame
    }

    private var acc1IsVirtuale: Bool {
        acc1Row?.name.trimmingCharacters(in: .whitespacesAndNewlines).localizedCaseInsensitiveCompare("virtuale") == .orderedSame
    }

    private var acc1IsCreditCard: Bool {
        acc1Row?.isCreditCard == true
    }

    /// Carta: niente campo assegno in UI; valore fisso «ccarta» (come desktop).
    private var showAssegnoSection: Bool {
        !acc1IsCassa && !acc1IsVirtuale && !acc1IsCreditCard
    }

    private var girataSelected: Bool {
        guard let c = lists?.categorie.first(where: { $0.code == catCode }) else { return false }
        return ContiDatabase.isGirataContoContoDisplayName(c.displayName)
    }

    private var acc2Row: ContiImmissioneConto? {
        lists?.conti.first { $0.code == acc2Code }
    }

    private var hasVirtualeInGirataPair: Bool {
        guard girataSelected else { return false }
        let n1 = acc1Row?.name.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let n2 = acc2Row?.name.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return n1.localizedCaseInsensitiveCompare("virtuale") == .orderedSame
            || n2.localizedCaseInsensitiveCompare("virtuale") == .orderedSame
    }

    private var acc2Label: String {
        if acc2Code.isEmpty { return "—" }
        return lists?.conti.first { $0.code == acc2Code }?.name ?? "—"
    }

    /// Richiede doppia conferma come sul desktop (conto Virtuale in prima o in girata).
    private var virtualeInvolved: Bool {
        acc1IsVirtuale || hasVirtualeInGirataPair
    }

    private var immissioneDateClosedRange: ClosedRange<Date> {
        let b = ContiDatabase.immissioneDateBoundsIso()
        let lo = ContiDatabase.dateFromIsoCalendarLocal(b.minIso) ?? Date.distantPast
        let hi = ContiDatabase.dateFromIsoCalendarLocal(b.maxIso) ?? Date.distantFuture
        return lo...hi
    }

    private var formReadyForSave: Bool {
        !catCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !acc1Code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && ContiDatabase.lightImmissioneAmountIsValidNonZero(amountText: amountText, girataSelected: girataSelected)
    }

    var body: some View {
        Group {
            if lists == nil {
                ContentUnavailableView(
                    "Dati non disponibili",
                    systemImage: "tray",
                    description: Text("Apri di nuovo la sessione o verifica il file light.")
                )
            } else {
                Form {
                    Section {
                        NavigationLink {
                            ImmissioneCodePickView(
                                title: "Categoria",
                                rows: catRows,
                                includeNone: false,
                                noneLabel: "",
                                selectedCode: $catCode
                            )
                        } label: {
                            LabeledContent("Categoria", value: catLabel)
                        }
                        .disabled(catRows.isEmpty)

                        Text(selectedCatNote)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Section {
                        DatePicker(
                            "Data",
                            selection: $pickedDate,
                            in: immissioneDateClosedRange,
                            displayedComponents: [.date]
                        )
                        .datePickerStyle(.graphical)
                        Button("Oggi") {
                            var cal = Calendar(identifier: .gregorian)
                            cal.timeZone = .current
                            let t = cal.startOfDay(for: Date())
                            let r = immissioneDateClosedRange
                            pickedDate = min(max(t, r.lowerBound), r.upperBound)
                        }
                    }
                    Section {
                        NavigationLink {
                            ImmissioneCodePickView(
                                title: "Conto",
                                rows: accRows,
                                includeNone: false,
                                noneLabel: "",
                                selectedCode: $acc1Code
                            )
                        } label: {
                            LabeledContent("Conto", value: acc1Label)
                        }
                        .disabled(accRows.isEmpty)

                        if girataSelected {
                            NavigationLink {
                                ImmissioneCodePickView(
                                    title: "Secondo conto",
                                    rows: accRows,
                                    includeNone: true,
                                    noneLabel: "Nessuno",
                                    selectedCode: $acc2Code
                                )
                            } label: {
                                LabeledContent("Secondo conto", value: acc2Label)
                            }
                            .disabled(accRows.isEmpty)
                        }
                    }
                    Section {
                        LabeledContent("Importo (€)") {
                            TextField("0,00", text: $amountText)
                                .keyboardType(.decimalPad)
                                .multilineTextAlignment(.trailing)
                                .focused($focusedField, equals: .amount)
                        }
                        HStack {
                            Spacer()
                            Button("+") { prependSign("+") }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 6)
                                .background(Color(uiColor: .systemTeal).opacity(0.2))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                            Button("−") { prependSign("-") }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 6)
                                .background(Color.red.opacity(0.12))
                                .clipShape(RoundedRectangle(cornerRadius: 8))
                        }
                    }
                    if showAssegnoSection {
                        Section {
                            LabeledContent("Assegno") {
                                TextField("—", text: $chequeText)
                                    .textInputAutocapitalization(.characters)
                                    .focused($focusedField, equals: .cheque)
                                    .onSubmit { focusedField = .note }
                            }
                        }
                    }
                    Section {
                        LabeledContent("Nota") {
                            TextField("Nota registrazione", text: $noteText)
                                .focused($focusedField, equals: .note)
                        }
                    }
                    Section {
                        Button("Conferma immissione") {
                            prepareCommitDialog()
                        }
                        .frame(maxWidth: .infinity)
                        .disabled(isSaving || !canAttemptSave || !formReadyForSave)
                        Button("Cancella valori", role: .destructive) {
                            clearForm()
                        }
                        .frame(maxWidth: .infinity)
                        .disabled(isSaving)
                    }
                }
            }
        }
        .overlay {
            if isSaving {
                ZStack {
                    Color.black.opacity(0.2).ignoresSafeArea()
                    ProgressView("Salvataggio…")
                        .padding(24)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
                }
            }
        }
        .navigationTitle("Nuove registrazioni")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if !didRunInitialDefaults {
                didRunInitialDefaults = true
                applyDefaultCategoryAccountAndDate()
            }
            syncChequeFromAcc1()
            applyGiroDefaultNoteIfNeeded()
        }
        .onChange(of: pickedDate) { _, d in
            dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(d))
        }
        .onChange(of: amountText) { _, newVal in
            guard focusedField == .amount else { return }
            if amountFractionHasAtLeastTwoDecimalDigits(newVal) {
                dismissNumericKeyboard()
                focusedField = showAssegnoSection ? .cheque : .note
            }
        }
        .onChange(of: catCode) { _, newVal in
            if let c = lists?.categorie.first(where: { $0.code == newVal }) {
                let isG = ContiDatabase.isGirataContoContoDisplayName(c.displayName)
                if !isG {
                    if noteText.trimmingCharacters(in: .whitespacesAndNewlines) == "Giroconto" {
                        noteText = ""
                    }
                    acc2Code = ""
                } else {
                    let n = noteText.trimmingCharacters(in: .whitespacesAndNewlines)
                    if hasVirtualeInGirataPair {
                        if n == "Giroconto" { noteText = "" }
                    } else if n.isEmpty || n == "-" {
                        noteText = "Giroconto"
                    }
                }
            } else {
                acc2Code = ""
            }
            syncChequeFromAcc1()
        }
        .onChange(of: acc1Code) { _, _ in
            syncChequeFromAcc1()
        }
        .onChange(of: acc2Code) { _, _ in
            guard girataSelected else { return }
            if hasVirtualeInGirataPair, noteText.trimmingCharacters(in: .whitespacesAndNewlines) == "Giroconto" {
                noteText = ""
            }
        }
        .confirmationDialog("Confermare l’inserimento?", isPresented: $showSaveConfirmDialog, titleVisibility: .visible) {
            Button("Annulla", role: .cancel) {}
            Button("Inserisci") {
                if virtualeInvolved {
                    showVirtualeSecondConfirm = true
                } else {
                    performSave()
                }
            }
        } message: {
            Text(commitPreviewLine)
        }
        .alert("Registrazione con conto Virtuale", isPresented: $showVirtualeSecondConfirm) {
            Button("Annulla", role: .cancel) {}
            Button("Inserisci comunque", role: .destructive) {
                performSave()
            }
        } message: {
            Text(
                "Le registrazioni che coinvolgono il conto Virtuale non sono modificabili né eliminabili dal desktop. " +
                    "Controlla bene i dati prima di proseguire."
            )
        }
        .alert("Impossibile salvare", isPresented: $showErrorAlert) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(errorAlertMessage)
        }
        .alert("Salvataggio completato", isPresented: $showSuccessAlert) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(successAlertMessage)
        }
    }

    private var canAttemptSave: Bool {
        dataFolderURL != nil && keyURL != nil && lightEncURL != nil
    }

    private func prepareCommitDialog() {
        guard let db = sessionDb else {
            errorAlertMessage = "Sessione dati assente."
            showErrorAlert = true
            return
        }
        guard let k = keyURL, let e = lightEncURL, dataFolderURL != nil else {
            errorAlertMessage = "Percorsi file non disponibili. Esci dall’area Movimenti e accedi di nuovo."
            showErrorAlert = true
            return
        }
        _ = k
        _ = e
        dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(pickedDate))
        pendingLightRecordId = UUID().uuidString
        do {
            let tpl = try ContiDatabase.buildNewLightRecordTemplate(
                db: db,
                catCode: catCode,
                acc1Code: acc1Code,
                acc2Code: acc2Code,
                dateText: dateText,
                amountText: amountText,
                chequeText: chequeText,
                noteText: noteText,
                lightRecordId: pendingLightRecordId
            )
            commitPreviewLine = commitPreview(from: tpl)
            showSaveConfirmDialog = true
        } catch {
            errorAlertMessage = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            showErrorAlert = true
        }
    }

    private func commitPreview(from rec: [String: Any]) -> String {
        let isoHead = String((rec["date_iso"] as? String ?? "").prefix(10))
        let d = ContiDatabase.italianDateDisplayFromIso(isoHead.isEmpty ? ContiDatabase.todayIsoLocal() : isoHead)
        let cat = catLabel
        let a1 = acc1Label
        let a2 = girataSelected ? acc2Label : ""
        let amt = (rec["amount_eur"] as? String) ?? amountText
        var lines = ["Data \(d), \(cat), \(a1)"]
        if girataSelected, !a2.isEmpty, a2 != "—" { lines[0] += ", \(a2)" }
        lines.append("Importo (JSON): \(amt) EUR")
        lines.append("La registrazione sarà scritta nei file cifrati nella cartella dati (Dropbox / File).")
        return lines.joined(separator: "\n")
    }

    private func performSave() {
        guard let db = sessionDb, let folder = dataFolderURL, let k = keyURL, let e = lightEncURL else {
            errorAlertMessage = "Percorsi di salvataggio non disponibili."
            showErrorAlert = true
            return
        }
        dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(pickedDate))
        let rid = pendingLightRecordId.isEmpty ? UUID().uuidString : pendingLightRecordId
        pendingLightRecordId = rid
        let emailTrim = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let passwordTrim = password.trimmingCharacters(in: .whitespacesAndNewlines)
        isSaving = true
        DispatchQueue.global(qos: .userInitiated).async {
            let access = folder.startAccessingSecurityScopedResource()
            defer {
                if access {
                    folder.stopAccessingSecurityScopedResource()
                }
            }
            let result: Result<(sessionLight: [String: Any], note: String), Error> = {
                guard access else {
                    return .failure(ContiLightImmissioneError.message("Impossibile accedere in scrittura alla cartella dati (permessi)."))
                }
                do {
                    let tpl = try ContiDatabase.buildNewLightRecordTemplate(
                        db: db,
                        catCode: catCode,
                        acc1Code: acc1Code,
                        acc2Code: acc2Code,
                        dateText: dateText,
                        amountText: amountText,
                        chequeText: chequeText,
                        noteText: noteText,
                        lightRecordId: rid
                    )
                    var working = try ContiDatabase.deepCopyDb(db)
                    let appended = try ContiDatabase.appendLightSessionRecord(db: &working, recordTemplate: tpl)
                    let out = try ContiDatabase.persistSessionDbToEncryptedFiles(
                        sessionDb: working,
                        recordForSaldi: appended,
                        lightEncURL: e,
                        keyURL: k,
                        email: emailTrim,
                        password: passwordTrim
                    )
                    return .success((out.sessionLight, out.note))
                } catch {
                    return .failure(error)
                }
            }()
            DispatchQueue.main.async {
                isSaving = false
                switch result {
                case .success(let pair):
                    let rows = ContiDatabase.displayRecords(from: pair.sessionLight)
                    onPersisted(pair.sessionLight, rows, pair.note)
                    successAlertMessage = pair.note
                    showSuccessAlert = true
                    clearForm()
                case .failure(let err):
                    if let ce = err as? ContiLightImmissioneError, case .message(let s) = ce {
                        errorAlertMessage = s
                    } else if let le = err as? LocalizedError, let d = le.errorDescription {
                        errorAlertMessage = d
                    } else {
                        errorAlertMessage = err.localizedDescription
                    }
                    showErrorAlert = true
                }
            }
        }
    }

    private func prependSign(_ sign: String) {
        var s = amountText.trimmingCharacters(in: .whitespacesAndNewlines)
        if let f = s.first, f == "+" || f == "-" || f == "−" {
            s.removeFirst()
        }
        amountText = sign + s
    }

    private func clearForm() {
        acc2Code = ""
        amountText = ""
        chequeText = ""
        noteText = ""
        applyDefaultCategoryAccountAndDate()
        syncChequeFromAcc1()
        applyGiroDefaultNoteIfNeeded()
        focusedField = nil
    }

    private func applyDefaultCategoryAccountAndDate() {
        let r = immissioneDateClosedRange
        let todayIso = ContiDatabase.todayIsoLocal()
        if let d = ContiDatabase.dateFromIsoCalendarLocal(todayIso) {
            pickedDate = min(max(d, r.lowerBound), r.upperBound)
        } else {
            pickedDate = min(max(Date(), r.lowerBound), r.upperBound)
        }
        dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(pickedDate))
        guard let L = lists else { return }
        if let c = L.categorie.first(where: { ContiDatabase.normalizedCategorySortKey($0.displayName).contains("consumi ordinari") }) {
            catCode = c.code
        }
        if let a = L.conti.first(where: { $0.name.trimmingCharacters(in: .whitespacesAndNewlines).localizedCaseInsensitiveCompare("cassa") == .orderedSame }) {
            acc1Code = a.code
        }
    }

    private func dismissNumericKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    private func amountFractionHasAtLeastTwoDecimalDigits(_ raw: String) -> Bool {
        var t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let f = t.first, "+-−".contains(f) {
            t.removeFirst()
        }
        guard let idx = t.lastIndex(where: { $0 == "," || $0 == "." }) else { return false }
        let frac = t[t.index(after: idx)...]
        guard !frac.isEmpty else { return false }
        guard frac.unicodeScalars.allSatisfy({ CharacterSet.decimalDigits.contains($0) }) else { return false }
        return frac.count >= 2
    }

    /// Allineato al desktop: carta → «ccarta» senza campo; Cassa/Virtuale → vuoto.
    private func syncChequeFromAcc1() {
        if acc1IsCreditCard {
            chequeText = "ccarta"
        } else if acc1IsCassa || acc1IsVirtuale {
            chequeText = ""
        } else if chequeText.trimmingCharacters(in: .whitespacesAndNewlines).localizedCaseInsensitiveCompare("ccarta") == .orderedSame {
            chequeText = ""
        }
    }

    private func applyGiroDefaultNoteIfNeeded() {
        guard girataSelected else { return }
        if hasVirtualeInGirataPair {
            if noteText.trimmingCharacters(in: .whitespacesAndNewlines) == "Giroconto" {
                noteText = ""
            }
            return
        }
        let n = noteText.trimmingCharacters(in: .whitespacesAndNewlines)
        if n.isEmpty || n == "-" {
            noteText = "Giroconto"
        }
    }
}
