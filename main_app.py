#!/usr/bin/env python3
from __future__ import annotations

import json
import platform
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

# Stessa regola della colonna Importo nella griglia movimenti.
COLOR_AMOUNT_POS = "#006400"
COLOR_AMOUNT_NEG = "#b22222"


def app_title_text() -> str:
    return f"Conti di casa - {date.today().strftime('%d/%m/%Y')}"


def title_banner_font() -> tuple[str, int, str]:
    if platform.system() == "Darwin":
        return ("Helvetica Neue", 22, "bold")
    return ("TkDefaultFont", 20, "bold")


def pack_centered_page_title(parent: tk.Widget) -> None:
    """Titolo app ripetuto in cima a ogni scheda, centrato e ben visibile."""
    bar = ttk.Frame(parent)
    bar.pack(fill=tk.X, pady=(0, 14))
    tk.Label(
        bar,
        text=app_title_text(),
        font=title_banner_font(),
        fg="#111111",
        anchor=tk.CENTER,
    ).pack(fill=tk.X)


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


def format_saldo_cell(valuta: str, amount: Decimal) -> str:
    """Allinea stile movimenti: lire senza decimali, euro con 2 decimali e suffisso valuta."""
    if valuta == "L":
        n = int(abs(amount).quantize(Decimal("1")))
        body = f"{n:,}".replace(",", ".")
        if amount < 0:
            return f"-{body} L"
        if amount > 0:
            return f"+{body} L"
        return f"{body} L"
    txt = format_euro_it(amount)
    if amount > 0 and not txt.startswith("+"):
        txt = "+" + txt
    return f"{txt} €"


def _category_code_int(rec: dict) -> int | None:
    raw = str(rec.get("category_code", "")).strip()
    if not raw.isdigit():
        return None
    return int(raw)


def is_giroconto_record(rec: dict) -> bool:
    """Giroconto conto↔conto: stessa logica dei controlli in import_legacy (nome + fallback codice 1)."""
    cat_name = (rec.get("category_name") or "").upper()
    if "GIRATA.CONTO/CONTO" in cat_name or "GIRATA CONTO/CONTO" in cat_name:
        return True
    return _category_code_int(rec) == 1


def is_dotazione_record(rec: dict) -> bool:
    """Dotazione iniziale (cat. 0 nel legacy)."""
    return _category_code_int(rec) == 0


def compute_balances_from_2022(db: dict) -> tuple[int, list[str], list[Decimal]]:
    """
    Saldi dal 2022 all'ultimo anno incluso; dotazione iniziale (cat. 0) solo per il 2022.
    Piano conti = ultimo anno. + sul conto 1; giroconto: − sul conto 2.
    """
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    n_accounts = len(accounts)

    pool: list[dict] = []
    for yd in db["years"]:
        y = int(yd["year"])
        if y < 2022 or y > latest_year:
            continue
        pool.extend(yd["records"])
    pool.sort(key=lambda r: (int(r["year"]), r["source_folder"], r["source_file"], r["source_index"]))

    balances = [Decimal("0") for _ in accounts]
    for rec in pool:
        if rec.get("is_cancelled"):
            continue
        y = int(rec["year"])
        if is_dotazione_record(rec) and y != 2022:
            continue

        amount = to_decimal(rec["amount_eur"])
        c1 = rec.get("account_primary_code", "")
        c2 = rec.get("account_secondary_code", "")

        c1_idx = int(c1) - 1 if str(c1).isdigit() else -1
        c2_idx = int(c2) - 1 if str(c2).isdigit() else -1

        if 0 <= c1_idx < n_accounts:
            balances[c1_idx] += amount
        if is_giroconto_record(rec) and 0 <= c2_idx < n_accounts:
            balances[c2_idx] -= amount

    names = [a["name"] for a in accounts]
    return latest_year, names, balances


def balance_amount_fg(value: Decimal) -> str:
    """Rosso / verde come colonna Importo (zero trattato come non negativo)."""
    return COLOR_AMOUNT_NEG if value < 0 else COLOR_AMOUNT_POS


def show_record_in_movements_grid(rec: dict) -> bool:
    """Dotazione iniziale: visibile solo per il 1990; resto sempre visibile."""
    year = int(rec.get("year") or 0)
    cat = str(rec.get("category_code", "")).strip()
    if cat == "0" and year != 1990:
        return False
    return True


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
    # Riferimento mutabile: dopo import legacy da Opzioni, griglia e saldi devono usare il nuovo DB.
    db_holder: list[dict] = [db]

    def cur_db() -> dict:
        return db_holder[0]

    root = tk.Tk()
    root.title(app_title_text())
    root.geometry("1200x760")

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

    pack_centered_page_title(movimenti_frame)

    records_frame = ttk.Frame(movimenti_frame, padding=8)
    records_frame.pack(fill=tk.BOTH, expand=True)

    mov_style = ttk.Style(root)
    mov_style.configure(
        "MovGrid.Treeview",
        borderwidth=1,
        relief="solid",
        rowheight=22,
        background="#ffffff",
        fieldbackground="#ffffff",
    )
    mov_style.configure(
        "MovGrid.Treeview.Heading",
        borderwidth=1,
        relief="flat",
        background="#ebebeb",
        foreground="#1a1a1a",
        font=("TkDefaultFont", 10, "bold"),
    )

    mov_cols = (
        "legacy_registration_number",
        "date_it",
        "category_name",
        "account_primary_name",
        "account_primary_flags",
        "account_secondary_name",
        "cheque",
        "account_secondary_flags",
    )
    mov_tree = ttk.Treeview(
        records_frame,
        columns=mov_cols,
        show="headings",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    mov_tree.heading("legacy_registration_number", text="Reg.")
    mov_tree.heading("date_it", text="Data")
    mov_tree.heading("category_name", text="Categoria")
    mov_tree.heading("account_primary_name", text="Conto 1")
    mov_tree.heading("account_primary_flags", text="")
    mov_tree.heading("account_secondary_name", text="Conto 2")
    mov_tree.heading("cheque", text="Assegno")
    mov_tree.heading("account_secondary_flags", text="")
    mov_tree.column("legacy_registration_number", width=56, anchor=tk.E, stretch=False, minwidth=40)
    mov_tree.column("date_it", width=100, anchor=tk.CENTER, stretch=False, minwidth=80)
    mov_tree.column("category_name", width=160, stretch=True, minwidth=80)
    mov_tree.column("account_primary_name", width=130, stretch=True, minwidth=70)
    mov_tree.column("account_primary_flags", width=36, anchor=tk.CENTER, stretch=False, minwidth=32)
    mov_tree.column("account_secondary_name", width=150, stretch=True, minwidth=70)
    mov_tree.column("cheque", width=78, anchor=tk.CENTER, stretch=False, minwidth=60)
    mov_tree.column("account_secondary_flags", width=36, anchor=tk.CENTER, stretch=False, minwidth=32)

    mov_tree.tag_configure("stripe0", background="#f7f7f7")
    mov_tree.tag_configure("stripe1", background="#ffffff")

    # Importo (colori) prima di Nota: Treeview separato perché i tag colore valgono per riga intera.
    amt_tree = ttk.Treeview(
        records_frame,
        columns=("amount_eur",),
        show="headings",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    amt_tree.heading("amount_eur", text="Importo")
    amt_tree.column("amount_eur", width=128, anchor=tk.E, stretch=False, minwidth=96)
    amt_tree.tag_configure("neg", foreground=COLOR_AMOUNT_NEG)
    amt_tree.tag_configure("pos", foreground=COLOR_AMOUNT_POS)
    amt_tree.tag_configure("stripe0", background="#f7f7f7")
    amt_tree.tag_configure("stripe1", background="#ffffff")

    note_tree = ttk.Treeview(
        records_frame,
        columns=("note",),
        show="headings",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    note_tree.heading("note", text="Nota")
    note_tree.column("note", width=280, stretch=True, minwidth=120)
    note_tree.tag_configure("stripe0", background="#f7f7f7")
    note_tree.tag_configure("stripe1", background="#ffffff")

    yscroll = ttk.Scrollbar(records_frame, orient=tk.VERTICAL, command=mov_tree.yview)

    _yscroll_lock = False

    def mov_on_yscroll(first: str, last: str) -> None:
        nonlocal _yscroll_lock
        if _yscroll_lock:
            return
        _yscroll_lock = True
        try:
            yscroll.set(first, last)
            f = float(first)
            amt_tree.yview_moveto(f)
            note_tree.yview_moveto(f)
        finally:
            _yscroll_lock = False

    def amt_on_yscroll(first: str, last: str) -> None:
        nonlocal _yscroll_lock
        if _yscroll_lock:
            return
        _yscroll_lock = True
        try:
            yscroll.set(first, last)
            f = float(first)
            mov_tree.yview_moveto(f)
            note_tree.yview_moveto(f)
        finally:
            _yscroll_lock = False

    def note_on_yscroll(first: str, last: str) -> None:
        nonlocal _yscroll_lock
        if _yscroll_lock:
            return
        _yscroll_lock = True
        try:
            yscroll.set(first, last)
            f = float(first)
            mov_tree.yview_moveto(f)
            amt_tree.yview_moveto(f)
        finally:
            _yscroll_lock = False

    mov_tree.configure(yscrollcommand=mov_on_yscroll)
    amt_tree.configure(yscrollcommand=amt_on_yscroll)
    note_tree.configure(yscrollcommand=note_on_yscroll)

    _sel_sync = False

    def _clear_selection(tree: ttk.Treeview) -> None:
        for iid in tree.selection():
            tree.selection_remove(iid)

    def sync_selection_mov(_event: tk.Event | None = None) -> None:
        nonlocal _sel_sync
        if _sel_sync:
            return
        _sel_sync = True
        try:
            sel = mov_tree.selection()
            if sel:
                amt_tree.selection_set(sel)
                note_tree.selection_set(sel)
                amt_tree.focus(sel[0])
            else:
                _clear_selection(amt_tree)
                _clear_selection(note_tree)
        finally:
            _sel_sync = False

    def sync_selection_amt(_event: tk.Event | None = None) -> None:
        nonlocal _sel_sync
        if _sel_sync:
            return
        _sel_sync = True
        try:
            sel = amt_tree.selection()
            if sel:
                mov_tree.selection_set(sel)
                note_tree.selection_set(sel)
                mov_tree.focus(sel[0])
            else:
                _clear_selection(mov_tree)
                _clear_selection(note_tree)
        finally:
            _sel_sync = False

    def sync_selection_note(_event: tk.Event | None = None) -> None:
        nonlocal _sel_sync
        if _sel_sync:
            return
        _sel_sync = True
        try:
            sel = note_tree.selection()
            if sel:
                mov_tree.selection_set(sel)
                amt_tree.selection_set(sel)
                mov_tree.focus(sel[0])
            else:
                _clear_selection(mov_tree)
                _clear_selection(amt_tree)
        finally:
            _sel_sync = False

    mov_tree.bind("<<TreeviewSelect>>", sync_selection_mov)
    amt_tree.bind("<<TreeviewSelect>>", sync_selection_amt)
    note_tree.bind("<<TreeviewSelect>>", sync_selection_note)

    def on_mousewheel(event: tk.Event) -> str:
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = -1 if event.delta > 0 else 1
        if delta:
            mov_tree.yview("scroll", str(delta), "units")
        return "break"

    def on_button_scroll(event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            mov_tree.yview("scroll", "-1", "units")
        elif getattr(event, "num", None) == 5:
            mov_tree.yview("scroll", "1", "units")
        return "break"

    for _tree in (mov_tree, amt_tree, note_tree):
        _tree.bind("<MouseWheel>", on_mousewheel)
        _tree.bind("<Button-4>", on_button_scroll)
        _tree.bind("<Button-5>", on_button_scroll)

    records_frame.grid_columnconfigure(0, weight=1, minsize=120)
    records_frame.grid_columnconfigure(1, weight=0, minsize=104)
    records_frame.grid_columnconfigure(2, weight=1, minsize=100)
    records_frame.grid_columnconfigure(3, weight=0, minsize=20)
    records_frame.grid_rowconfigure(0, weight=1)
    mov_tree.grid(row=0, column=0, sticky="nsew")
    amt_tree.grid(row=0, column=1, sticky="nsew")
    note_tree.grid(row=0, column=2, sticky="nsew")
    yscroll.grid(row=0, column=3, sticky="ns", padx=(2, 0))

    def populate_movements_trees() -> None:
        for iid in mov_tree.get_children():
            mov_tree.delete(iid)
        for iid in amt_tree.get_children():
            amt_tree.delete(iid)
        for iid in note_tree.get_children():
            note_tree.delete(iid)
        d = cur_db()
        accounts_by_year = year_accounts_map(d)
        categories_by_year = year_categories_map(d)
        records = [r for y in d["years"] for r in y["records"]]
        records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        row_i = 0
        for r in records:
            if not show_record_in_movements_grid(r):
                continue
            year = r.get("year")
            year_accounts = accounts_by_year.get(year, [])
            year_categories = categories_by_year.get(year, [])
            account_1_name = account_name_for_record(r, year_accounts, "primary")
            account_2_name = account_name_for_record(r, year_accounts, "secondary")
            category_name = category_name_for_record(r, year_categories)
            stars_1 = r.get("account_primary_flags", "")
            stars_2 = r.get("account_secondary_flags", "")
            amount_text, amount_tag = format_amount_for_output(r)
            stripe = f"stripe{row_i % 2}"
            rid = str(row_i)
            mov_tree.insert(
                "",
                tk.END,
                iid=rid,
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
                tags=(stripe,),
            )
            amt_tree.insert("", tk.END, iid=rid, values=(amount_text,), tags=(amount_tag, stripe))
            note_tree.insert("", tk.END, iid=rid, values=(r.get("note") or "",), tags=(stripe,))
            row_i += 1

    populate_movements_trees()

    balance_footer = ttk.Frame(movimenti_frame, padding=(0, 10, 0, 0))
    balance_footer.pack(fill=tk.X)
    balance_footer_row = tk.Frame(balance_footer)
    balance_footer_row.pack(fill=tk.X, anchor=tk.W)

    saldo_footer_font = ("TkDefaultFont", 11)

    def refresh_balance_footer() -> None:
        for w in balance_footer_row.winfo_children():
            w.destroy()
        ly, names, amts = compute_balances_from_2022(cur_db())
        valuta = "E" if ly >= 2002 else "L"
        total = sum(amts, Decimal("0"))

        def plain(text: str) -> None:
            tk.Label(balance_footer_row, text=text, font=saldo_footer_font).pack(side=tk.LEFT)

        def colored_amount(amt: Decimal) -> None:
            tk.Label(
                balance_footer_row,
                text=format_saldo_cell(valuta, amt),
                font=saldo_footer_font,
                fg=balance_amount_fg(amt),
            ).pack(side=tk.LEFT)

        plain("Saldo totale: ")
        colored_amount(total)
        for name, amt in zip(names, amts):
            plain("    ")
            plain(f"{name.strip()}: ")
            colored_amount(amt)

    refresh_balance_footer()

    # Placeholder pages for next implementation steps
    pack_centered_page_title(nuovi_dati_frame)
    ttk.Label(nuovi_dati_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(verifica_frame)
    ttk.Label(verifica_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(statistiche_frame)
    ttk.Label(statistiche_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(budget_frame)
    ttk.Label(budget_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(aiuto_frame)
    ttk.Label(aiuto_frame, text="Pagina in preparazione").pack(anchor=tk.W)

    # Opzioni page
    pack_centered_page_title(opzioni_frame)
    opzioni_inner = ttk.Frame(opzioni_frame)
    opzioni_inner.pack(fill=tk.BOTH, expand=True)

    legacy_path_var = tk.StringVar(value=str(DEFAULT_CDC_ROOT))
    data_file_var = tk.StringVar(value=str(DEFAULT_ENCRYPTED_DB))
    key_file_var = tk.StringVar(value=str(DEFAULT_KEY_FILE))

    ttk.Label(opzioni_inner, text="Sorgente import legacy").grid(row=0, column=0, sticky="w", pady=(0, 6))
    legacy_entry = ttk.Entry(opzioni_inner, textvariable=legacy_path_var, width=80)
    legacy_entry.grid(row=1, column=0, sticky="we", padx=(0, 8))

    def browse_legacy() -> None:
        picked = filedialog.askdirectory(initialdir=legacy_path_var.get() or str(DEFAULT_CDC_ROOT))
        if picked:
            legacy_path_var.set(picked)

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_legacy).grid(row=1, column=1, sticky="w")

    ttk.Label(opzioni_inner, text="File dati nuova app (criptato)").grid(row=2, column=0, sticky="w", pady=(12, 6))
    data_entry = ttk.Entry(opzioni_inner, textvariable=data_file_var, width=80)
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

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_data_file).grid(row=3, column=1, sticky="w")

    ttk.Label(opzioni_inner, text="File chiave cifratura").grid(row=4, column=0, sticky="w", pady=(12, 6))
    key_entry = ttk.Entry(opzioni_inner, textvariable=key_file_var, width=80)
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

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_key_file).grid(row=5, column=1, sticky="w")

    status_var = tk.StringVar(value="")
    ttk.Label(opzioni_inner, textvariable=status_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))

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
            db_holder[0] = new_db
            populate_movements_trees()
            refresh_balance_footer()
            messagebox.showinfo(
                "Import completato",
                "Import legacy completato.\nIl database della nuova app è stato sovrascritto.",
            )
            status_var.set("Ultimo import: completato con sovrascrittura database nuovo.")
        except Exception as exc:
            messagebox.showerror("Errore import", str(exc))
            status_var.set(f"Errore: {exc}")

    ttk.Button(
        opzioni_inner,
        text="Ricarica importi legacy (sovrascrive dati nuova app)",
        command=reload_legacy_overwrite,
    ).grid(row=6, column=0, sticky="w", pady=(16, 0))

    opzioni_inner.columnconfigure(0, weight=1)

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
