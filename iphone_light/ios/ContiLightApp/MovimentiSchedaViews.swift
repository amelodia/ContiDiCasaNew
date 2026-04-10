import SwiftUI

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

    private var saldiIntroText: String {
        if let meta = ContiDatabase.lightSaldiSnapshotMeta(sessionDb: sessionDb) {
            return """
            Valori copiati dal desktop sul database completo (blocco «light_saldi»). \
            Riferimento \(meta.dateIso), anno piano \(meta.yearBasis). \
            Dopo nuove immissioni su iOS, al salvataggio si aggiornano in locale; salva sul desktop per ricalcolo globale.
            """
        }
        return "Dati mancanti: nel file non c’è il blocco «light_saldi». Rigenera il file *_light.enc dal desktop (salvataggio app desktop)."
    }

    private var sommaAssoluti: Decimal {
        rows.reduce(Decimal.zero) { $0 + $1.saldoAssoluto }
    }

    private var sommaAllaData: Decimal {
        rows.reduce(Decimal.zero) { $0 + $1.saldoOggi }
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
                Section("Saldi totali") {
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
                    Text("Somma algebrica dei conti elencati sotto (come riga di totale in elenco).")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                Section {
                    ForEach(rows) { r in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(r.accountName)
                                .font(.subheadline.weight(.semibold))
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
                                Text("Alla data (oggi al salvataggio desktop)")
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Text(ContiDatabase.formatEuroTwoDecimals(r.saldoOggi))
                                    .monospacedDigit()
                                    .foregroundStyle(amountColor(r.saldoOggi))
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
    let rows: [(code: String, label: String)]
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

    @State private var dateText = ""
    @State private var catCode = ""
    @State private var acc1Code = ""
    @State private var acc2Code = ""
    @State private var amountText = ""
    @State private var chequeText = ""
    @State private var noteText = ""
    @State private var showSaveStubAlert = false

    private var lists: (categorie: [ContiImmissioneCategoria], conti: [ContiImmissioneConto])? {
        guard let db = sessionDb else { return nil }
        return ContiDatabase.immissionePickLists(from: db)
    }

    private var catRows: [(code: String, label: String)] {
        (lists?.categorie ?? []).map { ($0.code, $0.displayName) }
    }

    private var accRows: [(code: String, label: String)] {
        (lists?.conti ?? []).map { ($0.code, $0.name) }
    }

    private var selectedCatNote: String {
        lists?.categorie.first { $0.code == catCode }?.planNote ?? "—"
    }

    private var catLabel: String {
        lists?.categorie.first { $0.code == catCode }?.displayName ?? "—"
    }

    private var acc1Label: String {
        lists?.conti.first { $0.code == acc1Code }?.name ?? "—"
    }

    private var acc2Label: String {
        if acc2Code.isEmpty { return "—" }
        return lists?.conti.first { $0.code == acc2Code }?.name ?? "—"
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
                        Text(
                            "Scheda allineata alla pagina «Nuove registrazioni» del desktop (campi principali). " +
                                "Niente memoria/saldo cassa su iOS. Il salvataggio sul file cifrato non è ancora attivo da questa app."
                        )
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    }
                    Section {
                        NavigationLink {
                            ImmissioneCodePickView(
                                title: "Categoria",
                                rows: catRows,
                                includeNone: true,
                                noneLabel: "—",
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
                        LabeledContent("Data (gg/mm/aaaa)") {
                            TextField("gg/mm/aaaa", text: $dateText)
                                .keyboardType(.numbersAndPunctuation)
                                .multilineTextAlignment(.trailing)
                        }
                        Button("Oggi") {
                            dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.todayIsoLocal())
                        }
                    }
                    Section {
                        NavigationLink {
                            ImmissioneCodePickView(
                                title: "Conto",
                                rows: accRows,
                                includeNone: true,
                                noneLabel: "—",
                                selectedCode: $acc1Code
                            )
                        } label: {
                            LabeledContent("Conto", value: acc1Label)
                        }
                        .disabled(accRows.isEmpty)

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
                    Section {
                        LabeledContent("Importo (€)") {
                            TextField("0,00", text: $amountText)
                                .keyboardType(.decimalPad)
                                .multilineTextAlignment(.trailing)
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
                    Section {
                        LabeledContent("Assegno") {
                            TextField("—", text: $chequeText)
                                .textInputAutocapitalization(.characters)
                        }
                    }
                    Section {
                        LabeledContent("Nota") {
                            TextField("Nota registrazione", text: $noteText)
                        }
                    }
                    Section {
                        Button("Conferma immissione") {
                            showSaveStubAlert = true
                        }
                        .frame(maxWidth: .infinity)
                        Button("Cancella valori", role: .destructive) {
                            clearForm()
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .navigationTitle("Nuove registrazioni")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if dateText.isEmpty {
                dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.todayIsoLocal())
            }
        }
        .alert("Immissione", isPresented: $showSaveStubAlert) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(
                "La registrazione non viene ancora scritta sul file .enc dall’app iOS. " +
                    "Per archiviarla usa il desktop."
            )
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
        dateText = ContiDatabase.italianDateDisplayFromIso(ContiDatabase.todayIsoLocal())
        catCode = ""
        acc1Code = ""
        acc2Code = ""
        amountText = ""
        chequeText = ""
        noteText = ""
    }
}
