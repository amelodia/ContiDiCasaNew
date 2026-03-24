#!/usr/bin/env python3
from __future__ import annotations

import json
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from datetime import date

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - runtime optional dependency check
    Fernet = None
    InvalidToken = Exception

from import_legacy import format_euro_it, run_import_legacy


DEFAULT_CDC_ROOT = Path("/Users/macand/Library/CloudStorage/Dropbox/CdC")
DEFAULT_OUTPUT = Path("data/unified_legacy_import.json")
DEFAULT_ENCRYPTED_DB = Path("data/conti_di_casa.enc")
DEFAULT_KEY_FILE = Path("data/conti_di_casa.key")


def to_decimal(value: str) -> Decimal:
    return Decimal(str(value).replace(",", "."))


def to_italian_date(date_iso: str) -> str:
    parts = date_iso.split("-")
    if len(parts) != 3:
        return date_iso
    yyyy, mm, dd = parts
    return f"{dd}/{mm}/{yyyy}"


def year_accounts_map(db: dict) -> dict[int, list[dict[str, str]]]:
    return {y["year"]: y["accounts"] for y in db["years"]}


def year_categories_map(db: dict) -> dict[int, list[dict[str, str]]]:
    return {y["year"]: y["categories"] for y in db["years"]}


def account_name_for_record(rec: dict, accounts_for_year: list[dict[str, str]], which: str) -> str:
    code_key = "account_primary_code" if which == "primary" else "account_secondary_code"
    code = str(rec.get(code_key, "")).strip()
    # Fallback: if code is missing but legacy string with flags exists, extract first digit.
    if not code:
        with_flags_key = "account_primary_with_flags" if which == "primary" else "account_secondary_with_flags"
        with_flags = str(rec.get(with_flags_key, "")).strip()
        if with_flags and with_flags[0].isdigit():
            code = with_flags[0]
    if not str(code).isdigit():
        return ""
    idx = int(code) - 1
    if 0 <= idx < len(accounts_for_year):
        return accounts_for_year[idx]["name"]
    return ""


def category_name_for_record(rec: dict, categories_for_year: list[dict[str, str]]) -> str:
    code = rec.get("category_code", "")
    if not str(code).isdigit():
        return rec.get("category_name") or ""
    idx = int(code)
    if 0 <= idx < len(categories_for_year):
        base = categories_for_year[idx]["name"]
    else:
        base = rec.get("category_name") or ""
    # Output-only: hide leading control sign (+, -, =)
    return base[1:].strip() if base[:1] in {"+", "-", "="} else base


def format_amount_for_output(rec: dict) -> tuple[str, str]:
    year = int(rec.get("year", 0))
    if year <= 2001 and rec.get("amount_lire_original") is not None:
        value = to_decimal(rec["amount_lire_original"])
        currency = "L"
        prefix = "+" if value >= 0 else ""
        # In output, lire amounts are shown without decimals.
        rounded_lire = int(abs(value).quantize(Decimal("1")))
        grouped_lire = f"{rounded_lire:,}".replace(",", ".")
        amount_text = f"{prefix}{'-' if value < 0 else ''}{grouped_lire} {currency}"
        return amount_text, ("neg" if value < 0 else "pos")
    else:
        value = to_decimal(rec["amount_eur"])
        currency = "€"

    prefix = "+" if value >= 0 else ""
    formatted = format_euro_it(value)
    return f"{prefix}{formatted} {currency}", ("neg" if value < 0 else "pos")


def compute_latest_year_balances(db: dict) -> tuple[int, list[dict[str, str]]]:
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    balances = [Decimal("0") for _ in accounts]

    for rec in year_data["records"]:
        amount = to_decimal(rec["amount_eur"])
        c1 = rec.get("account_primary_code", "")
        c2 = rec.get("account_secondary_code", "")
        cat = rec.get("category_code", "")

        c1_idx = int(c1) - 1 if c1.isdigit() else -1
        c2_idx = int(c2) - 1 if c2.isdigit() else -1

        if 0 <= c1_idx < len(balances):
            balances[c1_idx] += amount
        if cat == "1" and 0 <= c2_idx < len(balances):
            balances[c2_idx] -= amount

    rows: list[dict[str, str]] = []
    for account, amount in zip(accounts, balances):
        rows.append(
            {
                "code": account["code"],
                "name": account["name"],
                "balance_eur": format_euro_it(amount),
            }
        )
    return latest_year, rows


def get_or_create_key(key_path: Path) -> bytes:
    if Fernet is None:
        raise RuntimeError("Pacchetto 'cryptography' non disponibile. Installa con: pip install cryptography")
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    return key


def save_encrypted_db(db: dict, output_path: Path, key_path: Path) -> None:
    key = get_or_create_key(key_path)
    token = Fernet(key).encrypt(json.dumps(db, ensure_ascii=True, indent=2).encode("utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(token)


def load_encrypted_db(output_path: Path, key_path: Path) -> dict | None:
    if Fernet is None:
        return None
    if not output_path.exists() or not key_path.exists():
        return None
    key = key_path.read_bytes()
    token = output_path.read_bytes()
    raw = Fernet(key).decrypt(token)
    return json.loads(raw.decode("utf-8"))


def build_ui(db: dict) -> None:
    latest_year, balances = compute_latest_year_balances(db)

    root = tk.Tk()
    root.title(f"Conti di casa - {date.today().strftime('%d/%m/%Y')}")
    root.geometry("1200x760")

    header = ttk.Frame(root, padding=8)
    header.pack(fill=tk.X)
    ttk.Label(
        header,
        text=f"Registrazioni importate: {db['records_total']} | Ultimo anno: {latest_year}",
    ).pack(side=tk.LEFT)

    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    movimenti_frame = ttk.Frame(notebook, padding=8)
    nuovi_dati_frame = ttk.Frame(notebook, padding=8)
    verifica_frame = ttk.Frame(notebook, padding=8)
    statistiche_frame = ttk.Frame(notebook, padding=8)
    budget_frame = ttk.Frame(notebook, padding=8)
    opzioni_frame = ttk.Frame(notebook, padding=8)
    aiuto_frame = ttk.Frame(notebook, padding=8)
    notebook.add(movimenti_frame, text="Movimenti e correzioni")
    notebook.add(nuovi_dati_frame, text="Nuovi dati")
    notebook.add(verifica_frame, text="Verifica")
    notebook.add(statistiche_frame, text="Statistiche")
    notebook.add(budget_frame, text="Budget")
    notebook.add(opzioni_frame, text="Opzioni")
    notebook.add(aiuto_frame, text="Aiuto")
    notebook.select(0)

    balances_frame = ttk.LabelFrame(movimenti_frame, text="Saldi conti (ultimo anno)", padding=8)
    balances_frame.pack(fill=tk.X, pady=(0, 8))
    bal_cols = ("code", "name", "balance_eur")
    bal_tree = ttk.Treeview(balances_frame, columns=bal_cols, show="headings", height=12)
    bal_tree.heading("code", text="Codice")
    bal_tree.heading("name", text="Conto")
    bal_tree.heading("balance_eur", text="Saldo EUR")
    bal_tree.column("code", width=80, anchor=tk.CENTER)
    bal_tree.column("name", width=260)
    bal_tree.column("balance_eur", width=160, anchor=tk.E)
    bal_tree.pack(fill=tk.X)

    for row in balances:
        bal_tree.insert("", tk.END, values=(row["code"], row["name"], row["balance_eur"]))

    records_frame = ttk.LabelFrame(movimenti_frame, text="Registrazioni importate", padding=8)
    records_frame.pack(fill=tk.BOTH, expand=True)

    accounts_by_year = year_accounts_map(db)
    categories_by_year = year_categories_map(db)

    rec_cols = (
        "legacy_registration_number",
        "date_it",
        "category_name",
        "account_primary_name",
        "account_primary_flags",
        "account_secondary_name",
        "cheque",
        "account_secondary_flags",
    )
    rec_tree = ttk.Treeview(records_frame, columns=rec_cols, show="headings")
    rec_tree.heading("legacy_registration_number", text="Reg.")
    rec_tree.heading("date_it", text="Data")
    rec_tree.heading("category_name", text="Categoria")
    rec_tree.heading("account_primary_name", text="Conto 1")
    rec_tree.heading("account_primary_flags", text="*1")
    rec_tree.heading("account_secondary_name", text="Conto 2")
    rec_tree.heading("cheque", text="Assegno")
    rec_tree.heading("account_secondary_flags", text="*2")
    rec_tree.column("legacy_registration_number", width=65, anchor=tk.E)
    rec_tree.column("date_it", width=110, anchor=tk.CENTER)
    rec_tree.column("category_name", width=180)
    rec_tree.column("account_primary_name", width=150)
    rec_tree.column("account_primary_flags", width=40, anchor=tk.CENTER)
    rec_tree.column("account_secondary_name", width=170)
    rec_tree.column("cheque", width=85, anchor=tk.CENTER)
    rec_tree.column("account_secondary_flags", width=40, anchor=tk.CENTER)

    amount_tree = ttk.Treeview(records_frame, columns=("amount_eur",), show="headings")
    amount_tree.heading("amount_eur", text="Importo")
    amount_tree.column("amount_eur", width=135, anchor=tk.E)
    amount_tree.tag_configure("neg", foreground="#b22222")
    amount_tree.tag_configure("pos", foreground="#006400")

    note_tree = ttk.Treeview(records_frame, columns=("note",), show="headings")
    note_tree.heading("note", text="Nota")
    note_tree.column("note", width=320)

    def sync_scroll(*args: str) -> None:
        rec_tree.yview(*args)
        amount_tree.yview(*args)
        note_tree.yview(*args)

    def on_mousewheel(event: tk.Event) -> str:
        # macOS/Windows wheel
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = -1 if event.delta > 0 else 1
        if delta:
            sync_scroll("scroll", delta, "units")
        return "break"

    def on_button_scroll(event: tk.Event) -> str:
        # Linux wheel fallback
        if getattr(event, "num", None) == 4:
            sync_scroll("scroll", -1, "units")
        elif getattr(event, "num", None) == 5:
            sync_scroll("scroll", 1, "units")
        return "break"

    yscroll = ttk.Scrollbar(records_frame, orient=tk.VERTICAL, command=sync_scroll)
    rec_tree.configure(yscrollcommand=yscroll.set)
    amount_tree.configure(yscrollcommand=yscroll.set)
    note_tree.configure(yscrollcommand=yscroll.set)
    for tree in (rec_tree, amount_tree, note_tree):
        tree.bind("<MouseWheel>", on_mousewheel)
        tree.bind("<Button-4>", on_button_scroll)
        tree.bind("<Button-5>", on_button_scroll)
    rec_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    amount_tree.pack(side=tk.LEFT, fill=tk.Y)
    note_tree.pack(side=tk.LEFT, fill=tk.Y)
    yscroll.pack(side=tk.RIGHT, fill=tk.Y)

    records = [r for y in db["years"] for r in y["records"]]
    # Output order follows legacy registration order, not transaction date.
    records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
    for r in records:
        year = r.get("year")
        year_accounts = accounts_by_year.get(year, [])
        year_categories = categories_by_year.get(year, [])
        account_1_name = account_name_for_record(r, year_accounts, "primary")
        account_2_name = account_name_for_record(r, year_accounts, "secondary")
        category_name = category_name_for_record(r, year_categories)
        stars_1 = r.get("account_primary_flags", "")
        stars_2 = r.get("account_secondary_flags", "")
        amount_text, amount_tag = format_amount_for_output(r)
        rec_tree.insert(
            "",
            tk.END,
            values=(
                r.get("legacy_registration_number", r.get("source_index", "")),
                to_italian_date(r["date_iso"]),
                category_name,
                account_1_name,
                stars_1,
                account_2_name,
                r.get("cheque") or "",
                stars_2,
            ),
        )
        amount_tree.insert("", tk.END, values=(amount_text,), tags=(amount_tag,))
        note_tree.insert("", tk.END, values=(r.get("note") or "",))

    # Placeholder pages for next implementation steps
    ttk.Label(nuovi_dati_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    ttk.Label(verifica_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    ttk.Label(statistiche_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    ttk.Label(budget_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    ttk.Label(aiuto_frame, text="Pagina in preparazione").pack(anchor=tk.W)

    # Opzioni page
    legacy_path_var = tk.StringVar(value=str(DEFAULT_CDC_ROOT))
    data_file_var = tk.StringVar(value=str(DEFAULT_ENCRYPTED_DB))
    key_file_var = tk.StringVar(value=str(DEFAULT_KEY_FILE))

    ttk.Label(opzioni_frame, text="Sorgente import legacy").grid(row=0, column=0, sticky="w", pady=(0, 6))
    legacy_entry = ttk.Entry(opzioni_frame, textvariable=legacy_path_var, width=80)
    legacy_entry.grid(row=1, column=0, sticky="we", padx=(0, 8))

    def browse_legacy() -> None:
        picked = filedialog.askdirectory(initialdir=legacy_path_var.get() or str(DEFAULT_CDC_ROOT))
        if picked:
            legacy_path_var.set(picked)

    ttk.Button(opzioni_frame, text="Sfoglia...", command=browse_legacy).grid(row=1, column=1, sticky="w")

    ttk.Label(opzioni_frame, text="File dati nuova app (criptato)").grid(row=2, column=0, sticky="w", pady=(12, 6))
    data_entry = ttk.Entry(opzioni_frame, textvariable=data_file_var, width=80)
    data_entry.grid(row=3, column=0, sticky="we", padx=(0, 8))

    def browse_data_file() -> None:
        picked = filedialog.asksaveasfilename(
            initialdir=str(Path(data_file_var.get()).parent),
            initialfile=Path(data_file_var.get()).name,
            defaultextension=".enc",
            filetypes=[("Encrypted data", "*.enc"), ("All files", "*.*")],
        )
        if picked:
            data_file_var.set(picked)

    ttk.Button(opzioni_frame, text="Sfoglia...", command=browse_data_file).grid(row=3, column=1, sticky="w")

    ttk.Label(opzioni_frame, text="File chiave cifratura").grid(row=4, column=0, sticky="w", pady=(12, 6))
    key_entry = ttk.Entry(opzioni_frame, textvariable=key_file_var, width=80)
    key_entry.grid(row=5, column=0, sticky="we", padx=(0, 8))

    def browse_key_file() -> None:
        picked = filedialog.asksaveasfilename(
            initialdir=str(Path(key_file_var.get()).parent),
            initialfile=Path(key_file_var.get()).name,
            defaultextension=".key",
            filetypes=[("Key files", "*.key"), ("All files", "*.*")],
        )
        if picked:
            key_file_var.set(picked)

    ttk.Button(opzioni_frame, text="Sfoglia...", command=browse_key_file).grid(row=5, column=1, sticky="w")

    status_var = tk.StringVar(value="")
    ttk.Label(opzioni_frame, textvariable=status_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def reload_legacy_overwrite() -> None:
        confirmed = messagebox.askyesno(
            "Conferma import legacy",
            "Confermi l'avvio di ImportLegacy?\n"
            "Il database della nuova app verrà sovrascritto completamente.",
        )
        if not confirmed:
            status_var.set("Import legacy annullato dall'utente.")
            return
        try:
            legacy_root = Path(legacy_path_var.get())
            output_json = DEFAULT_OUTPUT
            run_import_legacy(legacy_root, output_json)
            new_db = json.loads(output_json.read_text(encoding="utf-8"))
            save_encrypted_db(new_db, Path(data_file_var.get()), Path(key_file_var.get()))
            messagebox.showinfo(
                "Import completato",
                "Import legacy completato.\nIl database della nuova app è stato sovrascritto.",
            )
            status_var.set("Ultimo import: completato con sovrascrittura database nuovo.")
        except Exception as exc:
            messagebox.showerror("Errore import", str(exc))
            status_var.set(f"Errore: {exc}")

    ttk.Button(
        opzioni_frame,
        text="Ricarica importi legacy (sovrascrive dati nuova app)",
        command=reload_legacy_overwrite,
    ).grid(row=6, column=0, sticky="w", pady=(16, 0))

    opzioni_frame.columnconfigure(0, weight=1)

    root.mainloop()


def main() -> None:
    encrypted_db = None
    try:
        encrypted_db = load_encrypted_db(DEFAULT_ENCRYPTED_DB, DEFAULT_KEY_FILE)
    except InvalidToken:
        encrypted_db = None

    if encrypted_db is not None:
        db = encrypted_db
    else:
        run_import_legacy(DEFAULT_CDC_ROOT, DEFAULT_OUTPUT)
        db = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
        try:
            save_encrypted_db(db, DEFAULT_ENCRYPTED_DB, DEFAULT_KEY_FILE)
        except Exception:
            # UI still starts even if encryption backend is unavailable.
            pass
    build_ui(db)


if __name__ == "__main__":
    main()
