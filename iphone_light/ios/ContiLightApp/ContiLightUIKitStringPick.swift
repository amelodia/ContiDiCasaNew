import SwiftUI
import UIKit

// MARK: - Liste filtri (stringhe): UITableView nativo, tap immediato

final class ContiLightStringPickTableVC: UITableViewController {
    var noneLabel = ""
    var choices: [String] = []
    /// Valore selezionato (vuoto = «tutte/tutti»).
    var currentSelection = ""
    var onPick: ((String) -> Void)?

    convenience init() {
        self.init(style: .plain)
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        tableView.rowHeight = UITableView.automaticDimension
        tableView.estimatedRowHeight = 44
        clearsSelectionOnViewWillAppear = false
    }

    override func numberOfSections(in _: UITableView) -> Int { 1 }

    override func tableView(_: UITableView, numberOfRowsInSection _: Int) -> Int {
        1 + choices.count
    }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
        var content = cell.defaultContentConfiguration()
        if indexPath.row == 0 {
            content.text = noneLabel
            let on = currentSelection.isEmpty
            cell.accessoryType = on ? .checkmark : .none
        } else {
            let text = choices[indexPath.row - 1]
            content.text = text
            content.textProperties.numberOfLines = 0
            let on = !currentSelection.isEmpty && currentSelection == text
            cell.accessoryType = on ? .checkmark : .none
        }
        cell.contentConfiguration = content
        return cell
    }

    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let value: String
        if indexPath.row == 0 {
            value = ""
        } else {
            value = choices[indexPath.row - 1]
        }
        onPick?(value)
    }
}

struct ContiLightUIKitStringPickRepresentable: UIViewControllerRepresentable {
    let title: String
    let noneLabel: String
    let choices: [String]
    @Binding var selection: String
    var afterSelect: (() -> Void)?

    func makeCoordinator() -> StringPickCoordinator {
        StringPickCoordinator(selection: $selection, afterSelect: afterSelect)
    }

    func makeUIViewController(context: Context) -> ContiLightStringPickTableVC {
        let vc = ContiLightStringPickTableVC()
        vc.title = title
        let coord = context.coordinator
        sync(vc: vc, coord: coord)
        vc.onPick = { [weak vc] newValue in
            coord.selection.wrappedValue = newValue
            vc?.currentSelection = newValue
            vc?.tableView.reloadData()
            coord.afterSelect?()
        }
        return vc
    }

    func updateUIViewController(_ vc: ContiLightStringPickTableVC, context: Context) {
        context.coordinator.selection = $selection
        context.coordinator.afterSelect = afterSelect
        sync(vc: vc, coord: context.coordinator)
        vc.tableView.reloadData()
    }

    private func sync(vc: ContiLightStringPickTableVC, coord: StringPickCoordinator) {
        vc.noneLabel = noneLabel
        vc.choices = choices
        vc.currentSelection = coord.selection.wrappedValue
    }

    final class StringPickCoordinator {
        var selection: Binding<String>
        var afterSelect: (() -> Void)?
        init(selection: Binding<String>, afterSelect: (() -> Void)?) {
            self.selection = selection
            self.afterSelect = afterSelect
        }
    }
}

// MARK: - Liste «Nuove registrazioni» (codice + etichetta)

final class ContiLightCodePickTableVC: UITableViewController {
    struct Row: Hashable {
        let code: String
        let label: String
        /// Sottotitolo (es. carta → conto di riferimento); opzionale.
        let subtitle: String?
    }

    var rows: [Row] = []
    var includeNone = false
    var noneLabel = ""
    var selectedCode = ""
    var onPick: ((String) -> Void)?

    convenience init() {
        self.init(style: .plain)
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        tableView.register(UITableViewCell.self, forCellReuseIdentifier: "cell")
        tableView.rowHeight = UITableView.automaticDimension
        tableView.estimatedRowHeight = 44
        clearsSelectionOnViewWillAppear = false
    }

    override var canBecomeFirstResponder: Bool { true }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        _ = becomeFirstResponder()
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        resignFirstResponder()
    }

    /// Allineato al desktop: tasto lettera → prima riga il cui nome inizia con quella lettera (se esiste).
    override var keyCommands: [UIKeyCommand]? {
        var cmds: [UIKeyCommand] = []
        for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" {
            cmds.append(UIKeyCommand(input: String(ch), modifierFlags: [], action: #selector(onLetterKey(_:))))
        }
        return cmds
    }

    @objc private func onLetterKey(_ sender: UIKeyCommand) {
        guard let inp = sender.input, let ch = inp.first, ch.isLetter else { return }
        let want = String(ch).lowercased()
        let offset = includeNone ? 1 : 0
        for (i, r) in rows.enumerated() {
            let trimmed = r.label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let firstChar = trimmed.first else { continue }
            if String(firstChar).lowercased() == want {
                let row = i + offset
                let ip = IndexPath(row: row, section: 0)
                tableView.scrollToRow(at: ip, at: .middle, animated: true)
                onPick?(r.code)
                return
            }
        }
    }

    override func tableView(_: UITableView, numberOfRowsInSection _: Int) -> Int {
        (includeNone ? 1 : 0) + rows.count
    }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "cell", for: indexPath)
        var content = cell.defaultContentConfiguration()
        let offset = includeNone ? 1 : 0
        if includeNone, indexPath.row == 0 {
            content.text = noneLabel
            let on = selectedCode.isEmpty
            cell.accessoryType = on ? .checkmark : .none
        } else {
            let r = rows[indexPath.row - offset]
            content.text = r.label
            if let sub = r.subtitle, !sub.isEmpty {
                content.secondaryText = sub
                content.secondaryTextProperties.color = .secondaryLabel
            } else {
                content.secondaryText = nil
            }
            content.textProperties.numberOfLines = 0
            let on = selectedCode == r.code
            cell.accessoryType = on ? .checkmark : .none
        }
        cell.contentConfiguration = content
        return cell
    }

    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        let offset = includeNone ? 1 : 0
        if includeNone, indexPath.row == 0 {
            onPick?("")
            return
        }
        let r = rows[indexPath.row - offset]
        onPick?(r.code)
    }
}

struct ContiLightUIKitCodePickRepresentable: UIViewControllerRepresentable {
    let title: String
    let rowItems: [(code: String, label: String, subtitle: String?)]
    let includeNone: Bool
    let noneLabel: String
    @Binding var selectedCode: String
    var afterSelect: (() -> Void)?

    func makeCoordinator() -> CodePickCoordinator {
        CodePickCoordinator(selectedCode: $selectedCode, afterSelect: afterSelect)
    }

    func makeUIViewController(context: Context) -> ContiLightCodePickTableVC {
        let vc = ContiLightCodePickTableVC()
        vc.title = title
        let coord = context.coordinator
        sync(vc: vc, coord: coord)
        vc.onPick = { [weak vc] code in
            coord.selectedCode.wrappedValue = code
            vc?.selectedCode = code
            vc?.tableView.reloadData()
            coord.afterSelect?()
        }
        return vc
    }

    func updateUIViewController(_ vc: ContiLightCodePickTableVC, context: Context) {
        context.coordinator.selectedCode = $selectedCode
        context.coordinator.afterSelect = afterSelect
        sync(vc: vc, coord: context.coordinator)
        vc.tableView.reloadData()
    }

    private func sync(vc: ContiLightCodePickTableVC, coord: CodePickCoordinator) {
        vc.rows = rowItems.map { ContiLightCodePickTableVC.Row(code: $0.code, label: $0.label, subtitle: $0.subtitle) }
        vc.includeNone = includeNone
        vc.noneLabel = noneLabel
        vc.selectedCode = coord.selectedCode.wrappedValue
    }

    final class CodePickCoordinator {
        var selectedCode: Binding<String>
        var afterSelect: (() -> Void)?
        init(selectedCode: Binding<String>, afterSelect: (() -> Void)?) {
            self.selectedCode = selectedCode
            self.afterSelect = afterSelect
        }
    }
}
