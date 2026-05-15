#!/usr/bin/env python3
"""
Diagnostico saldo ibrido vs saldo banca noto (un conto).

Legge il DB cifrato, NON lo modifica. Calcola: ibrido footer, scomposizione *sld* / +app / +annulli / +edit,
scarto rispetto al saldo banca indicato, delta implicito su legacy_saldi per allineare l'ibrido alla banca
senza toccare i movimenti, elenchi audit annulli e righe +app che toccano la colonna.

Uso (cartella dati da data_workspace, come le altre utility):
  python3 scripts/hybrid_bank_diagnostic.py --account-code 6 --bank-balance 4789,36

PDF in uscita (default: diagnostico_saldo_<codice>_YYYYMMDD.pdf nella root del repo):
  python3 scripts/hybrid_bank_diagnostic.py --account-code 6 --bank-balance 4789,36 \\
      --pdf /percorso/rapporto.pdf
  Solo testo su stdout, senza file PDF: aggiungere --no-pdf

Percorsi espliciti DB:
  python3 scripts/hybrid_bank_diagnostic.py --account-code 6 --bank-balance 4789,36 \\
      --enc /percorso/conti_utente_X.enc --key /percorso/conti_di_casa.key
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402
from main_app import (  # noqa: E402
    LEGACY_DOTAZIONE_YEAR,
    PLAN_REFERENCE_YEAR,
    _indices_touched_by_import_twin_actives,
    _record_contribution_to_balance_vector,
    account_column_index_in_latest_chart,
    compute_cancelled_imported_records_balance_adjustment,
    compute_imported_active_records_edit_balance_adjustment,
    compute_new_records_effect,
    format_euro_it,
    hybrid_absolute_balances_for_saldi,
    import_cancel_twin_balance_keys,
    is_dotazione_record,
    latest_year_bucket,
    legacy_absolute_account_amounts,
    load_encrypted_db,
    year_bucket_for_calendar_year,
)


def _resolve_db_enc_key(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    if args.enc and args.key:
        return Path(args.enc).expanduser().resolve(), Path(args.key).expanduser().resolve()
    saved = data_workspace.load_saved_workspace_path()
    if saved is None:
        return None, None
    data_workspace.set_data_workspace_root(saved)
    key_path = data_workspace.default_key_file()
    cands = data_workspace.primary_user_enc_files_sorted(saved)
    if not cands:
        return None, None
    return cands[0], key_path


def _pdf_safe(value: object) -> str:
    s = str(value if value is not None else "")
    s = (
        s.replace("€", "EUR")
        .replace("–", "-")
        .replace("—", "-")
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
    )
    try:
        s.encode("latin-1")
    except UnicodeEncodeError:
        s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s


def _parse_bank_balance(s: str) -> Decimal:
    t = (s or "").strip().replace(" ", "").replace(".", "").replace(",", ".") if "," in s else (s or "").strip().replace(" ", "")
    if not t:
        raise InvalidOperation("vuoto")
    return Decimal(t)


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostico ibrido vs saldo banca (PDF + opz. stdout)")
    ap.add_argument("--account-code", required=True, help="Codice conto (es. 6)")
    ap.add_argument("--bank-balance", required=True, help="Saldo banca ritenuto corretto (es. 4789,36)")
    ap.add_argument("--enc", help="File .enc")
    ap.add_argument("--key", help="File .chiave .key")
    ap.add_argument("--no-pdf", action="store_true", help="Non generare il file PDF")
    ap.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Percorso PDF (default: diagnostico_saldo_<codice>_YYYYMMDD.pdf nella root del repo)",
    )
    ap.add_argument("--max-rows", type=int, default=90, help="Max righe per tabella annulli/+app nel PDF (default 90)")
    args = ap.parse_args()

    try:
        bank = _parse_bank_balance(args.bank_balance)
    except (InvalidOperation, ValueError):
        print("Saldo banca non numerico.", file=sys.stderr)
        return 2

    enc_p, key_p = _resolve_db_enc_key(args)
    if enc_p is None or key_p is None:
        print("Specificare --enc e --key oppure configurare data_workspace (cartella dati).", file=sys.stderr)
        return 3
    if not enc_p.is_file() or not key_p.is_file():
        print("File .enc o .key non trovato.", file=sys.stderr)
        return 4

    db = load_encrypted_db(enc_p, key_p)
    if not db:
        print("Decifratura fallita.", file=sys.stderr)
        return 5

    yb = latest_year_bucket(db)
    if not yb:
        print("Nessun anno nel DB.", file=sys.stderr)
        return 6
    accounts = yb.get("accounts") or []
    n = len(accounts)
    if n == 0:
        print("Piano conti vuoto.", file=sys.stderr)
        return 7

    code = str(args.account_code).strip()
    idx = account_column_index_in_latest_chart(accounts, code)
    acc_row = accounts[idx] if 0 <= idx < len(accounts) else None
    acc_name = str((acc_row or {}).get("name") or "") if acc_row else ""

    today = date.today().isoformat()[:10]
    la = legacy_absolute_account_amounts(db, n)
    new_fx = compute_new_records_effect(db)
    canc = compute_cancelled_imported_records_balance_adjustment(db, cutoff_date_iso=today)
    edit_adj = compute_imported_active_records_edit_balance_adjustment(db)
    hyb_vec = hybrid_absolute_balances_for_saldi(db, today_cancel_cutoff_iso=today)
    if hyb_vec is None or len(hyb_vec) != n:
        print("hybrid_absolute_balances_for_saldi non valido.", file=sys.stderr)
        return 8

    leg = la[idx] if la is not None and idx < len(la) else None
    app = new_fx[idx] if idx < len(new_fx) else Decimal("0")
    can = canc[idx] if idx < len(canc) else Decimal("0")
    ed = edit_adj[idx] if idx < len(edit_adj) else Decimal("0")
    hyb = hyb_vec[idx]
    pre_twin = (leg if leg is not None else Decimal("0")) + app + can + ed
    gap = hyb - bank
    delta_legacy = bank - hyb

    tk = import_cancel_twin_balance_keys(db)
    aff: set[int] = set()
    twin_note = ""
    if tk:
        aff = _indices_touched_by_import_twin_actives(db, tk)
        if idx in aff:
            twin_note = "Colonna nel saldo finale sostituita da replay senza gemello attivo (twin import)."

    bank_delta_from_legacy = bank - leg if leg is not None else None
    m_total = app + can + ed
    excess_pipeline = (m_total - (bank_delta_from_legacy)) if bank_delta_from_legacy is not None else None

    latest_year = max(y["year"] for y in db["years"])
    y_ref = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    ls_file = ""
    if isinstance(y_ref, dict):
        ls = y_ref.get("legacy_saldi")
        if isinstance(ls, dict):
            ls_file = str(ls.get("source_file") or "")

    cancelled_rows: list[tuple[str, str, str, str]] = []
    for yd in db.get("years") or []:
        y_host = int(yd.get("year", 0) or 0)
        if y_host > latest_year:
            continue
        for rec in yd.get("records") or []:
            if not rec.get("is_cancelled"):
                continue
            if not (rec.get("raw_record") or "").strip():
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            y = int(rec.get("year", 0) or 0)
            if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
                continue
            cvec = _record_contribution_to_balance_vector(rec, accounts, n)
            if idx >= len(cvec) or cvec[idx] == 0:
                continue
            amt = rec.get("amount_eur")
            note = (rec.get("note") or "")[:70]
            cancelled_rows.append(
                (str(y_host), str(rec.get("date_iso") or ""), str(amt), _pdf_safe(note))
            )
    cancelled_rows.sort(key=lambda x: (x[0], x[1]))

    app_rows: list[tuple[str, str, str, str]] = []
    for yd in db.get("years") or []:
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled"):
                continue
            if (rec.get("raw_record") or "").strip():
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            y = int(yd.get("year", 0) or 0)
            if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
                continue
            cvec = _record_contribution_to_balance_vector(rec, accounts, n)
            if idx >= len(cvec) or cvec[idx] == 0:
                continue
            amt = rec.get("amount_eur")
            note = (rec.get("note") or "")[:70]
            app_rows.append((str(y), str(rec.get("date_iso") or ""), str(amt), _pdf_safe(note)))
    app_rows.sort(key=lambda x: (x[0], x[1]))

    lines_out: list[str] = []
    lines_out.append("=== Diagnostico saldo ibrido vs banca ===")
    lines_out.append(f"File: {enc_p}")
    lines_out.append(f"Data calcolo (cutoff annulli): {today}")
    lines_out.append(f"Conto: codice={code} nome={acc_name} indice_colonna={idx}")
    if ls_file:
        lines_out.append(f"legacy_saldi source (anno piano {PLAN_REFERENCE_YEAR}): {ls_file}")
    lines_out.append(f"Saldo banca (immissione): {format_euro_it(bank)} EUR")
    lines_out.append(f"Saldo ibrido (footer):      {format_euro_it(hyb)} EUR")
    lines_out.append(f"Scarto (ibrido - banca):    {format_euro_it(gap)} EUR")
    lines_out.append(f"Delta su legacy_saldi stesso conto per azzerare scarto (sommare a *sld* in DB): {format_euro_it(delta_legacy)} EUR")
    if leg is not None:
        lines_out.append(f"Legacy *sld* (base):         {format_euro_it(leg)} EUR")
        lines_out.append(f"+app:                        {format_euro_it(app)} EUR")
        lines_out.append(f"+annulli import:             {format_euro_it(can)} EUR")
        lines_out.append(f"+edit .dat:                  {format_euro_it(ed)} EUR")
        lines_out.append(f"Somma L+M (pre twin):        {format_euro_it(pre_twin)} EUR")
        if excess_pipeline is not None:
            lines_out.append(f"Banca - L (delta implicite movimenti): {format_euro_it(bank_delta_from_legacy)} EUR")
            lines_out.append(f"M - (Banca-L) eccesso pipeline vs banca: {format_euro_it(excess_pipeline)} EUR")
    if twin_note:
        lines_out.append(twin_note)
    lines_out.append(f"Righe annulli import su colonna: {len(cancelled_rows)}")
    lines_out.append(f"Righe +app su colonna:           {len(app_rows)}")
    print("\n".join(lines_out))

    if args.no_pdf:
        return 0

    pdf_path = (
        args.pdf.expanduser().resolve()
        if args.pdf is not None
        else ROOT / f"diagnostico_saldo_{code}_{date.today().strftime('%Y%m%d')}.pdf"
    )

    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        print("PDF: installare fpdf2 (pip install -r requirements.txt).", file=sys.stderr)
        return 9

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.multi_cell(
        0,
        8,
        _pdf_safe("Diagnostico saldo ibrido vs banca"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.set_font("Helvetica", "", 9)
    pdf.ln(2)

    def add_para(text: str, bold: bool = False) -> None:
        pdf.set_font("Helvetica", "B" if bold else "", 9)
        pdf.multi_cell(
            0,
            4.5,
            _pdf_safe(text),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.set_font("Helvetica", "", 9)

    add_para(f"Generato: {today}   DB: {enc_p.name}", False)
    add_para(f"Conto codice {code} - {acc_name} (colonna {idx})", False)
    if ls_file:
        add_para(f"*sld* file riferimento (piano {PLAN_REFERENCE_YEAR}): {ls_file}", False)
    pdf.ln(2)

    add_para("Riepilogo numerico", True)
    rows = [
        ("Saldo banca (input)", format_euro_it(bank) + " EUR"),
        ("Saldo ibrido (footer app)", format_euro_it(hyb) + " EUR"),
        ("Scarto ibrido - banca", format_euro_it(gap) + " EUR"),
        (
            "Delta da sommare a legacy_saldi per conto (bump)",
            format_euro_it(delta_legacy) + " EUR",
        ),
    ]
    if leg is not None:
        rows.extend(
            [
                ("Legacy *sld* L", format_euro_it(leg) + " EUR"),
                ("+app", format_euro_it(app) + " EUR"),
                ("+annulli import", format_euro_it(can) + " EUR"),
                ("+edit .dat", format_euro_it(ed) + " EUR"),
                ("L + M (pre twin)", format_euro_it(pre_twin) + " EUR"),
            ]
        )
        if bank_delta_from_legacy is not None and excess_pipeline is not None:
            rows.append(
                ("Banca - L (mov. implicite)", format_euro_it(bank_delta_from_legacy) + " EUR")
            )
            rows.append(
                ("M - (Banca-L) vs pipeline", format_euro_it(excess_pipeline) + " EUR")
            )
    for k, v in rows:
        pdf.set_x(pdf.l_margin)
        pdf.cell(95, 5, _pdf_safe(k), border=0)
        pdf.cell(0, 5, _pdf_safe(v), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    if twin_note:
        add_para(twin_note, True)
        pdf.ln(1)
    add_para(
        "Interpretazione: se lo scarto e' solo errore di baseline *sld*, il bump con --delta uguale al "
        "'Delta da sommare a legacy_saldi' (con app chiusa) allinea il footer alla banca senza toccare i movimenti. "
        "Se l'eccesso pipeline e' diverso da zero, conviene audit sulle tabelle sotto prima del bump.",
        False,
    )
    pdf.ln(3)

    max_r = max(8, min(int(args.max_rows), 200))

    def table_block(title: str, headers: tuple[str, ...], data: list[tuple[str, ...]]) -> None:
        pdf.add_page()
        add_para(title, True)
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 7)
        col_w = (pdf.w - pdf.l_margin - pdf.r_margin) / len(headers)
        for i, h in enumerate(headers):
            pdf.cell(col_w, 4, _pdf_safe(h), border=1)
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 7)
        shown = 0
        for row in data:
            if shown >= max_r:
                break
            for i, cell in enumerate(row):
                pdf.cell(col_w, 4, _pdf_safe(cell)[:48], border=1)
            pdf.ln(4)
            shown += 1
        if len(data) > max_r:
            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(
                0,
                4,
                _pdf_safe(f"... altre {len(data) - max_r} righe (usare --max-rows per piu' righe)."),
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    table_block(
        f"Annulli import con effetto su conto {code} (N={len(cancelled_rows)})",
        ("Anno", "Data", "Importo annullo", "Nota"),
        [(a, b, c, d) for a, b, c, d in cancelled_rows],
    )
    table_block(
        f"Righe solo app con effetto su conto {code} (N={len(app_rows)})",
        ("Anno", "Data", "Importo", "Nota"),
        [(a, b, c, d) for a, b, c, d in app_rows],
    )

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(pdf_path))
    print(f"\nPDF scritto: {pdf_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
