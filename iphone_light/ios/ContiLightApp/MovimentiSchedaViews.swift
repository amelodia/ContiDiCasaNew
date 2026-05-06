import SwiftUI
import UIKit

/// Destinazioni push da Movimenti (stile schede desktop, non sheet modali).
enum MovimentiSchedaRoute: Hashable {
    case saldi
    case nuoviDati
    case modifica(legacyKey: String)
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
    private var totalsNonCc: (abs: Decimal, sf: Decimal, day: Decimal, scc: Decimal, disp: Decimal)? {
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

    private var sommaDisponibilitaOggi: Decimal {
        if let t = totalsNonCc { return t.day }
        return rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.saldoOggi }
    }

    private var sommaImpegniFuturi: Decimal {
        if let t = totalsNonCc { return t.sf }
        return rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.speseFuture }
    }

    private var sommaImpegniCarte: Decimal {
        if let t = totalsNonCc { return t.scc }
        return rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.speseCC }
    }

    private var sommaDisponibilitaAssoluta: Decimal {
        if let t = totalsNonCc { return t.disp }
        return rows.filter { !$0.isCreditCard }.reduce(Decimal.zero) { $0 + $1.disponibilita }
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
                        Text("Saldi assoluti")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaAssoluti))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaAssoluti))
                    }
                    .font(.subheadline.weight(.medium))
                    HStack {
                        Text("Di cui, impegni futuri")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaImpegniFuturi))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaImpegniFuturi))
                    }
                    .font(.subheadline.weight(.medium))
                    HStack {
                        Text("Disponibilità oggi")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaDisponibilitaOggi))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaDisponibilitaOggi))
                    }
                    .font(.subheadline.weight(.medium))
                    HStack {
                        Text("Impegni per carte")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaImpegniCarte))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaImpegniCarte))
                    }
                    .font(.subheadline.weight(.medium))
                    HStack {
                        Text("Disponibilità assoluta")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(ContiDatabase.formatEuroTwoDecimals(sommaDisponibilitaAssoluta))
                            .monospacedDigit()
                            .foregroundStyle(amountColor(sommaDisponibilitaAssoluta))
                    }
                    .font(.subheadline.weight(.medium))
                    Text("Le carte non entrano nella somma dei non-carta (come sul desktop). Disponibilità oggi = saldi assoluti - impegni futuri. Disponibilità assoluta = saldi assoluti + impegni per carte. Sulle colonne carta: —.")
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
                                Text("Saldi assoluti")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(ContiDatabase.formatEuroTwoDecimals(r.saldoAssoluto))
                                    .monospacedDigit()
                                    .foregroundStyle(amountColor(r.saldoAssoluto))
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Di cui, impegni futuri")
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
                                Text("Disponibilità oggi")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                if r.isCreditCard {
                                    Text("—")
                                        .foregroundStyle(.tertiary)
                                } else {
                                    Text(ContiDatabase.formatEuroTwoDecimals(r.saldoOggi))
                                        .monospacedDigit()
                                        .foregroundStyle(amountColor(r.saldoOggi))
                                }
                            }
                            .font(.subheadline)
                            HStack {
                                Text("Impegni per carte")
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
                                Text("Disponibilità assoluta")
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

// MARK: - Campo importo € (decimal pad + logica allineata al desktop: segno, virgola, 2 decimali, formattazione in uscita)

private struct ContiLightEuroAmountField: UIViewRepresentable {
    @Binding var text: String
    var girataSelected: Bool
    var onRequestAdvance: () -> Void

    func makeUIView(context: Context) -> UITextField {
        let t = UITextField()
        t.placeholder = "0,00"
        t.keyboardType = .decimalPad
        t.textAlignment = .right
        t.autocorrectionType = .no
        t.spellCheckingType = .no
        t.font = UIFont.preferredFont(forTextStyle: .body)
        t.delegate = context.coordinator
        t.addTarget(context.coordinator, action: #selector(Coordinator.editingChanged(_:)), for: .editingChanged)
        t.text = text
        return t
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func updateUIView(_ uiView: UITextField, context: Context) {
        context.coordinator.parent = self
        guard uiView.text != text else { return }
        uiView.text = text
        if uiView.isFirstResponder {
            let b = uiView.beginningOfDocument
            if let e = uiView.position(from: b, offset: (text as NSString).length) {
                uiView.selectedTextRange = uiView.textRange(from: e, to: e)
            }
        }
    }

    final class Coordinator: NSObject, UITextFieldDelegate {
        var parent: ContiLightEuroAmountField

        init(_ parent: ContiLightEuroAmountField) {
            self.parent = parent
        }

        private static let unicodeMinus = Character("\u{2212}")

        private func isLeadingSign(_ c: Character) -> Bool {
            c == "+" || c == "-" || c == Self.unicodeMinus
        }

        /// Cursore subito dopo il segno iniziale (stesso criterio offset UTF-16 usato da UITextField).
        private func placeCaretAfterLeadingSign(_ textField: UITextField) {
            let t = textField.text ?? ""
            guard let f = t.first, isLeadingSign(f) else { return }
            let b = textField.beginningOfDocument
            let u16 = (String(f) as NSString).length
            if let p = textField.position(from: b, offset: u16) {
                textField.selectedTextRange = textField.textRange(from: p, to: p)
            }
        }

        /// Al focus: se c’è solo il segno, cursore subito dopo; altrimenti selezione del solo importo (senza segno) per correggere.
        private func selectAmountBodyExcludingSign(_ textField: UITextField) {
            var t = textField.text ?? ""
            if t.isEmpty {
                t = ContiDatabase.lightImmissioneDefaultAmountText
                textField.text = t
                parent.text = t
            }
            let n = ContiDatabase.normalizedEuroImmissioneAmountFieldText(t)
            if n != t {
                textField.text = n
                parent.text = n
            }
            t = textField.text ?? ""
            guard !t.isEmpty else { return }
            let b = textField.beginningOfDocument
            let u = t as NSString
            let len = u.length
            guard len > 0 else { return }
            guard let fc = t.first, isLeadingSign(fc) else {
                textField.selectAll(textField)
                return
            }
            let signLen = (String(fc) as NSString).length
            if signLen >= len {
                placeCaretAfterLeadingSign(textField)
                return
            }
            if let sPos = textField.position(from: b, offset: signLen),
               let ePos = textField.position(from: b, offset: len) {
                textField.selectedTextRange = textField.textRange(from: sPos, to: ePos)
            }
        }

        @objc func editingChanged(_ textField: UITextField) {
            var t = textField.text ?? ""
            if t.isEmpty { t = ContiDatabase.lightImmissioneDefaultAmountText }
            var n = ContiDatabase.normalizedEuroImmissioneAmountFieldText(t)
            if n.isEmpty { n = ContiDatabase.lightImmissioneDefaultAmountText }
            if n != t {
                textField.text = n
                parent.text = n
            } else {
                parent.text = t
            }
            if textField.isFirstResponder,
               ContiDatabase.euroImmissioneAmountHasAtLeastTwoDecimalDigits(parent.text) {
                parent.onRequestAdvance()
            }
        }

        func textField(
            _ textField: UITextField,
            shouldChangeCharactersIn range: NSRange,
            replacementString string: String
        ) -> Bool {
            let current = textField.text ?? ""
            // Backspace / taglio che toglierebbe il solo segno: mantieni «-» e cursore dopo il segno.
            if string.isEmpty, range.length > 0, range.location == 0, current.count == 1,
               let c = current.first, isLeadingSign(c) {
                let d = ContiDatabase.lightImmissioneDefaultAmountText
                textField.text = d
                parent.text = d
                placeCaretAfterLeadingSign(textField)
                return false
            }
            // Cancellazione del segno iniziale con cifre dopo: vietata (il tasto cancella non rimuove il segno).
            if string.isEmpty, range.length == 1, range.location == 0, current.count > 1,
               let c = current.first, isLeadingSign(c) {
                return false
            }
            let rawNew = (current as NSString).replacingCharacters(in: range, with: string)
            // Selezione intera e cancella: l’esito vuoto va forzato a «-» qui (altrimenti con return true iOS applica stringa vuota).
            if rawNew.isEmpty {
                let d = ContiDatabase.lightImmissioneDefaultAmountText
                textField.text = d
                parent.text = d
                placeCaretAfterLeadingSign(textField)
                return false
            }
            var new = rawNew
            var norm = ContiDatabase.normalizedEuroImmissioneAmountFieldText(new)
            if norm.isEmpty { norm = ContiDatabase.lightImmissioneDefaultAmountText }
            if norm != new {
                textField.text = norm
                parent.text = norm
                let b = textField.beginningOfDocument
                if let p = textField.position(from: b, offset: (norm as NSString).length) {
                    textField.selectedTextRange = textField.textRange(from: p, to: p)
                }
                return false
            }
            return true
        }

        func textFieldDidBeginEditing(_ textField: UITextField) {
            if (textField.text ?? "").isEmpty {
                textField.text = ContiDatabase.lightImmissioneDefaultAmountText
                parent.text = ContiDatabase.lightImmissioneDefaultAmountText
            }
            selectAmountBodyExcludingSign(textField)
            // Dopo il primo tocco iOS può ancora posizionare il cursore in base al punto toccato (es. prima del «-»).
            // Ripetere la selezione sul run loop successivo allinea il comportamento a ogni apertura del campo.
            DispatchQueue.main.async { [weak textField] in
                guard let tf = textField, tf.isFirstResponder else { return }
                self.selectAmountBodyExcludingSign(tf)
            }
        }

        func textFieldDidEndEditing(_ textField: UITextField) {
            let raw = textField.text ?? ""
            if raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                let d = ContiDatabase.lightImmissioneDefaultAmountText
                textField.text = d
                parent.text = d
                return
            }
            let f = ContiDatabase.formatEuroImmissioneOnExit(
                amountText: raw,
                girataSelected: parent.girataSelected
            )
            textField.text = f
            parent.text = f
        }
    }
}

struct ContiLightNuovoMovimentoSchedaView: View {
    let sessionDb: [String: Any]?
    let dataFolderURL: URL?
    /// Stesso bookmark del picker (file `.key`/`.enc`); `startAccessing` va chiamato su questo URL su iPadOS/Dropbox, non sulla cartella genitore.
    let securityScopedBookmarkURL: URL?
    let keyURL: URL?
    let lightEncURL: URL?
    let email: String
    let password: String
    let onPersisted: ([String: Any], [ContiRecordRow], String) -> Void
    /// Se valorizzata, stessa form in modalità modifica (solo righe inserite da Conti light).
    var editingLegacyKey: String? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var dateText = ""
    @State private var catCode = ""
    @State private var acc1Code = ""
    @State private var acc2Code = ""
    @State private var amountText: String = ContiDatabase.lightImmissioneDefaultAmountText
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
    @State private var showDeleteRecordConfirm = false
    @State private var pickedDate: Date = Date()
    @State private var didRunInitialDefaults = false
    @FocusState private var focusedField: ImmissioneField?

    private var isEditMode: Bool { editingLegacyKey != nil }

    private enum ImmissioneField: Hashable {
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

    /// Girata conto/conto: il secondo conto non può essere carta (come sul desktop).
    private var accRowsGirataSecondo: [(code: String, label: String, subtitle: String?)] {
        (lists?.conti ?? []).filter { !$0.isCreditCard }.map { ($0.code, $0.name, nil) }
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
                                    rows: accRowsGirataSecondo,
                                    includeNone: true,
                                    noneLabel: "Nessuno",
                                    selectedCode: $acc2Code
                                )
                            } label: {
                                LabeledContent("Secondo conto", value: acc2Label)
                            }
                            .disabled(accRowsGirataSecondo.isEmpty)
                        }
                    }
                    Section {
                        LabeledContent("Importo (€)") {
                            ContiLightEuroAmountField(
                                text: $amountText,
                                girataSelected: girataSelected,
                                onRequestAdvance: {
                                    dismissNumericKeyboard()
                                    focusedField = showAssegnoSection ? .cheque : .note
                                }
                            )
                        }
                        HStack {
                            Spacer()
                            Button {
                                setImmissioneSign(negative: false)
                            } label: {
                                Text("+")
                            }
                            .buttonStyle(.borderless)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Color(uiColor: .systemTeal).opacity(0.2))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                            Button {
                                setImmissioneSign(negative: true)
                            } label: {
                                Text("−")
                            }
                            .buttonStyle(.borderless)
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
                        Button(isEditMode ? "Conferma modifiche" : "Conferma immissione") {
                            prepareCommitDialog()
                        }
                        .frame(maxWidth: .infinity)
                        .disabled(isSaving || !canAttemptSave || !formReadyForSave)
                        if isEditMode {
                            Button("Annulla questa registrazione", role: .destructive) {
                                showDeleteRecordConfirm = true
                            }
                            .frame(maxWidth: .infinity)
                            .disabled(isSaving)
                        } else {
                            Button("Cancella valori", role: .destructive) {
                                clearForm()
                            }
                            .frame(maxWidth: .infinity)
                            .disabled(isSaving)
                        }
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
        .navigationTitle(isEditMode ? "Modifica registrazione" : "Nuove registrazioni")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if !didRunInitialDefaults {
                didRunInitialDefaults = true
                if isEditMode, let key = editingLegacyKey, let db = sessionDb {
                    applyEditPrefill(legacyKey: key, db: db)
                } else {
                    applyDefaultCategoryAccountAndDate()
                }
            }
            syncChequeFromAcc1()
            applyGiroDefaultNoteIfNeeded()
        }
        .onChange(of: pickedDate) { _, d in
            dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(d))
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
                    clearAcc2IfCreditCardInGirata()
                }
            } else {
                acc2Code = ""
            }
            syncChequeFromAcc1()
        }
        .onChange(of: acc1Code) { _, _ in
            syncChequeFromAcc1()
            clearAcc2IfCreditCardInGirata()
        }
        .onChange(of: acc2Code) { _, _ in
            guard girataSelected else { return }
            if hasVirtualeInGirataPair, noteText.trimmingCharacters(in: .whitespacesAndNewlines) == "Giroconto" {
                noteText = ""
            }
        }
        .confirmationDialog(
            isEditMode ? "Confermare le modifiche?" : "Confermare l’inserimento?",
            isPresented: $showSaveConfirmDialog,
            titleVisibility: .visible
        ) {
            Button("Annulla", role: .cancel) {}
            Button(isEditMode ? "Salva" : "Inserisci") {
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
            Button(isEditMode ? "Salva comunque" : "Inserisci comunque", role: .destructive) {
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
        .confirmationDialog(
            "Annullare questa registrazione? Verrà impostata come annullata (come sul desktop): non comparirà più in elenco né nei saldi, ma resterà nel database finché non la gestisci dal programma per PC.",
            isPresented: $showDeleteRecordConfirm,
            titleVisibility: .visible
        ) {
            Button("Non adesso", role: .cancel) {}
            Button("Annulla registrazione", role: .destructive) {
                performDeleteRecord()
            }
        }
    }

    private func applyEditPrefill(legacyKey: String, db: [String: Any]) {
        do {
            let p = try ContiDatabase.immissioneEditPrefill(db: db, legacyKey: legacyKey)
            pickedDate = p.date
            dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.isoDateStringFromDateLocal(p.date))
            catCode = p.catCode
            acc1Code = p.acc1
            acc2Code = p.acc2
            amountText = p.amountText
            chequeText = p.cheque
            noteText = p.note
            let clid = p.contiLightId.trimmingCharacters(in: .whitespacesAndNewlines)
            pendingLightRecordId = clid.isEmpty ? UUID().uuidString : clid
            clearAcc2IfCreditCardInGirata()
        } catch {
            if let ce = error as? ContiLightImmissioneError, case .message(let s) = ce {
                errorAlertMessage = s
            } else {
                errorAlertMessage = error.localizedDescription
            }
            showErrorAlert = true
        }
    }

    private var canAttemptSave: Bool {
        dataFolderURL != nil && keyURL != nil && lightEncURL != nil
    }

    private func errorMessage(from err: Error) -> String {
        if let ce = err as? ContiLightImmissioneError, case .message(let s) = ce {
            return s
        }
        if let le = err as? LocalizedError, let d = le.errorDescription {
            return d
        }
        return err.localizedDescription
    }

    private func runWithDataFolderAccess<T>(
        folder: URL,
        _ body: () -> Result<T, Error>
    ) -> Result<T, Error> {
        let scope = securityScopedBookmarkURL ?? folder
        let access = scope.startAccessingSecurityScopedResource()
        defer {
            if access {
                scope.stopAccessingSecurityScopedResource()
            }
        }
        guard access else {
            return .failure(
                ContiLightImmissioneError.message(
                    "Impossibile accedere in scrittura alla cartella dati (permessi)."
                )
            )
        }
        return body()
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
        if isEditMode {
            guard let lk = editingLegacyKey, !lk.isEmpty, !pendingLightRecordId.isEmpty else {
                errorAlertMessage = "Dati per la modifica non disponibili. Torna all’elenco e riapri la registrazione."
                showErrorAlert = true
                return
            }
        } else {
            pendingLightRecordId = UUID().uuidString
        }
        do {
            let rid = pendingLightRecordId
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
        lines.append(
            isEditMode
                ? "Le modifiche saranno scritte nei file cifrati nella cartella dati (Dropbox / File)."
                : "La registrazione sarà scritta nei file cifrati nella cartella dati (Dropbox / File)."
        )
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
        let optEdit = editingLegacyKey
        let isNewForm = (optEdit == nil)
        isSaving = true
        DispatchQueue.global(qos: .userInitiated).async {
            let result = runWithDataFolderAccess(folder: folder) {
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
                    if let lk = optEdit {
                        try ContiDatabase.applyLightImmissioneUpdateInSession(
                            db: &working,
                            legacyKey: lk,
                            recordFromTemplate: tpl
                        )
                    } else {
                        _ = try ContiDatabase.appendLightSessionRecord(db: &working, recordTemplate: tpl)
                    }
                    let out = try ContiDatabase.persistSessionDbToEncryptedFiles(
                        sessionDb: working,
                        recordForSaldi: tpl,
                        lightEncURL: e,
                        keyURL: k,
                        email: emailTrim,
                        password: passwordTrim
                    )
                    return .success((sessionLight: out.sessionLight, note: out.note))
                } catch {
                    return .failure(error)
                }
            }
            DispatchQueue.main.async {
                isSaving = false
                switch result {
                case .success(let pair):
                    let rows = ContiDatabase.displayRecords(from: pair.sessionLight)
                    onPersisted(pair.sessionLight, rows, pair.note)
                    successAlertMessage = pair.note
                    showSuccessAlert = true
                    if isNewForm {
                        clearForm()
                    }
                case .failure(let err):
                    errorAlertMessage = errorMessage(from: err)
                    showErrorAlert = true
                }
            }
        }
    }

    private func performDeleteRecord() {
        guard let db = sessionDb, let folder = dataFolderURL, let k = keyURL, let e = lightEncURL, let lk = editingLegacyKey else {
            errorAlertMessage = "Operazione non disponibile."
            showErrorAlert = true
            return
        }
        let emailTrim = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let passwordTrim = password.trimmingCharacters(in: .whitespacesAndNewlines)
        isSaving = true
        DispatchQueue.global(qos: .userInitiated).async {
            let result = runWithDataFolderAccess(folder: folder) {
                do {
                    var working = try ContiDatabase.deepCopyDb(db)
                    try ContiDatabase.setSessionRecordCancelled(db: &working, legacyKey: lk, isCancelled: true)
                    let saldiPlaceholder: [String: Any] = ["is_cancelled": true]
                    let out = try ContiDatabase.persistSessionDbToEncryptedFiles(
                        sessionDb: working,
                        recordForSaldi: saldiPlaceholder,
                        lightEncURL: e,
                        keyURL: k,
                        email: emailTrim,
                        password: passwordTrim
                    )
                    return .success((sessionLight: out.sessionLight, note: out.note))
                } catch {
                    return .failure(error)
                }
            }
            DispatchQueue.main.async {
                isSaving = false
                switch result {
                case .success(let pair):
                    let rows = ContiDatabase.displayRecords(from: pair.sessionLight)
                    onPersisted(pair.sessionLight, rows, pair.note)
                    dismiss()
                case .failure(let err):
                    errorAlertMessage = errorMessage(from: err)
                    showErrorAlert = true
                }
            }
        }
    }

    private func setImmissioneSign(negative: Bool) {
        let t = ContiDatabase.normalizedEuroImmissioneAmountFieldText(amountText)
        var body = t
        if t.first == "+" || t.first == "-" {
            body = String(t.dropFirst())
        }
        amountText = (negative ? "-" : "+") + body
    }

    private func clearForm() {
        acc2Code = ""
        amountText = ContiDatabase.lightImmissioneDefaultAmountText
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
        amountText = ContiDatabase.lightImmissioneDefaultAmountText
    }

    private func dismissNumericKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }

    private func clearAcc2IfCreditCardInGirata() {
        guard girataSelected else { return }
        if let a2 = lists?.conti.first(where: { $0.code == acc2Code }), a2.isCreditCard {
            acc2Code = ""
        }
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
