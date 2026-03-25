#!/usr/bin/env python3
from __future__ import annotations

import html as html_module
import json
import os
import calendar
import platform
import subprocess
import sys
import time
import tempfile
import tkinter as tk
import webbrowser
from collections.abc import Callable
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

# Inserimento griglia a lotti: migliaia di righe × 3 Treeview bloccano il main thread (macOS: beach ball).
MOVEMENTS_INSERT_BATCH = 400

# TODO (aggiunta / gestione conti): definire e applicare un limite massimo di conti attivi
# (coerente con DB, footer saldi, stampa, griglia). Oggi non c'è un tetto applicato nel codice.

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


def compute_balances_from_2022_asof(db: dict, *, cutoff_date_iso: str) -> tuple[int, list[str], list[Decimal]]:
    """
    Come `compute_balances_from_2022`, ma considera solo registrazioni con `date_iso <= cutoff_date_iso`.
    Utile per "Saldi alla data di oggi" (escludendo date future).
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
        r_date = str(rec.get("date_iso", ""))
        if r_date and r_date > cutoff_date_iso:
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


def _print_balances_native_macos(build_html: Callable[[float], str]) -> bool:
    """Stampa con dialog nativo macOS (AppKit). Sempre A4 verticale; tabella lunga → pagine successive.

    ``build_html(iw)`` riceve la larghezza in punti dell'area testo (``NSPrintInfo.imageablePageBounds``).

    Nota documentazione Apple / pratica: ``NSAttributedString.initWithHTML`` non rende HTML come un browser;
    larghezze tabella in % spesso falliscono. Usiamo ``colgroup`` e ``width`` della tabella in **punti** calcolati
    da ``iw``, più ``clipsToBounds = NO`` sulla vista. Per layout tabellare completo l'API consigliata è
    ``NSTextTable`` (non usata qui). Allineamento **verticale** del testo in cella: ``vertical-align: middle`` nel CSS.
    Larghezza layout ``iw_layout < iw`` (area stampabile): stesso valore per ``build_html`` e per
    ``NSTextContainer.setContainerSize_``, con ``textContainerInset`` orizzontale aumentato di metà differenza così
    il blocco resta centrato nell’area immagine e non viene tagliato a destra. Sul wrapper HTML resta il padding
    simmetrico (``margin-right`` sulle tabelle è inaffidabile).
    """
    try:
        from AppKit import (
            NSApplication,
            NSAttributedString,
            NSData,
            NSMakeRect,
            NSPrintInfo,
            NSPrintOperation,
            NSTextView,
        )
        from Foundation import NSSize
    except ImportError:
        return False
    try:
        app = NSApplication.sharedApplication()
        try:
            app.activateIgnoringOtherApps_(True)
        except Exception:
            pass

        # A4 verticale + margini espliciti; calcolare iw *prima* dell'HTML per pt espliciti nel markup.
        _mm_to_pt = 72.0 / 25.4
        _margin_pt = 7.0 * _mm_to_pt
        pinfo = NSPrintInfo.sharedPrintInfo().copy()
        pinfo.setOrientation_(0)
        try:
            pinfo.setVerticallyCentered_(False)
        except Exception:
            pass
        try:
            pinfo.setHorizontallyCentered_(False)
        except Exception:
            pass
        try:
            pinfo.setPaperSize_(NSSize(595, 842))
        except Exception:
            pass
        try:
            pinfo.setLeftMargin_(_margin_pt)
            pinfo.setRightMargin_(_margin_pt)
            pinfo.setTopMargin_(_margin_pt)
            pinfo.setBottomMargin_(_margin_pt)
        except Exception:
            pass
        try:
            ib = pinfo.imageablePageBounds()
            ox = float(ib.origin.x)
            oy = float(ib.origin.y)
            iw = float(ib.size.width)
            ih = float(ib.size.height)
            ps = pinfo.paperSize()
            paper_w = float(ps.width)
            paper_h = float(ps.height)
        except Exception:
            ox, oy, iw, ih = 56.0, 56.0, 483.0, 728.0
            paper_w, paper_h = 595.0, 842.0
        iw = max(200.0, iw)
        ih = max(200.0, ih)
        paper_w = max(200.0, paper_w)
        paper_h = max(200.0, paper_h)
        # NSTextView è flipped: inset alto = distanza dal bordo superiore del foglio all'area stampabile.
        # Ridurre la larghezza del container rispetto a ``iw`` e spostare leggermente l’inset a destra centra il
        # contenuto nella fascia stampabile; altrimenti TextKit+HTML possono disegnare ~qualche pt oltre ``iw``.
        # Banda vs area immagine (initWithHTML + bordo tabella): riduzione ampia per simmetria margini e linea verticale finale.
        _iw_trim_pt = 84.0
        iw_layout = max(200.0, iw - _iw_trim_pt)
        inset_x_pad = (iw - iw_layout) / 2.0
        left_inset = ox + inset_x_pad
        top_inset = paper_h - oy - ih

        html_utf8 = build_html(iw_layout)
        raw = html_utf8.encode("utf-8")
        nsdata = NSData.dataWithBytes_length_(raw, len(raw))
        parsed = NSAttributedString.alloc().initWithHTML_documentAttributes_(nsdata, None)
        if isinstance(parsed, tuple):
            attr, _doc_attrs = parsed
        else:
            attr = parsed
        if attr is None or attr.length() == 0:
            return False

        # Altezza iniziale ampia per il layout; poi stringiamo all'altezza reale del contenuto
        # per evitare una seconda pagina vuota.
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, paper_w, max(paper_h * 40.0, 4000.0)))
        tv.setEditable_(False)
        try:
            tv.setTextContainerInset_((left_inset, top_inset))
        except Exception:
            pass
        try:
            tv.textContainer().setLineFragmentPadding_(0.0)
        except Exception:
            pass
        try:
            tv.textContainer().setWidthTracksTextView_(False)
            tv.textContainer().setContainerSize_(NSSize(iw_layout, 1.0e7))
        except Exception:
            pass
        try:
            tv.setClipsToBounds_(False)
        except Exception:
            pass
        tv.textStorage().setAttributedString_(attr)
        try:
            lm = tv.layoutManager()
            tc = tv.textContainer()
            lm.ensureLayoutForTextContainer_(tc)
            used = lm.usedRectForTextContainer_(tc)
            h_need = top_inset + float(used.origin.y + used.size.height) + 12.0
            if h_need < 40.0:
                h_need = top_inset + ih
            tv.setFrame_(NSMakeRect(0, 0, paper_w, max(40.0, h_need)))
        except Exception:
            tv.setFrame_(NSMakeRect(0, 0, paper_w, top_inset + ih))

        try:
            op = NSPrintOperation.printOperationWithView_printInfo_(tv, pinfo)
        except Exception:
            op = NSPrintOperation.printOperationWithView_(tv)
            if op is not None:
                op.setPrintInfo_(pinfo)
        if op is None:
            return False
        op.setShowsPrintPanel_(True)
        op.setShowsProgressPanel_(True)
        # runOperation() è NO se l'utente annulla: non aprire il fallback browser (HTML/PDF indesiderati).
        op.runOperation()
        return True
    except Exception:
        return False


def _print_balances_native_windows(html_utf8: str) -> bool:
    """
    Dialog di stampa Windows via Internet Explorer COM (ExecWB), se disponibile.
    Su Windows 11 IE può mancare: in quel caso ritorna False e si usa il fallback browser.
    """
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    tmp_path: str | None = None
    coinit = False
    ie = None
    try:
        try:
            pythoncom.CoInitialize()
            coinit = True
        except pythoncom.com_error:
            pass
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
            f.write(html_utf8)
            tmp_path = str(Path(f.name).resolve())
        url = Path(tmp_path).resolve().as_uri()
        ie = win32com.client.DispatchEx("InternetExplorer.Application")
        ie.Visible = 1
        ie.Navigate2(url)

        for _ in range(200):
            if not ie.Busy and int(ie.ReadyState) == 4:
                break
            time.sleep(0.1)
        else:
            return False
        # OLECMDID_PRINT = 6, OLECMDEXECOPT_PROMPTUSER = 1
        ie.ExecWB(6, 1)
        time.sleep(0.5)
        return True
    except Exception:
        return False
    finally:
        if ie is not None:
            try:
                ie.Quit()
            except Exception:
                pass
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
        if coinit:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _print_balances_windows_pywebview(html_utf8: str) -> bool:
    """
    Windows 10/11: dialog stampa via Edge WebView2 (pacchetto pywebview), in sottoprocesso
    separato per non bloccare Tk.
    """
    try:
        import webview  # noqa: F401
    except ImportError:
        return False
    worker = Path(__file__).resolve().parent / "webview_print_worker.py"
    if not worker.is_file():
        return False
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
            f.write(html_utf8)
            html_path = str(Path(f.name).resolve())
        subprocess.Popen(
            [sys.executable, str(worker), html_path],
            close_fds=False,
        )
        return True
    except Exception:
        return False


def _hex_to_rgb_triplet(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#").strip()
    if len(h) != 6:
        return (26, 26, 26)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _print_balances_windows_fpdf(snap: dict) -> bool:
    """Fallback Windows: PDF A4 verticale, tabella trasposta (4 colonne come HTML)."""
    try:
        from fpdf import FPDF
    except ImportError:
        return False
    names: list[str] = snap["names"]
    valuta: str = snap["valuta"]
    n = len(names)
    try:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Conti di casa", align="C", ln=1)
        pdf.set_font("Helvetica", "", 8)
        pdf.cell(0, 5, f"Data: {snap['date_it']}", align="C", ln=1)
        # Spazio verticale data → tabella (~5 mm sotto la data + ~6 mm prima della tabella, come HTML).
        pdf.ln(11)

        epw = pdf.epw
        _sh = 0.88
        tw = epw * _sh
        x_table = pdf.l_margin + (epw - tw) / 2.0
        w_conti = tw * 0.16
        w_amt = tw * 0.28
        line_h = (6.5 if n > 12 else 7.0) * _sh
        fs_head = round(7 * _sh, 2)
        fs_body = round(7 * _sh, 2)

        def amt_cell(amt: Decimal, w: float, *, bold: bool) -> None:
            fg = balance_amount_fg(amt)
            r, g, b = _hex_to_rgb_triplet(fg)
            pdf.set_text_color(r, g, b)
            pdf.set_font("Helvetica", "B" if bold else "", fs_body)
            pdf.cell(w, line_h, format_saldo_cell(valuta, amt), border=1, align="R")

        # Intestazione
        pdf.set_x(x_table)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", fs_head)
        pdf.cell(w_conti, line_h * 1.3, "Conti", border=1, align="L")
        pdf.set_font("Helvetica", "B", fs_head)
        pdf.cell(w_amt, line_h * 1.3, "Saldi oggi", border=1, align="C")
        pdf.set_font("Helvetica", "", fs_head)
        pdf.cell(w_amt, line_h * 1.3, "Differenze", border=1, align="C")
        pdf.set_font("Helvetica", "B", fs_head)
        pdf.cell(w_amt, line_h * 1.3, "Saldi assol.", border=1, align="C")
        pdf.ln(line_h * 1.3)

        for i, nm in enumerate(names):
            pdf.set_x(x_table)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "B", fs_body)
            show_nm = (nm or "").strip()[:10]
            pdf.cell(w_conti, line_h, show_nm, border=1, align="L")
            amt_cell(snap["amts_today"][i], w_amt, bold=True)
            amt_cell(snap["diffs"][i], w_amt, bold=False)
            amt_cell(snap["amts_abs"][i], w_amt, bold=True)
            pdf.ln(line_h)

        pdf.set_fill_color(240, 240, 240)
        pdf.set_x(x_table)
        pdf.set_font("Helvetica", "B", fs_body)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(w_conti, line_h, "TOTALE", border=1, align="L", fill=True)
        for amt, bold in (
            (snap["total_today"], True),
            (snap["total_diff"], False),
            (snap["total_abs"], True),
        ):
            fg = balance_amount_fg(amt)
            r, g, b = _hex_to_rgb_triplet(fg)
            pdf.set_text_color(r, g, b)
            pdf.set_font("Helvetica", "B" if bold else "", fs_body)
            pdf.cell(w_amt, line_h, format_saldo_cell(valuta, amt), border=1, align="R", fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(line_h)

        fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="saldi_")
        os.close(fd)
        pdf.output(out_path)
        os.startfile(out_path)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def show_record_in_movements_grid(rec: dict) -> bool:
    """Dotazione iniziale: visibile solo per il 1990; resto sempre visibile."""
    year = int(rec.get("year") or 0)
    cat = str(rec.get("category_code", "")).strip()
    if cat == "0" and year != 1990:
        return False
    return True


def record_legacy_stable_key(rec: dict) -> str:
    """Chiave univoca del record nel DB unificato (come in import legacy)."""
    k = rec.get("legacy_registration_key")
    if isinstance(k, str) and k.strip():
        return k
    return f"{rec.get('year', '')}:{rec.get('source_folder', '')}:{rec.get('source_file', '')}:{rec.get('source_index', '')}"


def unified_registration_sequence_map(records_sorted: list[dict]) -> dict[str, int]:
    """
    Progressivo globale 1..N su tutti i record nell'ordine di merge:
    anno → cartella → file → indice (stesso criterio della griglia).
    `legacy_registration_number` nel file .dat è solo l'indice dentro l'anno e si ripete ogni anno.
    """
    return {record_legacy_stable_key(r): i for i, r in enumerate(records_sorted, start=1)}


def filter_and_sort_movements_for_grid(
    records_canonical: list[dict],
    reg_seq_map: dict[str, int],
    *,
    order_by_date: bool,
    exclude_future_dates: bool,
    backward: bool,
    date_from_iso: str | None = None,
    date_to_iso: str | None = None,
) -> list[dict]:
    """
    Applica filtro date future + (opzionale) filtro intervallo date e ordinamento richiesto dalla pagina Movimenti.
    - order_by_date: True = per data, False = per numero di registrazione globale.
    - exclude_future_dates: True = nasconde registrazioni con data > oggi.
    - backward: True = dalla più recente / numero più alto; False = dalla più lontana / più basso.
    - date_from_iso/date_to_iso: se presenti, restringono per intervallo inclusivo su `date_iso` (YYYY-MM-DD).
    """
    today = date.today().isoformat()
    d_from = date_from_iso or None
    d_to = date_to_iso or None
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from
    pool: list[dict] = []
    for r in records_canonical:
        if not show_record_in_movements_grid(r):
            continue
        r_date = str(r.get("date_iso", ""))
        if exclude_future_dates and r_date > today:
            continue
        if d_from and r_date < d_from:
            continue
        if d_to and r_date > d_to:
            continue
        pool.append(r)

    reg_key = lambda r: reg_seq_map[record_legacy_stable_key(r)]
    if order_by_date:
        pool.sort(key=lambda r: (str(r.get("date_iso", "")), reg_key(r)), reverse=backward)
    else:
        pool.sort(key=reg_key, reverse=backward)
    return pool


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
    # Avvio a finestra intera (massimizzata). Su macOS `state("zoomed")` può minimizzare:
    # usiamo invece la geometria a schermo.
    root.update_idletasks()
    if platform.system() == "Darwin":
        # Su macOS la geometria a schermo può portare a comportamenti strani (finestra che collassa).
        # Usiamo fullscreen nativo e poi forziamo deiconify/lift.
        try:
            root.attributes("-fullscreen", True)
        except Exception:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            root.geometry(f"{sw}x{sh}+0+0")

        def _ensure_visible() -> None:
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
            except Exception:
                pass

        root.after(50, _ensure_visible)
    else:
        root.geometry("1200x760")
        try:
            root.state("zoomed")
        except Exception:
            pass

    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    # Tab notebook: testo in bold (selettori pagine).
    ttk.Style(root).configure("TNotebook.Tab", font=("TkDefaultFont", 13, "bold"))

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

    def _on_tab_changed(_e: tk.Event) -> None:
        # Quando si torna alla scheda Movimenti, riallinea visibilità e tendine.
        try:
            if notebook.index(notebook.select()) == 0:
                refresh_movement_filter_button_styles()
                refresh_date_controls_visibility()
        except Exception:
            pass

    notebook.bind("<<NotebookTabChanged>>", _on_tab_changed)

    # Preselezione (sei controlli) vs valori applicati alla griglia (solo con «Cerca»).
    filter_order_preview_var = tk.StringVar(value="date")
    filter_future_preview_var = tk.StringVar(value="include")
    filter_direction_preview_var = tk.StringVar(value="backward")
    filter_order_applied_var = tk.StringVar(value="date")
    filter_future_applied_var = tk.StringVar(value="include")
    filter_direction_applied_var = tk.StringVar(value="backward")

    # Filtri testuali (solo Ricerca per data): preview vs applicato (solo con «Cerca»).
    text_category_preview_var = tk.StringVar(value="")
    text_account_preview_var = tk.StringVar(value="")
    text_cheque_preview_var = tk.StringVar(value="")
    text_note_preview_var = tk.StringVar(value="")
    text_category_applied_var = tk.StringVar(value="")
    text_account_applied_var = tk.StringVar(value="")
    text_cheque_applied_var = tk.StringVar(value="")
    text_note_applied_var = tk.StringVar(value="")

    # Ricerca per registrazione: limiti progressivo (preview vs applicato).
    reg_preset_preview_var = tk.StringVar(value="last_12")
    reg_preset_applied_var = tk.StringVar(value="last_12")
    reg_from_preview_var = tk.StringVar(value="")
    reg_to_preview_var = tk.StringVar(value="")
    reg_from_applied_var = tk.StringVar(value="")
    reg_to_applied_var = tk.StringVar(value="")

    # Intervallo date per «Ricerca per data»: preview (solo UI) vs applicato (solo con «Cerca»).
    date_preset_preview_var = tk.StringVar(value="last_12")
    date_preset_applied_var = tk.StringVar(value="last_12")
    date_from_preview_var = tk.StringVar(value="")
    date_to_preview_var = tk.StringVar(value="")
    date_from_applied_var = tk.StringVar(value="")
    date_to_applied_var = tk.StringVar(value="")
    _dataset_min_date: date | None = None
    _dataset_max_date: date | None = None
    _dataset_years_with_records: list[int] = []
    # Se l'utente modifica manualmente "Date a scelta" (calendar o campi),
    # evitiamo di sovrascrivere la scelta quando cambia Comprese/Escluse o direzione.
    date_custom_manual_override = False

    # Bounds dataset iniziali (per calcolare subito i preset default).
    try:
        d0 = cur_db()
        records0 = [r for y in d0.get("years", []) for r in y.get("records", [])]
        parsed0: list[date] = []
        for rr in records0:
            iso = str(rr.get("date_iso", "")).strip()
            if not iso:
                continue
            try:
                parsed0.append(date.fromisoformat(iso))
            except Exception:
                continue
        if parsed0:
            _dataset_min_date = min(parsed0)
            _dataset_max_date = max(parsed0)
            _dataset_years_with_records = sorted({d.year for d in parsed0})
        else:
            _dataset_min_date = date.today()
            _dataset_max_date = date.today()
            _dataset_years_with_records = [date.today().year]
    except Exception:
        _dataset_min_date = date.today()
        _dataset_max_date = date.today()
        _dataset_years_with_records = [date.today().year]

    filters_row = ttk.Frame(movimenti_frame)
    filters_row.pack(fill=tk.X, pady=(0, 4))

    filters_search_row = ttk.Frame(movimenti_frame)
    filters_search_row.pack(fill=tk.X, pady=(0, 8))

    # Riga controlli per Ricerca per registrazione (visibile solo in quella modalità)
    reg_controls_row = ttk.Frame(filters_search_row)
    reg_controls_row.pack(side=tk.LEFT, anchor=tk.W)
    reg_controls_row.pack_forget()

    filters_text_row = ttk.Frame(movimenti_frame)
    filters_text_row.pack(fill=tk.X, pady=(0, 10))

    # Riga filtri testuali (visibile solo in Ricerca per data)
    filters_text_inner = ttk.Frame(filters_text_row)
    filters_text_inner.pack(fill=tk.X, anchor=tk.W)

    # Zona filtri: testo in bold (etichette, entry, combobox, pulsanti).
    filter_ui_font = ("TkDefaultFont", 12, "bold")
    ttk.Style(root).configure("Filters.TLabel", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TEntry", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TCombobox", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TButton", font=filter_ui_font)

    _ALL_CATEGORIES_LABEL = "Tutte"
    _ALL_ACCOUNTS_LABEL = "Tutti"

    ttk.Label(filters_text_inner, text="Categoria", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    category_entry = ttk.Combobox(
        filters_text_inner,
        textvariable=text_category_preview_var,
        state="readonly",
        width=22,
        values=("",),
        style="Filters.TCombobox",
    )
    category_entry.pack(side=tk.LEFT, padx=(0, 14))

    ttk.Label(filters_text_inner, text="Conto", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    account_entry = ttk.Combobox(
        filters_text_inner,
        textvariable=text_account_preview_var,
        state="readonly",
        width=22,
        values=("",),
        style="Filters.TCombobox",
    )
    account_entry.pack(side=tk.LEFT, padx=(0, 14))

    ttk.Label(filters_text_inner, text="Assegno", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    cheque_entry = ttk.Entry(
        filters_text_inner,
        textvariable=text_cheque_preview_var,
        width=18,
        style="Filters.TEntry",
    )
    cheque_entry.pack(side=tk.LEFT, padx=(0, 14))

    ttk.Label(filters_text_inner, text="Nota", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    note_entry = ttk.Entry(
        filters_text_inner,
        textvariable=text_note_preview_var,
        width=40,
        style="Filters.TEntry",
    )
    note_entry.pack(side=tk.LEFT, padx=(0, 0))

    clear_filters_btn = ttk.Button(filters_text_inner, text="Pulisci filtri", style="Filters.TButton")
    clear_filters_btn.pack(side=tk.LEFT, padx=(14, 0))

    # ---- UI Ricerca per registrazione (preset + range reg + conto) ----
    reg_controls_inner = ttk.Frame(reg_controls_row)
    reg_controls_inner.pack(fill=tk.X, anchor=tk.W)

    reg_btn_last12 = tk.Label(
        reg_controls_inner,
        text="Ultimi 12 mesi",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=8,
        pady=6,
    )
    reg_btn_all = tk.Label(
        reg_controls_inner,
        text="Intero periodo",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=8,
        pady=6,
    )
    reg_btn_last12.pack(side=tk.LEFT, padx=(0, 8))
    reg_btn_all.pack(side=tk.LEFT, padx=(0, 16))

    ttk.Label(reg_controls_inner, text="Dalla reg. #", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_from_entry = ttk.Entry(reg_controls_inner, textvariable=reg_from_preview_var, width=8, style="Filters.TEntry")
    reg_from_entry.pack(side=tk.LEFT, padx=(0, 14))

    ttk.Label(reg_controls_inner, text="Alla reg. #", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_to_entry = ttk.Entry(reg_controls_inner, textvariable=reg_to_preview_var, width=8, style="Filters.TEntry")
    reg_to_entry.pack(side=tk.LEFT, padx=(0, 18))

    ttk.Label(reg_controls_inner, text="Conto", style="Filters.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_account_entry = ttk.Combobox(
        reg_controls_inner,
        textvariable=text_account_preview_var,
        state="readonly",
        width=22,
        values=(_ALL_ACCOUNTS_LABEL,),
        style="Filters.TCombobox",
    )
    reg_account_entry.pack(side=tk.LEFT, padx=(0, 0))

    def _sorted_with_preferred(values: set[str], preferred: str) -> tuple[str, ...]:
        # Prefer match case-insensitive, ma restituisce la stringa originale presente nei dati.
        preferred_actual = None
        pref_l = preferred.lower()
        for v in values:
            if v.lower() == pref_l:
                preferred_actual = v
                break
        rest = sorted((v for v in values if v != preferred_actual), key=lambda s: s.lower())
        return ((preferred_actual,) if preferred_actual else tuple()) + tuple(rest)

    def refresh_category_account_dropdowns() -> None:
        """Popola le tendine con soli valori presenti nello scope date (preview)."""
        if filter_order_preview_var.get() != "date":
            return

        # Limiti scope dalle date in finestra (preview) + Comprese/Escluse.
        dmin = _parse_iso_to_date(date_from_preview_var.get())
        dmax = _parse_iso_to_date(date_to_preview_var.get())
        if not dmin or not dmax:
            # se non ancora pronte, lascia almeno opzione vuota
            category_entry.configure(values=(_ALL_CATEGORIES_LABEL,))
            account_entry.configure(values=(_ALL_ACCOUNTS_LABEL,))
            return
        if dmin > dmax:
            dmin, dmax = dmax, dmin

        # Rispetta Escluse date future (solo per scope).
        today = date.today()
        if filter_future_preview_var.get() == "exclude" and dmax > today:
            dmax = today
        if filter_future_preview_var.get() == "exclude" and dmin > today:
            dmin = today

        d = cur_db()
        accounts_by_year = year_accounts_map(d)
        categories_by_year = year_categories_map(d)
        records = [r for y in d["years"] for r in y["records"]]

        cats: set[str] = set()
        accs: set[str] = set()
        for r in records:
            try:
                r_date = date.fromisoformat(str(r.get("date_iso", "")))
            except Exception:
                continue
            if r_date < dmin or r_date > dmax:
                continue
            if not show_record_in_movements_grid(r):
                continue
            year = r.get("year")
            year_accounts = accounts_by_year.get(year, [])
            year_categories = categories_by_year.get(year, [])
            c = category_name_for_record(r, year_categories)
            a1 = account_name_for_record(r, year_accounts, "primary")
            a2 = account_name_for_record(r, year_accounts, "secondary")
            if c:
                cats.add(str(c).strip())
            if a1:
                accs.add(str(a1).strip())
            if a2:
                accs.add(str(a2).strip())

        cat_vals = (_ALL_CATEGORIES_LABEL,) + _sorted_with_preferred(cats, "Consumi ordinari")
        acc_vals = (_ALL_ACCOUNTS_LABEL,) + _sorted_with_preferred(accs, "Cassa")
        category_entry.configure(values=cat_vals)
        account_entry.configure(values=acc_vals)

        # Se la selezione corrente non è più valida, azzera.
        if not text_category_preview_var.get():
            text_category_preview_var.set(_ALL_CATEGORIES_LABEL)
        if not text_account_preview_var.get():
            text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)
        if (
            text_category_preview_var.get()
            and text_category_preview_var.get() != _ALL_CATEGORIES_LABEL
            and text_category_preview_var.get() not in cats
        ):
            text_category_preview_var.set(_ALL_CATEGORIES_LABEL)
        if (
            text_account_preview_var.get()
            and text_account_preview_var.get() != _ALL_ACCOUNTS_LABEL
            and text_account_preview_var.get() not in accs
        ):
            text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)

    records_frame = ttk.Frame(movimenti_frame, padding=8)
    records_frame.pack(fill=tk.BOTH, expand=True)

    search_title_var = tk.StringVar(value="")
    _PRINT_RICERCA_RED = "#c62828"
    _PRINT_RICERCA_RED_ACTIVE = "#8e0000"
    search_title_row = tk.Frame(records_frame, bg="#ffffff")
    btn_stampa_ricerca = tk.Label(
        search_title_row,
        text="Stampa ricerca",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=12,
        pady=4,
        bg=_PRINT_RICERCA_RED,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_stampa_ricerca.pack(side=tk.LEFT, padx=(0, 10))
    search_title_label = tk.Label(
        search_title_row,
        textvariable=search_title_var,
        font=("TkDefaultFont", 12, "bold"),
        fg="#1a1a1a",
        bg="#ffffff",
        anchor="w",
        justify="left",
    )
    search_title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    no_results_label = tk.Label(
        records_frame,
        text="Nessuna registrazione con questi filtri",
        font=("TkDefaultFont", 16, "bold"),
        fg="#444444",
        bg="#ffffff",
    )

    mov_style = ttk.Style(root)
    mov_style.configure(
        "MovGrid.Treeview",
        borderwidth=1,
        relief="solid",
        rowheight=22,
        background="#ffffff",
        fieldbackground="#ffffff",
        font=("TkDefaultFont", 11, "bold"),
    )
    mov_style.configure(
        "MovGridAmount.Treeview",
        borderwidth=1,
        relief="solid",
        rowheight=22,
        background="#ffffff",
        fieldbackground="#ffffff",
        font=("TkDefaultFont", 12, "bold"),
    )
    mov_style.configure(
        "MovGrid.Treeview.Heading",
        borderwidth=1,
        relief="flat",
        background="#ebebeb",
        foreground="#1a1a1a",
        font=("TkDefaultFont", 10, "bold"),
    )

    # Prima colonna `mov_pad` vuota (1px): su macOS la prima colonna dati ha bug/troncamenti; Reg è la seconda.
    # Solo `show=headings` (no colonna albero #0): così `anchor=e` su Reg allinea a destra correttamente.
    mov_cols = (
        "mov_pad",
        "reg_display",
        "date_it",
        "category_name",
        "account_primary_name",
        "account_primary_flags",
        "account_secondary_name",
        "account_secondary_flags",
        "cheque",
    )
    mov_tree = ttk.Treeview(
        records_frame,
        columns=mov_cols,
        show="tree",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    mov_tree.heading("mov_pad", text="")
    mov_tree.column("mov_pad", width=1, minwidth=1, stretch=False, anchor=tk.CENTER)
    mov_tree.heading("reg_display", text="Reg #", anchor="e")
    mov_tree.column("reg_display", width=62, anchor="e", stretch=False, minwidth=50)
    mov_tree.heading("date_it", text="Data", anchor="e")
    mov_tree.heading("category_name", text="Categoria", anchor="w")
    mov_tree.heading("account_primary_name", text="Dal conto", anchor="w")
    mov_tree.heading("account_primary_flags", text="")
    mov_tree.heading("account_secondary_name", text="al conto", anchor="w")
    mov_tree.heading("account_secondary_flags", text="")
    mov_tree.heading("cheque", text="Assegno")
    mov_tree.column("date_it", width=92, anchor="e", stretch=False, minwidth=80)
    mov_tree.column("category_name", width=160, anchor="w", stretch=True, minwidth=80)
    mov_tree.column("account_primary_name", width=130, anchor="w", stretch=True, minwidth=70)
    mov_tree.column("account_primary_flags", width=36, anchor=tk.CENTER, stretch=False, minwidth=32)
    mov_tree.column("account_secondary_name", width=150, anchor="w", stretch=True, minwidth=70)
    mov_tree.column("account_secondary_flags", width=36, anchor=tk.CENTER, stretch=False, minwidth=32)
    mov_tree.column("cheque", width=78, anchor=tk.CENTER, stretch=False, minwidth=60)

    mov_tree.tag_configure("stripe0", background="#f7f7f7")
    mov_tree.tag_configure("stripe1", background="#ffffff")

    def refresh_search_title() -> None:
        mode = filter_order_applied_var.get()
        future_txt = "comprese date future" if filter_future_applied_var.get() == "include" else "escluse date future"
        dir_txt = (
            "all'indietro dalla più recente"
            if filter_direction_applied_var.get() == "backward"
            else "in avanti dalla più lontana"
        )
        if mode == "date":
            s_from = to_italian_date(date_from_applied_var.get())
            s_to = to_italian_date(date_to_applied_var.get())
            date_txt = f"dalla data {s_from} alla data {s_to}"
            mode_txt = "Ricerca per data"
        else:
            scope_from, scope_to = _scope_dates_for_registration(reg_preset_applied_var.get())
            date_txt = f"dalla data {to_italian_date(scope_from)} alla data {to_italian_date(scope_to)}"
            mode_txt = "Ricerca per registrazione"

        parts: list[str] = [mode_txt, future_txt, dir_txt, date_txt]

        if mode == "registration":
            rf = (reg_from_applied_var.get() or "").strip()
            rt = (reg_to_applied_var.get() or "").strip()
            if rf and rt:
                parts.append(f"dalla reg. # {rf} alla reg. # {rt}")

        cat = (text_category_applied_var.get() or "").strip()
        acc = (text_account_applied_var.get() or "").strip()
        chq = (text_cheque_applied_var.get() or "").strip()
        note = (text_note_applied_var.get() or "").strip()
        if mode == "date" and cat and cat != _ALL_CATEGORIES_LABEL:
            parts.append(f"per la categoria {cat}")
        if acc and acc != _ALL_ACCOUNTS_LABEL:
            parts.append(f"per il conto {acc}")
        if mode == "date" and chq:
            parts.append(f"per l'assegno {chq}")
        if mode == "date" and note:
            parts.append(f"per la nota {note}")

        s = ", ".join(parts).strip()
        if s and not s.endswith("."):
            s += "."
        search_title_var.set(s)

    # Separatori verticali nel primo Treeview (mov_tree).
    # ttk.Treeview non supporta vere gridline verticali; overlay con Frame 1px.
    mov_tree_vlines: list[tk.Frame] = []

    def _ensure_mov_tree_vlines() -> None:
        nonlocal mov_tree_vlines
        if mov_tree_vlines:
            return
        for _ in range(8):  # confini tra 9 colonne (mov_pad..flags2), escludiamo bordo finale
            ln = tk.Frame(mov_tree, bg="#c0c0c0", width=1, highlightthickness=0)
            mov_tree_vlines.append(ln)

    def _position_mov_tree_vlines(_e: tk.Event | None = None) -> None:
        _ensure_mov_tree_vlines()
        # confini dopo queste colonne:
        cols = [
            "mov_pad",
            "reg_display",
            "date_it",
            "category_name",
            "account_primary_name",
            "account_primary_flags",
            "account_secondary_name",
            "account_secondary_flags",
            # cheque (ultimo) -> niente linea dopo
        ]
        x = 0
        # piccolo offset per compensare bordo interno su macOS
        x_offset = 1
        for i, cid in enumerate(cols):
            try:
                w = int(mov_tree.column(cid, "width"))
            except Exception:
                w = 0
            x += w
            ln = mov_tree_vlines[i]
            ln.place(x=x + x_offset, y=0, relheight=1.0)
            ln.lift()

    mov_tree.bind("<Configure>", _position_mov_tree_vlines, add=True)
    root.after(0, _position_mov_tree_vlines)

    # Importo (colori) prima di Nota: Treeview separato perché i tag colore valgono per riga intera.
    amt_tree = ttk.Treeview(
        records_frame,
        columns=("amount_eur",),
        show="tree",
        selectmode="browse",
        style="MovGridAmount.Treeview",
    )
    amt_tree.heading("amount_eur", text="Importo", anchor="e")
    amt_tree.column("amount_eur", width=128, anchor="e", stretch=False, minwidth=96)
    amt_tree.tag_configure("neg", foreground=COLOR_AMOUNT_NEG)
    amt_tree.tag_configure("pos", foreground=COLOR_AMOUNT_POS)
    amt_tree.tag_configure("stripe0", background="#f7f7f7")
    amt_tree.tag_configure("stripe1", background="#ffffff")

    note_tree = ttk.Treeview(
        records_frame,
        columns=("note",),
        show="tree",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    note_tree.heading("note", text="Nota", anchor="w")
    note_tree.column("note", width=280, anchor="w", stretch=True, minwidth=120)
    note_tree.tag_configure("stripe0", background="#f7f7f7")
    note_tree.tag_configure("stripe1", background="#ffffff")

    mov_tree.column("#0", width=0, minwidth=0, stretch=False)
    amt_tree.column("#0", width=0, minwidth=0, stretch=False)
    note_tree.column("#0", width=0, minwidth=0, stretch=False)

    # Intestazioni custom (su macOS ttk può ignorare l'allineamento delle headings).
    header_bg = "#ebebeb"
    header_fg = "#1a1a1a"
    header_font = ("TkDefaultFont", 10, "bold")
    header_row = tk.Frame(records_frame, bg=header_bg)
    mov_hdr = tk.Frame(header_row, bg=header_bg)
    amt_hdr = tk.Frame(header_row, bg=header_bg)
    note_hdr = tk.Frame(header_row, bg=header_bg)
    # Canale separatore: permette di posizionare la linea leggermente più a sinistra/destra.
    _SEP_CH_W = 6
    hdr_sep_1 = tk.Frame(header_row, bg=header_bg, width=_SEP_CH_W)
    hdr_sep_2 = tk.Frame(header_row, bg=header_bg, width=_SEP_CH_W)
    hdr_sep_1_line = tk.Frame(hdr_sep_1, bg="#c0c0c0", width=1)
    hdr_sep_2_line = tk.Frame(hdr_sep_2, bg="#c0c0c0", width=1)

    # La riga header deve seguire la griglia principale (mov / amt / note).
    header_row.grid_columnconfigure(0, weight=1, minsize=120)  # mov_hdr
    header_row.grid_columnconfigure(1, weight=0, minsize=_SEP_CH_W)    # sep
    header_row.grid_columnconfigure(2, weight=0, minsize=104)  # amt_hdr
    header_row.grid_columnconfigure(3, weight=0, minsize=_SEP_CH_W)    # sep
    header_row.grid_columnconfigure(4, weight=1, minsize=100)  # note_hdr

    # Mov header columns (pixel widths = come Treeview)
    mov_hdr.grid_columnconfigure(0, minsize=1)    # mov_pad
    mov_hdr.grid_columnconfigure(1, minsize=62)   # Reg #
    mov_hdr.grid_columnconfigure(2, minsize=92)   # Data
    mov_hdr.grid_columnconfigure(3, weight=1, minsize=160)  # Categoria
    mov_hdr.grid_columnconfigure(4, weight=1, minsize=130)  # Dal conto
    mov_hdr.grid_columnconfigure(5, minsize=36)   # flags
    mov_hdr.grid_columnconfigure(6, weight=1, minsize=150)  # al conto
    mov_hdr.grid_columnconfigure(7, minsize=36)   # flags2
    mov_hdr.grid_columnconfigure(8, minsize=78)   # Assegno

    tk.Label(mov_hdr, text="", bg=header_bg, fg=header_fg, font=header_font).grid(row=0, column=0, sticky="ew")
    tk.Label(mov_hdr, text="Reg #", bg=header_bg, fg=header_fg, font=header_font, anchor="center").grid(row=0, column=1, sticky="ew")
    tk.Label(mov_hdr, text="Data", bg=header_bg, fg=header_fg, font=header_font, anchor="center").grid(row=0, column=2, sticky="ew")
    tk.Label(mov_hdr, text="Categoria", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(row=0, column=3, sticky="ew")
    tk.Label(mov_hdr, text="Dal conto", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(row=0, column=4, sticky="ew")
    tk.Label(mov_hdr, text="", bg=header_bg, fg=header_fg, font=header_font).grid(row=0, column=5, sticky="ew")
    tk.Label(mov_hdr, text="al conto", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(row=0, column=6, sticky="ew")
    tk.Label(mov_hdr, text="", bg=header_bg, fg=header_fg, font=header_font).grid(row=0, column=7, sticky="ew")
    tk.Label(mov_hdr, text="Assegno", bg=header_bg, fg=header_fg, font=header_font, anchor="center").grid(row=0, column=8, sticky="ew")

    # Linee verticali in intestazione (mov_hdr): overlay, coerenti con le larghezze del Treeview.
    mov_hdr_vlines: list[tk.Frame] = []

    def _ensure_mov_hdr_vlines() -> None:
        nonlocal mov_hdr_vlines
        if mov_hdr_vlines:
            return
        for _ in range(8):
            mov_hdr_vlines.append(tk.Frame(mov_hdr, bg="#c0c0c0", width=1, highlightthickness=0))

    def _position_mov_hdr_vlines(_e: tk.Event | None = None) -> None:
        _ensure_mov_hdr_vlines()
        cols = [
            "mov_pad",
            "reg_display",
            "date_it",
            "category_name",
            "account_primary_name",
            "account_primary_flags",
            "account_secondary_name",
            "account_secondary_flags",
        ]
        x = 0
        x_offset = 1
        for i, cid in enumerate(cols):
            try:
                w = int(mov_tree.column(cid, "width"))
            except Exception:
                w = 0
            x += w
            ln = mov_hdr_vlines[i]
            ln.place(x=x + x_offset, y=0, relheight=1.0)
            ln.lift()

    mov_hdr.bind("<Configure>", _position_mov_hdr_vlines, add=True)
    root.after(0, _position_mov_hdr_vlines)

    amt_hdr.grid_columnconfigure(0, weight=1, minsize=128)
    tk.Label(amt_hdr, text="Importo", bg=header_bg, fg=header_fg, font=header_font, anchor="e").grid(row=0, column=0, sticky="ew")

    note_hdr.grid_columnconfigure(0, weight=1, minsize=280)
    tk.Label(note_hdr, text="Nota", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(row=0, column=0, sticky="ew")

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

    def _selection_tuple(tree: ttk.Treeview) -> tuple[str, ...]:
        return tuple(tree.selection())

    def sync_selection_mov(_event: tk.Event | None = None) -> None:
        nonlocal _sel_sync
        if _sel_sync:
            return
        _sel_sync = True
        try:
            sel = mov_tree.selection()
            if sel:
                if _selection_tuple(amt_tree) != sel:
                    amt_tree.selection_set(*sel)
                if _selection_tuple(note_tree) != sel:
                    note_tree.selection_set(*sel)
            else:
                if amt_tree.selection():
                    _clear_selection(amt_tree)
                if note_tree.selection():
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
                if _selection_tuple(mov_tree) != sel:
                    mov_tree.selection_set(*sel)
                if _selection_tuple(note_tree) != sel:
                    note_tree.selection_set(*sel)
            else:
                if mov_tree.selection():
                    _clear_selection(mov_tree)
                if note_tree.selection():
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
                if _selection_tuple(mov_tree) != sel:
                    mov_tree.selection_set(*sel)
                if _selection_tuple(amt_tree) != sel:
                    amt_tree.selection_set(*sel)
            else:
                if mov_tree.selection():
                    _clear_selection(mov_tree)
                if amt_tree.selection():
                    _clear_selection(amt_tree)
        finally:
            _sel_sync = False

    mov_tree.bind("<<TreeviewSelect>>", sync_selection_mov)
    amt_tree.bind("<<TreeviewSelect>>", sync_selection_amt)
    note_tree.bind("<<TreeviewSelect>>", sync_selection_note)

    def scroll_movements_grid_to_top() -> None:
        """Dopo filtro/ordinamento o ricarica dati, la prima riga deve restare in cima (scroll sincronizzato)."""
        root.update_idletasks()
        mov_tree.yview_moveto(0)

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

    # Colonne griglia: mov | sep | amt | sep | note | scrollbar
    records_frame.grid_columnconfigure(0, weight=1, minsize=120)
    records_frame.grid_columnconfigure(1, weight=0, minsize=_SEP_CH_W)
    records_frame.grid_columnconfigure(2, weight=0, minsize=104)
    records_frame.grid_columnconfigure(3, weight=0, minsize=_SEP_CH_W)
    records_frame.grid_columnconfigure(4, weight=1, minsize=100)
    records_frame.grid_columnconfigure(5, weight=0, minsize=20)
    records_frame.grid_rowconfigure(0, weight=0)
    records_frame.grid_rowconfigure(1, weight=0)
    records_frame.grid_rowconfigure(2, weight=1)
    search_title_row.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 6))
    header_row.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(0, 2))
    mov_hdr.grid(row=0, column=0, sticky="ew")
    hdr_sep_1.grid(row=0, column=1, sticky="nsw")
    amt_hdr.grid(row=0, column=2, sticky="ew")
    hdr_sep_2.grid(row=0, column=3, sticky="nsw")
    note_hdr.grid(row=0, column=4, sticky="ew")

    # Linee nei canali separatori: ancorate a sinistra (spostate "un po'" a sinistra).
    # In intestazione manteniamo la linea visibile: ancorata al bordo sinistro del canale.
    hdr_sep_1_line.place(x=0, y=0, relheight=1.0)
    hdr_sep_2_line.place(x=0, y=0, relheight=1.0)

    # Separator verticali: su macOS `ttk.Separator` può risultare poco visibile.
    # Usiamo Frame 1px con colore fisso, allineati anche con l'intestazione.
    sep_1 = tk.Frame(records_frame, bg=header_bg, width=_SEP_CH_W)
    sep_2 = tk.Frame(records_frame, bg=header_bg, width=_SEP_CH_W)
    sep_1_line = tk.Frame(sep_1, bg="#c0c0c0", width=1)
    sep_2_line = tk.Frame(sep_2, bg="#c0c0c0", width=1)
    mov_tree.grid(row=2, column=0, sticky="nsew")
    sep_1.grid(row=2, column=1, sticky="nsw")
    amt_tree.grid(row=2, column=2, sticky="nsew")
    sep_2.grid(row=2, column=3, sticky="nsw")
    note_tree.grid(row=2, column=4, sticky="nsew")
    yscroll.grid(row=2, column=5, sticky="ns", padx=(2, 0))

    sep_1_line.place(x=-3, y=0, relheight=1.0)
    sep_2_line.place(x=-3, y=0, relheight=1.0)

    pending_movement_rows: list[
        tuple[str, str, tuple[object, ...], str, str, str, str]
    ] = []
    movements_population_seq = 0

    def _movement_rows_from_pool(
        pool: list[dict],
        reg_seq_map: dict,
        accounts_by_year: dict,
        categories_by_year: dict,
    ) -> list[tuple[str, str, tuple[object, ...], str, str, str, str]]:
        """Stessa logica della griglia: (iid, reg#, mov_vals×7, importo, tag colore, nota, stripe)."""
        q_cat_raw = text_category_applied_var.get().strip()
        q_acc_raw = text_account_applied_var.get().strip()
        q_cat = "" if q_cat_raw in ("", _ALL_CATEGORIES_LABEL) else q_cat_raw.lower()
        q_acc = "" if q_acc_raw in ("", _ALL_ACCOUNTS_LABEL) else q_acc_raw.lower()
        q_chq = text_cheque_applied_var.get().strip().lower()
        q_note = text_note_applied_var.get().strip().lower()
        row_i = 0
        reg_from_n = None
        reg_to_n = None
        if filter_order_applied_var.get() == "registration":
            try:
                reg_from_n = int(str(reg_from_applied_var.get()).strip())
                reg_to_n = int(str(reg_to_applied_var.get()).strip())
            except Exception:
                reg_from_n = None
                reg_to_n = None
        out: list[tuple[str, str, tuple[object, ...], str, str, str, str]] = []
        for r in pool:
            year = r.get("year")
            year_accounts = accounts_by_year.get(year, [])
            year_categories = categories_by_year.get(year, [])
            account_1_name = account_name_for_record(r, year_accounts, "primary")
            account_2_name = account_name_for_record(r, year_accounts, "secondary")
            category_name = category_name_for_record(r, year_categories)
            stars_1 = r.get("account_primary_flags", "")
            stars_2 = r.get("account_secondary_flags", "")
            if filter_order_applied_var.get() == "date":
                if q_cat and q_cat != (category_name or "").lower():
                    continue
                if q_acc and q_acc not in (account_1_name or "").lower() and q_acc not in (account_2_name or "").lower():
                    continue
                if q_chq and q_chq not in str(r.get("cheque") or "").lower():
                    continue
                if q_note and q_note not in str(r.get("note") or "").lower():
                    continue
            elif filter_order_applied_var.get() == "registration":
                nreg = reg_seq_map[record_legacy_stable_key(r)]
                if reg_from_n is not None and reg_to_n is not None:
                    if filter_direction_applied_var.get() == "backward":
                        if nreg > reg_from_n or nreg < reg_to_n:
                            continue
                    else:
                        if nreg < reg_from_n or nreg > reg_to_n:
                            continue
                if q_acc and q_acc not in (account_1_name or "").lower() and q_acc not in (account_2_name or "").lower():
                    continue

            amount_text, amount_tag = format_amount_for_output(r)
            stripe = f"stripe{row_i % 2}"
            rid = str(row_i)
            reg_text = str(reg_seq_map[record_legacy_stable_key(r)])
            mov_vals = (
                to_italian_date(r["date_iso"]),
                category_name,
                account_1_name,
                stars_1,
                account_2_name,
                stars_2,
                r.get("cheque") or "",
            )
            out.append((rid, reg_text, mov_vals, amount_text, amount_tag, r.get("note") or "", stripe))
            row_i += 1
        return out

    def populate_movements_trees() -> None:
        nonlocal movements_population_seq
        movements_population_seq += 1
        token_local = movements_population_seq
        try:
            refresh_search_title()
        except Exception:
            pass
        # Nascondi eventuale messaggio "no risultati"
        try:
            no_results_label.place_forget()
        except Exception:
            pass
        _clear_selection(mov_tree)
        _clear_selection(amt_tree)
        _clear_selection(note_tree)
        for iid in mov_tree.get_children():
            mov_tree.delete(iid)
        for iid in amt_tree.get_children():
            amt_tree.delete(iid)
        for iid in note_tree.get_children():
            note_tree.delete(iid)
        scroll_movements_grid_to_top()
        d = cur_db()
        accounts_by_year = year_accounts_map(d)
        categories_by_year = year_categories_map(d)
        records = [r for y in d["years"] for r in y["records"]]
        records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        reg_seq_map = unified_registration_sequence_map(records)

        # Bounds date del dataset (servono per preset e per calendario).
        nonlocal _dataset_min_date, _dataset_max_date
        parsed_dates: list[date] = []
        for rr in records:
            iso = str(rr.get("date_iso", "")).strip()
            if not iso:
                continue
            try:
                parsed_dates.append(date.fromisoformat(iso))
            except Exception:
                continue
        if parsed_dates:
            _dataset_min_date = min(parsed_dates)
            _dataset_max_date = max(parsed_dates)
            _dataset_years_with_records = sorted({d.year for d in parsed_dates})
        else:
            _dataset_min_date = date.today()
            _dataset_max_date = date.today()
            _dataset_years_with_records = [date.today().year]

        # Se la UI date è già stata creata, riallinea i campi preset su nuovi bounds (es. dopo import legacy).
        try:
            refresh_date_preview_from_modes()
        except NameError:
            pass

        pool = filter_and_sort_movements_for_grid(
            records,
            reg_seq_map,
            order_by_date=filter_order_applied_var.get() == "date",
            exclude_future_dates=filter_future_applied_var.get() == "exclude",
            backward=filter_direction_applied_var.get() == "backward",
            date_from_iso=(
                date_from_applied_var.get()
                if filter_order_applied_var.get() == "date"
                else (_scope_dates_for_registration(reg_preset_applied_var.get())[0] if filter_order_applied_var.get() == "registration" else None)
            ),
            date_to_iso=(
                date_to_applied_var.get()
                if filter_order_applied_var.get() == "date"
                else (_scope_dates_for_registration(reg_preset_applied_var.get())[1] if filter_order_applied_var.get() == "registration" else None)
            ),
        )
        pending_movement_rows.clear()
        pending_movement_rows.extend(
            _movement_rows_from_pool(pool, reg_seq_map, accounts_by_year, categories_by_year)
        )

        def flush_movement_batch(start: int) -> None:
            # Evita race condition: se nel frattempo viene lanciato un nuovo populate,
            # i batch vecchi non devono inserire nel Treeview corrente.
            if token_local != movements_population_seq:
                return
            end = min(start + MOVEMENTS_INSERT_BATCH, len(pending_movement_rows))
            for i in range(start, end):
                rid, reg_text, mov_vals, amount_text, amount_tag, note_text, stripe = pending_movement_rows[i]
                mov_tree.insert(
                    "",
                    tk.END,
                    iid=rid,
                    values=("", reg_text) + mov_vals,
                    tags=(stripe,),
                )
                amt_tree.insert("", tk.END, iid=rid, values=(amount_text,), tags=(amount_tag, stripe))
                note_tree.insert("", tk.END, iid=rid, values=(note_text,), tags=(stripe,))
            if end < len(pending_movement_rows):
                root.after(1, lambda s=end: flush_movement_batch(s))
            else:
                # Risultati presenti: assicurati che intestazione e griglia siano visibili.
                try:
                    header_row.grid()
                    mov_tree.grid()
                    sep_1.grid()
                    amt_tree.grid()
                    sep_2.grid()
                    note_tree.grid()
                    yscroll.grid()
                except Exception:
                    pass
                root.after_idle(scroll_movements_grid_to_top)

        if pending_movement_rows:
            # Mostra griglia/intestazione (se erano state nascoste per "nessun risultato").
            try:
                header_row.grid()
                mov_tree.grid()
                sep_1.grid()
                amt_tree.grid()
                sep_2.grid()
                note_tree.grid()
                yscroll.grid()
            except Exception:
                pass
            root.after(0, lambda: flush_movement_batch(0))
        else:
            # Nessun risultato: mostra testo centrato.
            try:
                header_row.grid_remove()
                mov_tree.grid_remove()
                sep_1.grid_remove()
                amt_tree.grid_remove()
                sep_2.grid_remove()
                note_tree.grid_remove()
                yscroll.grid_remove()
            except Exception:
                pass
            no_results_label.place(relx=0.5, rely=0.5, anchor="center")

    # Coppie tipo pulsante: su macOS tk.Button ignora spesso bg; usiamo Label cliccabili (bg rispettato).
    _FILTER_BG_OFF = "#ffffff"
    _FILTER_BG_ON = "#fff176"

    def _set_filter_toggle_style(w: tk.Label, selected: bool) -> None:
        if selected:
            w.configure(
                bg=_FILTER_BG_ON,
                fg="#1a1a1a",
                relief=tk.SUNKEN,
                bd=2,
                highlightthickness=0,
            )
        else:
            w.configure(
                bg=_FILTER_BG_OFF,
                fg="#1a1a1a",
                relief=tk.RAISED,
                bd=1,
                highlightthickness=0,
            )

    g1 = ttk.Frame(filters_row)
    g1.pack(side=tk.LEFT, anchor=tk.W)
    btn_order_date = tk.Label(
        g1,
        text="Ricerca per data",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_order_reg = tk.Label(
        g1,
        text="Ricerca per registrazione",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_order_date.bind("<Button-1>", lambda _e: pick_order("date"))
    btn_order_reg.bind("<Button-1>", lambda _e: pick_order("registration"))
    btn_order_date.pack(side=tk.LEFT, padx=(0, 8))
    btn_order_reg.pack(side=tk.LEFT)

    g2 = ttk.Frame(filters_row)
    g2.pack(side=tk.LEFT, padx=(28, 0), anchor=tk.W)
    btn_future_include = tk.Label(
        g2,
        text="Comprese date future",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_future_exclude = tk.Label(
        g2,
        text="Escluse date future",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_future_include.bind("<Button-1>", lambda _e: pick_future("include"))
    btn_future_exclude.bind("<Button-1>", lambda _e: pick_future("exclude"))
    btn_future_include.pack(side=tk.LEFT, padx=(0, 8))
    btn_future_exclude.pack(side=tk.LEFT)

    g3 = ttk.Frame(filters_row)
    g3.pack(side=tk.LEFT, padx=(28, 0), anchor=tk.W)
    btn_dir_backward = tk.Label(
        g3,
        text="All'indietro, dalla più recente",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_dir_forward = tk.Label(
        g3,
        text="In avanti, dalla più lontana",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=5,
    )
    btn_dir_backward.bind("<Button-1>", lambda _e: pick_direction("backward"))
    btn_dir_forward.bind("<Button-1>", lambda _e: pick_direction("forward"))
    btn_dir_backward.pack(side=tk.LEFT, padx=(0, 8))
    btn_dir_forward.pack(side=tk.LEFT)

    def refresh_movement_filter_button_styles() -> None:
        _set_filter_toggle_style(btn_order_date, filter_order_preview_var.get() == "date")
        _set_filter_toggle_style(btn_order_reg, filter_order_preview_var.get() == "registration")
        _set_filter_toggle_style(btn_future_include, filter_future_preview_var.get() == "include")
        _set_filter_toggle_style(btn_future_exclude, filter_future_preview_var.get() == "exclude")
        _set_filter_toggle_style(btn_dir_backward, filter_direction_preview_var.get() == "backward")
        _set_filter_toggle_style(btn_dir_forward, filter_direction_preview_var.get() == "forward")

    def pick_order(which: str) -> None:
        if filter_order_preview_var.get() == which:
            return
        filter_order_preview_var.set(which)
        refresh_movement_filter_button_styles()
        refresh_date_controls_visibility()
        if which == "registration":
            # Default preset per registrazione: ultimi 12 mesi
            if reg_preset_preview_var.get() not in ("last_12", "all_time"):
                reg_preset_preview_var.set("last_12")
            refresh_reg_preset_button_styles()
            try:
                refresh_registration_scope_and_controls()
            except Exception:
                pass

    def pick_future(which: str) -> None:
        if filter_future_preview_var.get() == which:
            return
        filter_future_preview_var.set(which)
        refresh_movement_filter_button_styles()
        refresh_date_preview_from_modes()
        try:
            refresh_registration_scope_and_controls()
        except Exception:
            pass

    def pick_direction(which: str) -> None:
        if filter_direction_preview_var.get() == which:
            return
        filter_direction_preview_var.set(which)
        refresh_movement_filter_button_styles()
        refresh_date_preview_from_modes()
        try:
            refresh_registration_scope_and_controls()
        except Exception:
            pass

    def apply_movement_search(_event: tk.Event | None = None) -> None:
        o = filter_order_preview_var.get()
        f = filter_future_preview_var.get()
        d = filter_direction_preview_var.get()
        df_preview = date_from_preview_var.get()
        dt_preview = date_to_preview_var.get()
        dp_preview = date_preset_preview_var.get()
        cat_preview = text_category_preview_var.get()
        acc_preview = text_account_preview_var.get()
        chq_preview = text_cheque_preview_var.get()
        note_preview = text_note_preview_var.get()
        rp_preview = reg_preset_preview_var.get()
        rf_preview = reg_from_preview_var.get()
        rt_preview = reg_to_preview_var.get()

        if o == "registration":
            # Validazione limiti registrazione coerenti con scope (preset + include/exclude).
            scope_from, scope_to = _scope_dates_for_registration(rp_preview)
            ddb = cur_db()
            recs = [r for y in ddb["years"] for r in y["records"]]
            recs.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
            rmap = unified_registration_sequence_map(recs)
            scoped_nums: list[int] = []
            for rr in recs:
                if not show_record_in_movements_grid(rr):
                    continue
                iso = str(rr.get("date_iso", ""))
                if iso < scope_from or iso > scope_to:
                    continue
                scoped_nums.append(rmap[record_legacy_stable_key(rr)])
            mn_allowed = min(scoped_nums) if scoped_nums else 1
            mx_allowed = max(scoped_nums) if scoped_nums else 1

            def _parse_int(s: str) -> int | None:
                s = (s or "").strip()
                if not s:
                    return None
                if not s.isdigit():
                    return None
                try:
                    return int(s)
                except Exception:
                    return None

            rf = _parse_int(rf_preview)
            rt = _parse_int(rt_preview)
            if rf is None or rt is None:
                messagebox.showerror("Valore non valido", "Inserisci numeri di registrazione validi.")
                return
            if rf < mn_allowed or rf > mx_allowed or rt < mn_allowed or rt > mx_allowed:
                messagebox.showerror(
                    "Fuori intervallo",
                    f"I numeri di registrazione devono essere tra {mn_allowed} e {mx_allowed} per il periodo scelto.",
                )
                # Dopo l'avviso, ripristina subito i valori coerenti nelle caselle.
                try:
                    refresh_registration_scope_and_controls()
                except Exception:
                    pass
                return

            # Coerenza con direzione: backward -> dalla >= alla ; forward -> dalla <= alla
            if d == "backward" and rf < rt:
                messagebox.showerror("Ordine non coerente", "Con All'indietro, Dalla reg. # deve essere >= Alla reg. #.")
                try:
                    refresh_registration_scope_and_controls()
                except Exception:
                    pass
                return
            if d == "forward" and rf > rt:
                messagebox.showerror("Ordine non coerente", "Con In avanti, Dalla reg. # deve essere <= Alla reg. #.")
                try:
                    refresh_registration_scope_and_controls()
                except Exception:
                    pass
                return

        if (
            o == filter_order_applied_var.get()
            and f == filter_future_applied_var.get()
            and d == filter_direction_applied_var.get()
            and dp_preview == date_preset_applied_var.get()
            and df_preview == date_from_applied_var.get()
            and dt_preview == date_to_applied_var.get()
            and rp_preview == reg_preset_applied_var.get()
            and rf_preview == reg_from_applied_var.get()
            and rt_preview == reg_to_applied_var.get()
            and cat_preview == text_category_applied_var.get()
            and acc_preview == text_account_applied_var.get()
            and chq_preview == text_cheque_applied_var.get()
            and note_preview == text_note_applied_var.get()
        ):
            return
        filter_order_applied_var.set(o)
        filter_future_applied_var.set(f)
        filter_direction_applied_var.set(d)
        date_preset_applied_var.set(dp_preview)
        date_from_applied_var.set(df_preview)
        date_to_applied_var.set(dt_preview)
        reg_preset_applied_var.set(rp_preview)
        reg_from_applied_var.set(rf_preview)
        reg_to_applied_var.set(rt_preview)
        text_category_applied_var.set(cat_preview)
        text_account_applied_var.set(acc_preview)
        text_cheque_applied_var.set(chq_preview)
        text_note_applied_var.set(note_preview)
        populate_movements_trees()

    # Enter nei filtri testuali = esegui Cerca
    for _w in (category_entry, account_entry, cheque_entry, note_entry):
        _w.bind("<Return>", apply_movement_search)

    def clear_movement_text_filters() -> None:
        text_category_preview_var.set(_ALL_CATEGORIES_LABEL)
        text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)
        text_cheque_preview_var.set("")
        text_note_preview_var.set("")
        apply_movement_search()

    clear_filters_btn.configure(command=clear_movement_text_filters)

    # ------------------------------
    # Ricerca per data: preset + intervallo (dalla/alla) + calendario
    # ------------------------------
    def _parse_iso_to_date(s: str) -> date | None:
        s = (s or "").strip()
        if not s:
            return None
        try:
            return date.fromisoformat(s)
        except Exception:
            return None

    def _add_months(d: date, months: int) -> date:
        """Aggiunge/sottrae mesi, clampando sul fine mese."""
        y = d.year + (d.month - 1 + months) // 12
        m = (d.month - 1 + months) % 12 + 1
        day = min(d.day, calendar.monthrange(y, m)[1])
        return date(y, m, day)

    def _normalize_range_preview() -> None:
        d1 = _parse_iso_to_date(date_from_preview_var.get())
        d2 = _parse_iso_to_date(date_to_preview_var.get())
        if not d1 or not d2:
            return
        direction = filter_direction_preview_var.get()
        # In avanti => "dalla data" dovrebbe essere la più bassa (d1 <= d2).
        # All'indietro => "dalla data" dovrebbe essere la più alta (d1 >= d2).
        if direction == "backward":
            if d1 < d2:
                date_from_preview_var.set(d2.isoformat())
                date_to_preview_var.set(d1.isoformat())
        else:
            if d1 > d2:
                date_from_preview_var.set(d2.isoformat())
                date_to_preview_var.set(d1.isoformat())

    def _dataset_minmax_safe() -> tuple[date, date]:
        mn = _dataset_min_date or date.today()
        mx = _dataset_max_date or date.today()
        return mn, mx

    def _compute_preset_range(preset_id: str) -> tuple[date, date]:
        mn, mx = _dataset_minmax_safe()
        allowed_min = mn
        allowed_max = date.today() if filter_future_preview_var.get() == "exclude" else mx

        if preset_id == "all_time":
            return allowed_min, allowed_max

        # I preset "Ultimi X mesi" sono sempre agganciati alla data massima consentita,
        # così "In avanti, dalla più lontana" non sposta la finestra (solo l'ordine grid).
        months = 12
        if preset_id == "last_6":
            months = 6
        elif preset_id == "last_4":
            months = 4
        elif preset_id == "last_3":
            months = 3
        elif preset_id == "last_2":
            months = 2
        elif preset_id == "last_1":
            months = 1
        elif preset_id == "last_12":
            months = 12

        ref_end = allowed_max
        start = _add_months(ref_end, -months)
        # clamp start
        start = max(allowed_min, min(start, allowed_max))
        return start, ref_end

    def refresh_date_fields_from_current_preset() -> None:
        preset_id = date_preset_preview_var.get()
        if preset_id == "custom":
            _normalize_range_preview()
            return
        d_from, d_to = _compute_preset_range(preset_id)
        direction = filter_direction_preview_var.get()
        if direction == "backward":
            # Mostriamo "dalla data" come la più alta.
            date_from_preview_var.set(d_to.isoformat())
            date_to_preview_var.set(d_from.isoformat())
        else:
            date_from_preview_var.set(d_from.isoformat())
            date_to_preview_var.set(d_to.isoformat())
        _normalize_range_preview()

    def refresh_date_entry_states() -> None:
        custom = date_preset_preview_var.get() == "custom"
        # Non disabilitiamo l'Entry: su macOS il testo disabilitato può risultare poco leggibile.
        # L'apertura calendario resta comunque subordinata a "Date a scelta".
        date_from_entry.configure(state="normal")
        date_to_entry.configure(state="normal")

    def refresh_date_preview_from_modes() -> None:
        preset_id = date_preset_preview_var.get()
        mn, mx = _dataset_minmax_safe()
        max_allowed = date.today() if filter_future_preview_var.get() == "exclude" else mx
        min_allowed = mn

        if preset_id != "custom":
            refresh_date_fields_from_current_preset()
        else:
            if not date_custom_manual_override:
                # Preimpostazione comodità: ultimi 12 mesi, ma i vincoli di scelta restano globali.
                start_12 = _add_months(max_allowed, -12)
                start_12 = max(min_allowed, min(start_12, max_allowed))
                if filter_direction_preview_var.get() == "backward":
                    date_from_preview_var.set(max_allowed.isoformat())
                    date_to_preview_var.set(start_12.isoformat())
                else:
                    date_from_preview_var.set(start_12.isoformat())
                    date_to_preview_var.set(max_allowed.isoformat())
                _normalize_range_preview()
            else:
                # Clamp dei valori custom entro i limiti attuali.
                d_from = _parse_iso_to_date(date_from_preview_var.get()) or min_allowed
                d_to = _parse_iso_to_date(date_to_preview_var.get()) or max_allowed
                d_from = max(min_allowed, min(d_from, max_allowed))
                d_to = max(min_allowed, min(d_to, max_allowed))
                date_from_preview_var.set(d_from.isoformat())
                date_to_preview_var.set(d_to.isoformat())
                _normalize_range_preview()

        refresh_date_entry_states()
        try:
            refresh_category_account_dropdowns()
        except Exception:
            pass

    def _scope_dates_for_registration(preset_id: str) -> tuple[str, str]:
        """Restituisce (from_iso, to_iso) per lo scope '12 mesi' o 'intero periodo'."""
        mn, mx = _dataset_minmax_safe()
        max_allowed = date.today() if filter_future_preview_var.get() == "exclude" else mx
        min_allowed = mn
        if preset_id == "all_time":
            return min_allowed.isoformat(), max_allowed.isoformat()
        # last_12
        start_12 = _add_months(max_allowed, -12)
        start_12 = max(min_allowed, min(start_12, max_allowed))
        return start_12.isoformat(), max_allowed.isoformat()

    def refresh_registration_scope_and_controls() -> None:
        """Preimposta reg_from/reg_to e aggiorna dropdown conto in base a preset + include/exclude + direzione."""
        if filter_order_preview_var.get() != "registration":
            return
        scope_from, scope_to = _scope_dates_for_registration(reg_preset_preview_var.get())
        d = cur_db()
        records = [r for y in d["years"] for r in y["records"]]
        records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        reg_seq_map = unified_registration_sequence_map(records)

        # scegli solo records nello scope date (e visibili) e (se exclude future) già incorporato in scope_to
        def in_scope(r: dict) -> bool:
            if not show_record_in_movements_grid(r):
                return False
            iso = str(r.get("date_iso", ""))
            if iso < scope_from or iso > scope_to:
                return False
            return True

        scoped = [r for r in records if in_scope(r)]
        if scoped:
            nums = [reg_seq_map[record_legacy_stable_key(r)] for r in scoped]
            mn_reg = min(nums)
            mx_reg = max(nums)
        else:
            mn_reg = 1
            mx_reg = 1

        # preimposta in base a direzione: backward -> from=max, to=min; forward -> from=min, to=max
        if filter_direction_preview_var.get() == "backward":
            reg_from_preview_var.set(str(mx_reg))
            reg_to_preview_var.set(str(mn_reg))
        else:
            reg_from_preview_var.set(str(mn_reg))
            reg_to_preview_var.set(str(mx_reg))

        # aggiorna valori conto disponibili nello scope
        accounts_by_year = year_accounts_map(d)
        accs: set[str] = set()
        for r in scoped:
            year = r.get("year")
            year_accounts = accounts_by_year.get(year, [])
            a1 = account_name_for_record(r, year_accounts, "primary")
            a2 = account_name_for_record(r, year_accounts, "secondary")
            if a1:
                accs.add(str(a1).strip())
            if a2:
                accs.add(str(a2).strip())
        acc_vals = (_ALL_ACCOUNTS_LABEL,) + _sorted_with_preferred(accs, "Cassa")
        reg_account_entry.configure(values=acc_vals)
        if not text_account_preview_var.get():
            text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)
        if text_account_preview_var.get() != _ALL_ACCOUNTS_LABEL and text_account_preview_var.get() not in accs:
            text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)

    def open_calendar_for(which: str) -> tk.Toplevel | None:
        if date_preset_preview_var.get() != "custom":
            return None

        mn, mx = _dataset_minmax_safe()
        global_min = mn
        global_max = date.today() if filter_future_preview_var.get() == "exclude" else mx

        d_from = _parse_iso_to_date(date_from_preview_var.get())
        d_to = _parse_iso_to_date(date_to_preview_var.get())

        # Nei limiti globali il calendario consente l'intero periodo consentito
        # (Include/Esclude date future). L'ordine "dalla/alla" viene poi sistemato
        # da _normalize_range_preview() dopo la scelta.
        field_min = global_min
        field_max = global_max
        if which == "from":
            current = d_from or field_min
        else:
            current = d_to or field_min

        if field_min > field_max:
            field_min, field_max = field_max, field_min

        # clamp current
        if current < field_min:
            current = field_min
        if current > field_max:
            current = field_max

        top = tk.Toplevel(root)
        top.title(
            "Seleziona data di inizio ricerca"
            if which == "from"
            else "Seleziona data di fine ricerca"
        )
        top.transient(root)
        # Non rendiamo modale (grab): serve poter cliccare di nuovo sulla casella data
        # per chiudere il popup e passare alla digitazione manuale.
        try:
            top.grab_release()
        except Exception:
            pass
        top.protocol("WM_DELETE_WINDOW", lambda: top.destroy())
        try:
            top.focus_force()
        except Exception:
            pass

        selected_date = current
        cur_year = current.year
        cur_month = current.month

        # Anni presenti nel DB (per evitare di scegliere anni vuoti).
        years_available = [
            y for y in _dataset_years_with_records if field_min.year <= y <= field_max.year
        ]
        if not years_available:
            years_available = [cur_year]
        if cur_year not in years_available:
            # scegli l'anno più vicino in lista (preferendo quello superiore)
            higher = [y for y in years_available if y >= cur_year]
            cur_year = min(higher) if higher else max(years_available)

        header = ttk.Frame(top, padding=6)
        header.pack(fill=tk.X)
        title_lbl = ttk.Label(header, font=("TkDefaultFont", 10, "bold"))
        title_lbl.pack(side=tk.LEFT)

        btns = ttk.Frame(header)
        btns.pack(side=tk.RIGHT)

        def _prev_month(y: int, m: int) -> tuple[int, int]:
            return (y - 1, 12) if m == 1 else (y, m - 1)

        def _next_month(y: int, m: int) -> tuple[int, int]:
            return (y + 1, 1) if m == 12 else (y, m + 1)

        def render() -> None:
            nonlocal cur_year, cur_month
            for child in list(days_frame.winfo_children()):
                child.destroy()
            title_lbl.configure(text=f"{calendar.month_name[cur_month]} {cur_year}")
            _update_month_nav_state()
            # Mantieni allineata la tendina anno anche se render è chiamato da altri percorsi.
            nonlocal suppress_year_trace
            if year_var.get() != str(cur_year):
                suppress_year_trace = True
                year_var.set(str(cur_year))
                suppress_year_trace = False

            first_wd = date(cur_year, cur_month, 1).weekday()  # Lun=0
            days_in_month = calendar.monthrange(cur_year, cur_month)[1]

            # intestazioni vuote
            for i in range(first_wd):
                ttk.Label(days_frame, text="").grid(row=0, column=i, padx=1, pady=1, sticky="nsew")

            for day_num in range(1, days_in_month + 1):
                idx = first_wd + day_num - 1
                row = idx // 7
                col = idx % 7
                dsel = date(cur_year, cur_month, day_num)
                in_bounds = field_min <= dsel <= field_max
                # Su macOS i tk.Button possono ignorare bg/relief (si vede solo la cornice).
                # Usiamo Label cliccabili per un look consistente.
                cell = tk.Label(
                    days_frame,
                    text=str(day_num),
                    width=3,
                    padx=2,
                    pady=2,
                    fg="#111111",
                    bg="#ffffff",
                    relief=tk.RAISED,
                    bd=1,
                    highlightthickness=0,
                )
                if in_bounds:
                    cell.configure(cursor="hand2")
                    cell.bind("<Button-1>", lambda _e, dd=dsel: on_pick(dd))
                else:
                    cell.configure(fg="#999999", bg="#f5f5f5")

                if dsel == selected_date:
                    cell.configure(
                        bg="#fff176",
                        relief=tk.SUNKEN,
                        bd=2,
                        highlightthickness=1,
                        highlightbackground="#9e9e9e",
                        highlightcolor="#9e9e9e",
                    )

                cell.grid(row=row + 1, column=col, padx=1, pady=1, sticky="nsew")

            for c in range(7):
                days_frame.grid_columnconfigure(c, weight=1)

        def on_pick(dsel: date) -> None:
            if which == "from":
                date_from_preview_var.set(dsel.isoformat())
            else:
                date_to_preview_var.set(dsel.isoformat())
            nonlocal date_custom_manual_override
            date_custom_manual_override = True
            _normalize_range_preview()
            refresh_date_entry_states()
            top.destroy()

        # Anni: menu a tendina (evita anni senza registrazioni).
        year_var = tk.StringVar(value=str(cur_year))
        year_menu = tk.OptionMenu(btns, year_var, *[str(y) for y in years_available])
        year_menu.pack(side=tk.LEFT, padx=(0, 6))

        suppress_year_trace = False

        def _on_year_changed(*_args: object) -> None:
            nonlocal cur_year
            if suppress_year_trace:
                return
            y = int(year_var.get())
            if y == cur_year:
                return
            cur_year = y
            render()

        year_var.trace_add("write", _on_year_changed)

        btn_month_minus = ttk.Button(btns, text="<<", command=lambda: _jump_month(-1))
        btn_month_plus = ttk.Button(btns, text=">>", command=lambda: _jump_month(1))
        btn_month_minus.pack(side=tk.LEFT, padx=(0, 4))
        btn_month_plus.pack(side=tk.LEFT, padx=(0, 0))

        min_month_key = (field_min.year, field_min.month)
        max_month_key = (field_max.year, field_max.month)

        def _month_key(y: int, m: int) -> tuple[int, int]:
            return (y, m)

        def _update_month_nav_state() -> None:
            prev_y, prev_m = _prev_month(cur_year, cur_month)
            next_y, next_m = _next_month(cur_year, cur_month)
            btn_month_minus.configure(
                state=("normal" if _month_key(prev_y, prev_m) >= min_month_key else "disabled")
            )
            btn_month_plus.configure(
                state=("normal" if _month_key(next_y, next_m) <= max_month_key else "disabled")
            )

        def _jump_month(delta: int) -> None:
            nonlocal cur_year, cur_month
            if delta < 0:
                cur_year, cur_month = _prev_month(cur_year, cur_month)
            else:
                cur_year, cur_month = _next_month(cur_year, cur_month)
            if cur_year not in years_available:
                higher = [y for y in years_available if y >= cur_year]
                cur_year = min(higher) if higher else max(years_available)
            # sincronizza la tendina quando cambia anno (anche se l'anno è valido)
            nonlocal suppress_year_trace
            if year_var.get() != str(cur_year):
                suppress_year_trace = True
                year_var.set(str(cur_year))
                suppress_year_trace = False
            render()

        # giorni settimana
        labels = ttk.Frame(top, padding=(6, 0, 6, 0))
        labels.pack(fill=tk.X)
        for i, name in enumerate(["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]):
            ttk.Label(labels, text=name).grid(row=0, column=i, padx=1, pady=2, sticky="nsew")

        days_frame = tk.Frame(top, padx=6, pady=6)
        days_frame.pack(fill=tk.BOTH, expand=True)
        for c in range(7):
            days_frame.grid_columnconfigure(c, weight=1)

        footer = ttk.Frame(top, padding=6)
        footer.pack(fill=tk.X)
        ttk.Button(
            footer,
            text="Oggi",
            command=lambda: _on_pick_today(),
        ).pack(side=tk.LEFT)

        def _on_pick_today() -> None:
            today = date.today()
            # rispetta solo i vincoli globali (include/exclude), poi normalizza l'ordine
            # in base a "All'indietro/In avanti".
            today_clamped = max(global_min, min(today, global_max))
            if which == "from":
                date_from_preview_var.set(today_clamped.isoformat())
            else:
                date_to_preview_var.set(today_clamped.isoformat())
            _normalize_range_preview()
            refresh_date_entry_states()
            top.destroy()

        render()
        return top
        _update_month_nav_state()

    def refresh_date_controls_visibility() -> None:
        mode = filter_order_preview_var.get()
        if mode == "date":
            date_controls_left.pack(side=tk.LEFT, anchor=tk.W)
            # Re-pack before grid area so it doesn't end up after it.
            filters_text_row.pack(fill=tk.X, pady=(0, 10), before=records_frame)
            reg_controls_row.pack_forget()
            refresh_category_account_dropdowns()
        elif mode == "registration":
            date_controls_left.pack_forget()
            filters_text_row.pack_forget()
            reg_controls_row.pack(side=tk.LEFT, anchor=tk.W)
            try:
                refresh_registration_scope_and_controls()
            except Exception:
                pass
        else:
            date_controls_left.pack_forget()
            filters_text_row.pack_forget()
            reg_controls_row.pack_forget()

    def refresh_movement_date_controls_visibility() -> None:
        refresh_date_controls_visibility()

    def refresh_reg_preset_button_styles() -> None:
        _set_filter_toggle_style(reg_btn_last12, reg_preset_preview_var.get() == "last_12")
        _set_filter_toggle_style(reg_btn_all, reg_preset_preview_var.get() == "all_time")

    def pick_reg_preset(preset_id: str) -> None:
        if reg_preset_preview_var.get() == preset_id:
            return
        reg_preset_preview_var.set(preset_id)
        refresh_reg_preset_button_styles()
        try:
            refresh_registration_scope_and_controls()
        except Exception:
            pass

    reg_btn_last12.bind("<Button-1>", lambda _e: pick_reg_preset("last_12"))
    reg_btn_all.bind("<Button-1>", lambda _e: pick_reg_preset("all_time"))

    # Enter nei campi reg = esegui Cerca (con validazione in apply_movement_search)
    reg_from_entry.bind("<Return>", apply_movement_search)
    reg_to_entry.bind("<Return>", apply_movement_search)

    # Controlli date in basso a destra della prima riga di filtri.
    date_controls_left = ttk.Frame(filters_search_row)
    date_controls_left.pack(side=tk.LEFT, anchor=tk.W)

    _PRESETS: list[tuple[str, str]] = [
        ("last_12", "Ultimi 12 mesi"),
        ("all_time", "Intero periodo"),
        ("last_6", "6 mesi"),
        ("last_4", "4 mesi"),
        ("last_3", "3 mesi"),
        ("last_2", "2 mesi"),
        ("last_1", "1 mese"),
        ("custom", "Date a scelta"),
    ]

    date_preset_buttons: dict[str, tk.Label] = {}
    presets_row = ttk.Frame(date_controls_left)
    presets_row.pack(side=tk.LEFT)

    def refresh_date_preset_button_styles() -> None:
        for pid, btn in date_preset_buttons.items():
            _set_filter_toggle_style(btn, date_preset_preview_var.get() == pid)

    def pick_date_preset(preset_id: str) -> None:
        if date_preset_preview_var.get() == preset_id:
            return
        date_preset_preview_var.set(preset_id)
        nonlocal date_custom_manual_override
        if preset_id == "custom":
            date_custom_manual_override = False
            # Quando si attiva "Date a scelta" i calendari devono permettere la scelta
            # sull'intero periodo: impostiamo quindi dai limiti globali consentiti,
            # tenendo conto di Comprese/Escluse e della direzione (All'indietro/In avanti).
            mn = _dataset_min_date or date.today()
            mx = _dataset_max_date or date.today()
            global_max = date.today() if filter_future_preview_var.get() == "exclude" else mx
            global_min = mn
            # Preimpostazione comodità: ultimi 12 mesi (poi la scelta resta possibile su tutto il periodo).
            start_12 = _add_months(global_max, -12)
            start_12 = max(global_min, min(start_12, global_max))
            if filter_direction_preview_var.get() == "backward":
                date_from_preview_var.set(global_max.isoformat())
                date_to_preview_var.set(start_12.isoformat())
            else:
                date_from_preview_var.set(start_12.isoformat())
                date_to_preview_var.set(global_max.isoformat())
            _normalize_range_preview()
        else:
            refresh_date_fields_from_current_preset()
        refresh_date_preset_button_styles()
        refresh_date_entry_states()
        refresh_category_account_dropdowns()

    for pid, text in _PRESETS:
        b = tk.Label(
            presets_row,
            text=text,
            cursor="hand2",
            highlightthickness=0,
            font=filter_ui_font,
            padx=8,
            pady=6,
        )
        b.bind("<Button-1>", lambda _e, _pid=pid: pick_date_preset(_pid))
        b.pack(side=tk.LEFT, padx=(0, 8))
        date_preset_buttons[pid] = b

    fields_row = ttk.Frame(date_controls_left)
    fields_row.pack(side=tk.LEFT, padx=(16, 0))

    ttk.Label(fields_row, text="dalla data", style="Filters.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
    date_from_disp_var = tk.StringVar()
    date_to_disp_var = tk.StringVar()
    calendar_popup_from: tk.Toplevel | None = None
    calendar_popup_to: tk.Toplevel | None = None
    manual_mode_from = False
    manual_mode_to = False
    manual_restore_iso_from: str | None = None
    manual_restore_iso_to: str | None = None
    _DATE_MASK = "__/__/____"
    _DATE_MASK_POS = (0, 1, 3, 4, 6, 7, 8, 9)

    # Manteniamo testo sempre ben visibile (anche quando non è "Date a scelta").
    ttk.Style(root).configure(
        "DateEntry.TEntry",
        foreground="#111111",
        fieldbackground="#ffffff",
        font=filter_ui_font,
    )
    date_from_entry = ttk.Entry(
        fields_row,
        textvariable=date_from_disp_var,
        width=10,
        style="DateEntry.TEntry",
    )
    date_from_entry.grid(row=0, column=1, sticky="w")
    ttk.Label(fields_row, text="alla data", style="Filters.TLabel").grid(row=0, column=2, sticky="w", padx=(16, 6))
    date_to_entry = ttk.Entry(
        fields_row,
        textvariable=date_to_disp_var,
        width=10,
        style="DateEntry.TEntry",
    )
    date_to_entry.grid(row=0, column=3, sticky="w")

    def _close_calendar(which: str) -> None:
        nonlocal calendar_popup_from, calendar_popup_to
        pop = calendar_popup_from if which == "from" else calendar_popup_to
        if pop is not None:
            try:
                pop.destroy()
            except Exception:
                pass
        if which == "from":
            calendar_popup_from = None
        else:
            calendar_popup_to = None

    def _toggle_calendar_or_edit(which: str) -> None:
        """In Date a scelta: 1° click apre calendario; 2° click chiude e abilita digitazione."""
        if date_preset_preview_var.get() != "custom":
            return
        nonlocal calendar_popup_from, calendar_popup_to
        nonlocal manual_mode_from, manual_mode_to, manual_restore_iso_from, manual_restore_iso_to

        entry = date_from_entry if which == "from" else date_to_entry
        disp_var = date_from_disp_var if which == "from" else date_to_disp_var
        preview_var = date_from_preview_var if which == "from" else date_to_preview_var

        # Se siamo già in modalità manuale, un click ripristina preselezione iniziale e riapre calendario.
        if which == "from" and manual_mode_from:
            manual_mode_from = False
            if manual_restore_iso_from:
                preview_var.set(manual_restore_iso_from)
            _sync_date_displays_from_iso()
            new_pop = open_calendar_for(which)
            calendar_popup_from = new_pop
            if new_pop is not None:
                def _on_destroy(_e: tk.Event, _which: str = which) -> None:
                    nonlocal calendar_popup_from
                    calendar_popup_from = None
                new_pop.bind("<Destroy>", _on_destroy)
            return
        if which == "to" and manual_mode_to:
            manual_mode_to = False
            if manual_restore_iso_to:
                preview_var.set(manual_restore_iso_to)
            _sync_date_displays_from_iso()
            new_pop = open_calendar_for(which)
            calendar_popup_to = new_pop
            if new_pop is not None:
                def _on_destroy(_e: tk.Event, _which: str = which) -> None:
                    nonlocal calendar_popup_to
                    calendar_popup_to = None
                new_pop.bind("<Destroy>", _on_destroy)
            return

        pop = calendar_popup_from if which == "from" else calendar_popup_to
        if pop is not None:
            _close_calendar(which)
            # Passa a modalità manuale: mostra placeholder e seleziona tutto.
            if which == "from":
                manual_mode_from = True
                manual_restore_iso_from = preview_var.get() or manual_restore_iso_from
            else:
                manual_mode_to = True
                manual_restore_iso_to = preview_var.get() or manual_restore_iso_to

            disp_var.set(_DATE_MASK)
            try:
                entry.configure(foreground="#111111")
            except Exception:
                pass
            entry.focus_set()
            try:
                entry.selection_clear()
            except Exception:
                pass
            try:
                entry.xview_moveto(0)
                entry.icursor(0)
            except Exception:
                pass
            return

        new_pop = open_calendar_for(which)
        if which == "from":
            calendar_popup_from = new_pop
        else:
            calendar_popup_to = new_pop

        if new_pop is not None:
            # Se l'utente chiude il popup con la X, azzera lo stato.
            def _on_destroy(_e: tk.Event, _which: str = which) -> None:
                nonlocal calendar_popup_from, calendar_popup_to
                if _which == "from":
                    calendar_popup_from = None
                else:
                    calendar_popup_to = None

            new_pop.bind("<Destroy>", _on_destroy)

    def _on_date_click(which: str, _e: tk.Event) -> str:
        _toggle_calendar_or_edit(which)
        # Evita che l'Entry riposizioni il cursore in base al punto di click.
        return "break"

    date_from_entry.bind("<Button-1>", lambda e: _on_date_click("from", e))
    date_to_entry.bind("<Button-1>", lambda e: _on_date_click("to", e))

    def _sync_date_displays_from_iso() -> None:
        df = date_from_preview_var.get()
        dt = date_to_preview_var.get()
        date_from_disp_var.set(to_italian_date(df) if df else "")
        date_to_disp_var.set(to_italian_date(dt) if dt else "")

    def _parse_italian_ddmmyyyy_to_iso(s: str) -> str | None:
        s = (s or "").strip()
        if not s:
            return None
        # Accetta anche ISO per resilienza.
        if "-" in s:
            parts = s.split("-")
            if len(parts) == 3:
                try:
                    return date.fromisoformat(s).isoformat()
                except Exception:
                    return None
        parts = s.split("/")
        if len(parts) != 3:
            return None
        dd, mm, yyyy = parts
        try:
            return date(int(yyyy), int(mm), int(dd)).isoformat()
        except Exception:
            return None

    def _validate_manual_date_and_apply(which: str) -> None:
        if date_preset_preview_var.get() != "custom":
            _sync_date_displays_from_iso()
            return

        # Valida formato e limiti come il calendario.
        mn, mx = _dataset_minmax_safe()
        global_min = mn
        global_max = date.today() if filter_future_preview_var.get() == "exclude" else mx

        raw = date_from_disp_var.get() if which == "from" else date_to_disp_var.get()
        def _refocus_manual() -> None:
            entry = date_from_entry if which == "from" else date_to_entry
            try:
                entry.focus_set()
            except Exception:
                pass
            # porta il cursore al primo '_' disponibile
            try:
                s = (date_from_disp_var.get() if which == "from" else date_to_disp_var.get()) or _DATE_MASK
                for i in _DATE_MASK_POS:
                    if i < len(s) and s[i] == "_":
                        entry.icursor(i)
                        return
                entry.icursor(0)
            except Exception:
                pass

        if not raw or "_" in raw or raw.strip() == _DATE_MASK:
            messagebox.showerror("Data non valida", "Inserisci una data completa nel formato gg/mm/aaaa.")
            _refocus_manual()
            return
        iso = _parse_italian_ddmmyyyy_to_iso(raw or "")
        if not iso:
            messagebox.showerror("Data non valida", "Formato richiesto: gg/mm/aaaa.")
            _refocus_manual()
            return
        try:
            dsel = date.fromisoformat(iso)
        except Exception:
            messagebox.showerror("Data non valida", "Data non valida (giorno/mese/anno).")
            _refocus_manual()
            return
        if dsel < global_min or dsel > global_max:
            messagebox.showerror(
                "Data fuori intervallo",
                f"La data deve essere compresa tra {to_italian_date(global_min.isoformat())} e {to_italian_date(global_max.isoformat())}.",
            )
            _refocus_manual()
            return

        nonlocal date_custom_manual_override
        date_custom_manual_override = True
        if which == "from":
            date_from_preview_var.set(dsel.isoformat())
        else:
            date_to_preview_var.set(dsel.isoformat())
        _normalize_range_preview()
        refresh_date_entry_states()
        # Aggiorna subito le tendine Categoria/Conto in base al nuovo intervallo.
        try:
            refresh_category_account_dropdowns()
        except Exception:
            pass
        # Uscita da modalità manuale dopo applicazione.
        nonlocal manual_mode_from, manual_mode_to
        if which == "from":
            manual_mode_from = False
        else:
            manual_mode_to = False
        try:
            date_from_entry.configure(foreground="#111111")
            date_to_entry.configure(foreground="#111111")
        except Exception:
            pass

    def _on_from_enter(_e: tk.Event) -> str:
        _validate_manual_date_and_apply("from")
        return "break"

    def _on_to_enter(_e: tk.Event) -> str:
        _validate_manual_date_and_apply("to")
        return "break"

    def _mask_set_at(s: str, idx: int, ch: str) -> str:
        return s[:idx] + ch + s[idx + 1 :]

    def _mask_next_slot(s: str, start_pos: int) -> int | None:
        for i in _DATE_MASK_POS:
            if i >= start_pos and s[i] == "_":
                return i
        for i in _DATE_MASK_POS:
            if s[i] == "_":
                return i
        return None

    def _mask_prev_filled(s: str, start_pos: int) -> int | None:
        for i in reversed(_DATE_MASK_POS):
            if i < start_pos and s[i] != "_":
                return i
        for i in reversed(_DATE_MASK_POS):
            if s[i] != "_":
                return i
        return None

    def _masked_keypress(which: str, event: tk.Event) -> str | None:
        if date_preset_preview_var.get() != "custom":
            return None
        if which == "from" and not manual_mode_from:
            return None
        if which == "to" and not manual_mode_to:
            return None

        entry = date_from_entry if which == "from" else date_to_entry
        var = date_from_disp_var if which == "from" else date_to_disp_var
        s = var.get() or ""
        if len(s) != len(_DATE_MASK) or s[2] != "/" or s[5] != "/":
            s = _DATE_MASK

        keysym = getattr(event, "keysym", "")
        ch = getattr(event, "char", "")

        # Navigazione: permetti solo le frecce, ma evita di uscire dalla maschera.
        if keysym in ("Left", "Right", "Home", "End", "Tab", "ISO_Left_Tab"):
            return None

        # Backspace: cancella la cifra precedente
        if keysym == "BackSpace":
            pos = entry.index(tk.INSERT)
            prev_i = _mask_prev_filled(s, pos)
            if prev_i is not None:
                s2 = _mask_set_at(s, prev_i, "_")
                var.set(s2)
                entry.icursor(prev_i)
            return "break"

        # Solo cifre: riempi il prossimo slot disponibile
        if ch.isdigit():
            pos = entry.index(tk.INSERT)
            # Se il cursore è fuori maschera, riparti da inizio.
            if pos >= len(_DATE_MASK):
                pos = 0
            next_i = _mask_next_slot(s, pos)
            if next_i is None:
                return "break"
            s2 = _mask_set_at(s, next_i, ch)

            # Validazione immediata per evitare numeri impossibili.
            def _digits_at(ix1: int, ix2: int) -> str:
                return (s2[ix1] if ix1 < len(s2) else "_") + (s2[ix2] if ix2 < len(s2) else "_")

            dd = _digits_at(0, 1)
            mm = _digits_at(3, 4)
            yyyy = "".join(s2[i] for i in (6, 7, 8, 9) if i < len(s2))

            # Giorno: blocca subito valori fuori 01..31
            if next_i in (0, 1):
                # prima cifra giorno: 0..3
                if next_i == 0 and ch not in ("0", "1", "2", "3"):
                    return "break"
                if dd[0] != "_" and dd[1] != "_":
                    day = int(dd)
                    if day < 1 or day > 31:
                        return "break"
                # seconda cifra: se prima è 3, seconda 0..1; se prima è 0, seconda 1..9
                if next_i == 1 and dd[0] != "_":
                    if dd[0] == "3" and ch not in ("0", "1"):
                        return "break"
                    if dd[0] == "0" and ch == "0":
                        return "break"

            # Mese: blocca subito valori fuori 01..12
            if next_i in (3, 4):
                if next_i == 3 and ch not in ("0", "1"):
                    return "break"
                if mm[0] != "_" and mm[1] != "_":
                    month = int(mm)
                    if month < 1 or month > 12:
                        return "break"
                if next_i == 4 and mm[0] != "_":
                    if mm[0] == "1" and ch not in ("0", "1", "2"):
                        return "break"
                    if mm[0] == "0" and ch == "0":
                        return "break"

            # Anno: appena completo, deve stare dentro il range anni del DB (min..max).
            if next_i in (6, 7, 8, 9):
                if all(s2[i].isdigit() for i in (6, 7, 8, 9)):
                    y = int(s2[6:10])
                    if _dataset_years_with_records:
                        y_min = min(_dataset_years_with_records)
                        y_max = max(_dataset_years_with_records)
                    else:
                        y_min = (_dataset_min_date or date.today()).year
                        y_max = (_dataset_max_date or date.today()).year
                    if y < y_min or y > y_max:
                        return "break"

            # Se la data è completa, verifica subito coerenza calendario (mesi, bisestili, ecc.).
            if all(s2[i].isdigit() for i in (0, 1, 3, 4, 6, 7, 8, 9)):
                try:
                    _ = date(int(s2[6:10]), int(s2[3:5]), int(s2[0:2]))
                except Exception:
                    return "break"

            var.set(s2)
            # sposta cursore al prossimo slot (o fine)
            after = next_i + 1
            # salta gli slash
            if after in (2, 5):
                after += 1
            entry.icursor(after)
            return "break"

        # Blocca qualunque altro carattere
        if ch:
            return "break"
        return None

    def _ensure_mask_cursor(which: str) -> None:
        if date_preset_preview_var.get() != "custom":
            return
        if which == "from" and not manual_mode_from:
            return
        if which == "to" and not manual_mode_to:
            return
        entry = date_from_entry if which == "from" else date_to_entry
        var = date_from_disp_var if which == "from" else date_to_disp_var
        s = var.get() or ""
        if s != _DATE_MASK and "_" not in s:
            return
        # se il cursore è dopo la maschera o sugli slash, portalo al primo slot
        try:
            pos = entry.index(tk.INSERT)
        except Exception:
            pos = 0
        if pos >= len(_DATE_MASK) or pos in (2, 5):
            try:
                entry.icursor(0)
            except Exception:
                pass

    date_from_entry.bind("<Return>", _on_from_enter)
    date_to_entry.bind("<Return>", _on_to_enter)
    # Usa add=True per non interferire con binding interni ttk; ritorno "break" blocca l'inserimento.
    date_from_entry.bind("<KeyPress>", lambda e: _masked_keypress("from", e), add=True)
    date_to_entry.bind("<KeyPress>", lambda e: _masked_keypress("to", e), add=True)
    date_from_entry.bind("<FocusIn>", lambda _e: _ensure_mask_cursor("from"), add=True)
    date_to_entry.bind("<FocusIn>", lambda _e: _ensure_mask_cursor("to"), add=True)

    date_from_preview_var.trace_add("write", lambda *_: _sync_date_displays_from_iso())
    date_to_preview_var.trace_add("write", lambda *_: _sync_date_displays_from_iso())

    _sync_date_displays_from_iso()

    refresh_date_preset_button_styles()
    refresh_date_preview_from_modes()
    # Alla prima apertura, la griglia deve riflettere i default preset.
    date_preset_applied_var.set(date_preset_preview_var.get())
    date_from_applied_var.set(date_from_preview_var.get())
    date_to_applied_var.set(date_to_preview_var.get())
    refresh_movement_date_controls_visibility()

    cerca_wrap = tk.Frame(filters_search_row, highlightthickness=0)
    _CERCA_GREEN = "#2e7d32"
    _CERCA_GREEN_ACTIVE = "#1b5e20"
    lbl_cerca = tk.Label(
        cerca_wrap,
        text="Cerca",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=18,
        pady=6,
        bg=_CERCA_GREEN,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    lbl_cerca.bind("<Button-1>", apply_movement_search)
    lbl_cerca.pack()

    def _cerca_enter(_e: tk.Event) -> None:
        lbl_cerca.configure(bg=_CERCA_GREEN_ACTIVE)

    def _cerca_leave(_e: tk.Event) -> None:
        lbl_cerca.configure(bg=_CERCA_GREEN)

    lbl_cerca.bind("<Enter>", _cerca_enter)
    lbl_cerca.bind("<Leave>", _cerca_leave)

    def _position_cerca_over_note_column(_e: tk.Event | None = None) -> None:
        """Posiziona Cerca in corrispondenza della colonna Nota (note_tree)."""
        try:
            # Coord x del note_tree in coordinate schermo.
            note_x = note_tree.winfo_rootx()
            note_w = note_tree.winfo_width()
            row_x = filters_search_row.winfo_rootx()
            # Assicura width calcolati.
            root.update_idletasks()
            btn_w = cerca_wrap.winfo_reqwidth()
            # Allinea a destra dentro la colonna Nota.
            x = max(0, (note_x + note_w - btn_w) - row_x)
            cerca_wrap.place(x=x, y=0)
        except Exception:
            # Fallback: a destra ma con margine
            try:
                cerca_wrap.place(relx=1.0, x=-200, y=0, anchor="ne")
            except Exception:
                pass

    # Riposiziona quando cambia layout/dimensioni.
    filters_search_row.bind("<Configure>", _position_cerca_over_note_column, add=True)
    records_frame.bind("<Configure>", _position_cerca_over_note_column, add=True)
    root.after_idle(_position_cerca_over_note_column)

    refresh_movement_filter_button_styles()

    populate_movements_trees()

    balance_footer = ttk.Frame(movimenti_frame, padding=(0, 6, 0, 0))
    balance_footer.pack(fill=tk.X)
    balance_footer_row = tk.Frame(balance_footer)
    balance_footer_row.pack(fill=tk.X, anchor=tk.CENTER)
    balance_left = tk.Frame(balance_footer_row)
    balance_left.pack(side=tk.LEFT, anchor="w")
    balance_center = tk.Frame(balance_footer_row)
    balance_center.pack(side=tk.LEFT, fill=tk.X, expand=True)

    saldo_footer_font = ("TkDefaultFont", 13)

    def _saldi_snapshot_for_print() -> dict:
        _, names, amts_abs = compute_balances_from_2022(cur_db())
        _, _, amts_today = compute_balances_from_2022_asof(cur_db(), cutoff_date_iso=date.today().isoformat())
        total_abs = sum(amts_abs, Decimal("0"))
        total_today = sum(amts_today, Decimal("0"))
        diffs = [a - b for a, b in zip(amts_abs, amts_today)]
        total_diff = total_abs - total_today
        return {
            "valuta": "E",
            "names": [n.strip() for n in names],
            "amts_abs": amts_abs,
            "amts_today": amts_today,
            "diffs": diffs,
            "total_abs": total_abs,
            "total_today": total_today,
            "total_diff": total_diff,
            "date_it": to_italian_date(date.today().isoformat()),
        }

    def _build_saldi_print_html(
        snap: dict,
        *,
        for_native: bool = False,
        native_text_width_pt: float | None = None,
    ) -> str:
        """Stampa A4: tabella trasposta — righe = conti, colonne = tre tipi di saldo + TOTALE in chiusura.

        Con ``native_text_width_pt=iw`` (solo macOS) colgroup e larghezza tabella sono in **punti** (proporzioni 16/28/28/28).
        """
        valuta = snap["valuta"]
        names: list[str] = snap["names"]
        n_acc = len(names)
        # Sempre A4 verticale: molte righe → continuazione su pagine successive (non orizzontale:
        # in landscape l'altezza utile per le righe diminuisce).
        page_size = "A4"
        # Stampa nativa macOS: margini solo da NSPrintInfo + textContainerInset (evita doppio margine HTML).
        page_margin = "0" if for_native else "7mm"
        body_pad_v, body_pad_h = "1mm", "2mm"
        h1_pt = 10.0
        meta_pt = 7.0
        table_pt = 5.8 if n_acc <= 10 else 5.2
        hdr_pt = round(table_pt * 0.88, 2)
        # Stampa nativa: tabella −12% (0,88) per margine sicuro sull’ultima colonna; font tabella in scala.
        _saldi_shrink = 0.88 if native_text_width_pt is not None else 1.0
        _tbl_pt = round(table_pt * _saldi_shrink, 3)
        _hdr_tbl_pt = round(_tbl_pt * 0.88, 2)
        cell_pad = "1px 2px"
        line_h = 1.05
        body_pad_css = "0" if for_native else f"{body_pad_v} {body_pad_h}"
        # Larghezze colonne: 16% Conti, 28% ciascuna colonna importo (100% totale).
        pct_conti = 16
        pct_amt = 28
        native_root_style = ""
        native_wrap_style = ""
        native_table_style = ""
        if native_text_width_pt is not None:
            _iw = float(native_text_width_pt)
            # Slack orizzontale simmetrico: riduce la larghezza tabella e la centra con padding sul wrap,
            # così bordi/rounding TextKit non tagliano l'ultima colonna (initWithHTML non è un motore browser).
            _slack = 8.0
            _tw_base = max(120.0, _iw - _slack)
            _tw = _tw_base * _saldi_shrink
            _side = max(0.0, (_iw - _tw) / 2.0)
            # Gutter uguale sinistra/destra dentro il wrap: lascia ~1px bordo tabella senza taglio a destra (percezione margine asimmetrico).
            _edge_gutter_pt = 5.0
            _inner_tw = max(100.0, _tw - 2.0 * _edge_gutter_pt)
            _pad_h = _side + _edge_gutter_pt
            w_c = _inner_tw * pct_conti / 100.0
            w_a = _inner_tw * pct_amt / 100.0
            colgroup_html = (
                "<colgroup>"
                f'<col class="col-conti" style="width:{w_c:.2f}pt" />'
                f'<col style="width:{w_a:.2f}pt" />'
                f'<col style="width:{w_a:.2f}pt" />'
                f'<col style="width:{w_a:.2f}pt" />'
                "</colgroup>"
            )
            native_root_style = (
                f' style="width:{_iw:.2f}pt;max-width:{_iw:.2f}pt;margin:0;padding:0;box-sizing:border-box;"'
            )
            # border-box + padding orizzontale _side: area interna = iw - 2*_side = _tw (centra senza margin sulla table;
            # margin-right su <table> è spesso ignorato da initWithHTML e spinge il taglio a destra).
            native_wrap_style = (
                f' style="width:{_iw:.2f}pt;max-width:{_iw:.2f}pt;margin:0;'
                f'padding:6mm {_pad_h:.2f}pt 0 {_pad_h:.2f}pt;box-sizing:border-box;text-align:left;"'
            )
            native_table_style = (
                f' style="width:{_inner_tw:.2f}pt;max-width:{_inner_tw:.2f}pt;margin:0;padding:0;'
                f'table-layout:fixed;border-collapse:collapse;border-spacing:0;"'
            )
        else:
            colgroup_html = (
                "<colgroup>"
                f'<col class="col-conti" style="width:{pct_conti}%" />'
                f'<col style="width:{pct_amt}%" />'
                f'<col style="width:{pct_amt}%" />'
                f'<col style="width:{pct_amt}%" />'
                "</colgroup>"
            )
        _table_width_css_block = (
            f"""  table.saldi {{
    width: 88%;
    max-width: 100%;
    margin: 0 auto;
    table-layout: fixed;
    border-collapse: collapse;
    border-spacing: 0;
    font-size: {_tbl_pt}pt;
    line-height: {line_h};
  }}"""
            if native_text_width_pt is None
            else f"""  table.saldi {{
    table-layout: fixed;
    border-collapse: collapse;
    border-spacing: 0;
    font-size: {_tbl_pt}pt;
    line-height: {line_h};
  }}"""
        )

        def conti_cell(label: str) -> str:
            s = (label or "").strip()[:10]
            return f'<td class="row-label">{html_module.escape(s)}</td>'

        def td_num(amt: Decimal, *, bold: bool) -> str:
            fg = balance_amount_fg(amt)
            t = html_module.escape(format_saldo_cell(valuta, amt))
            cls = "num amt-b" if bold else "num amt-n"
            inner = f"<strong>{t}</strong>" if bold else t
            return f'<td class="{cls}" style="color:{html_module.escape(fg)}">{inner}</td>'

        header_cells = (
            '<th class="hdr-name">Conti</th>'
            '<th class="col-hdr col-hdr-b"><strong>Saldi alla data<br/>di oggi</strong></th>'
            '<th class="col-hdr col-hdr-n">Differenze</th>'
            '<th class="col-hdr col-hdr-b"><strong>Saldi assoluti</strong></th>'
        )

        body_lines: list[str] = []
        for i, nm in enumerate(names):
            body_lines.append(
                "<tr>"
                + conti_cell(nm)
                + td_num(snap["amts_today"][i], bold=True)
                + td_num(snap["diffs"][i], bold=False)
                + td_num(snap["amts_abs"][i], bold=True)
                + "</tr>"
            )
        body_lines.append(
            '<tr class="totale">'
            + conti_cell("TOTALE")
            + td_num(snap["total_today"], bold=True)
            + td_num(snap["total_diff"], bold=False)
            + td_num(snap["total_abs"], bold=True)
            + "</tr>"
        )
        tbody_html = "\n".join(body_lines)

        return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<title>Conti di casa — Saldi</title>
<style>
  @page {{ size: {page_size}; margin: {page_margin}; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  body {{ padding: {body_pad_css}; color: #1a1a1a; text-align: left; }}
  .print-root {{ width: 100%; max-width: 100%; margin: 0; padding: 0; text-align: left; }}
  .print-head {{ width: 100%; max-width: 100%; margin: 0; padding: 0; text-align: center; box-sizing: border-box; }}
  h1 {{ font-size: {h1_pt}pt; text-align: center; margin: 0 0 1mm 0; padding: 0; font-weight: 700; line-height: 1.1; width: 100%; }}
  .meta {{ text-align: center; margin: 0; padding: 0 0 5mm 0; font-size: {meta_pt}pt; line-height: 1.1; width: 100%; }}
  .saldi-table-wrap {{ width: 100%; margin: 0; padding: 6mm 0 0 0; text-align: left; box-sizing: border-box; }}
{_table_width_css_block}
  thead {{ display: table-header-group; }}
  .saldi tbody tr {{ page-break-inside: avoid; }}
  .saldi th, .saldi td {{
    border: 1px solid #333;
    padding: {cell_pad};
    vertical-align: middle;
    white-space: nowrap;
  }}
  .saldi th {{
    background: #ebebeb;
    vertical-align: middle;
  }}
  .saldi th.hdr-name {{
    text-align: left;
    font-size: {_tbl_pt}pt;
    font-weight: 700;
    overflow: hidden;
    text-overflow: clip;
  }}
  .saldi th.col-hdr {{
    text-align: center;
    font-size: {_hdr_tbl_pt}pt;
    line-height: 1.12;
    white-space: normal;
    overflow: visible;
  }}
  .saldi th.col-hdr-b {{ font-weight: 700; }}
  .saldi th.col-hdr-n {{ font-weight: 400; }}
  .saldi td.row-label {{
    font-weight: 600;
    text-align: left;
    background: #fafafa;
    overflow: hidden;
    text-overflow: clip;
  }}
  .saldi tr.totale td.row-label {{ font-weight: 700; }}
  .saldi tr.totale td {{ background: #f0f0f0; }}
  .saldi td.num {{
    text-align: right;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    overflow: visible;
    letter-spacing: -0.04em;
  }}
  .saldi td.amt-b strong {{ font-weight: 700; }}
  .saldi td.amt-n {{ font-weight: 400; }}
  @media print {{
    body {{ padding: 0; margin: 0; }}
    .print-root {{ margin: 0; padding: 0; }}
    .print-head {{ text-align: center; }}
    h1 {{ margin-top: 0; text-align: center; }}
    .saldi-table-wrap {{ padding-top: 6mm; }}
    .noprint {{ display: none !important; }}
  }}
</style>
</head>
<body>
<div class="print-root"{native_root_style}>
<div class="print-head">
<h1 style="margin:0 0 1mm 0;padding:0;text-align:center;width:100%;font-weight:700;">Conti di casa</h1>
<div class="meta" style="margin:0;padding:0 0 5mm 0;text-align:center;width:100%;">Data: {html_module.escape(snap["date_it"])}</div>
</div>
<div class="saldi-table-wrap"{native_wrap_style}>
<table class="saldi" role="table"{native_table_style}>
{colgroup_html}
<thead><tr>{header_cells}</tr></thead>
<tbody>
{tbody_html}
</tbody>
</table>
</div>
</div>
{(
            '<p class="noprint" style="margin-top:8mm;font-size:9pt;color:#555;text-align:center;">'
            "Se la finestra di stampa non si apre, usa il comando Stampa del browser (es. Cmd+P / Ctrl+P)."
            "</p>"
            "<script>"
            'window.addEventListener("load", function () {'
            "setTimeout(function () { window.print(); }, 400);"
            "});"
            "</script>"
            if not for_native
            else ""
        )}
</body>
</html>
"""

    def _print_saldi_via_browser(html_doc: str) -> None:
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
                f.write(html_doc)
                tmp_path = Path(f.name).resolve()
            uri = tmp_path.as_uri()
            webbrowser.open(uri)
        except Exception as exc:
            picked = filedialog.asksaveasfilename(
                defaultextension=".html",
                filetypes=[("HTML", "*.html"), ("Tutti i file", "*.*")],
                initialfile=f"saldi_{date.today().isoformat()}.html",
            )
            if picked:
                Path(picked).write_text(html_doc, encoding="utf-8")
                try:
                    webbrowser.open(Path(picked).resolve().as_uri())
                except Exception:
                    messagebox.showerror("Stampa saldi", str(exc))
            else:
                messagebox.showerror("Stampa saldi", str(exc))

    def _print_ricerca_via_browser(html_doc: str) -> None:
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
                f.write(html_doc)
                tmp_path = Path(f.name).resolve()
            uri = tmp_path.as_uri()
            webbrowser.open(uri)
        except Exception as exc:
            picked = filedialog.asksaveasfilename(
                defaultextension=".html",
                filetypes=[("HTML", "*.html"), ("Tutti i file", "*.*")],
                initialfile=f"ricerca_{date.today().isoformat()}.html",
            )
            if picked:
                Path(picked).write_text(html_doc, encoding="utf-8")
                try:
                    webbrowser.open(Path(picked).resolve().as_uri())
                except Exception:
                    messagebox.showerror("Stampa ricerca", str(exc))
            else:
                messagebox.showerror("Stampa ricerca", str(exc))

    def _build_ricerca_print_html(
        rows: list[tuple[str, str, tuple[object, ...], str, str, str, str]],
        search_desc: str,
        *,
        for_native: bool = False,
        native_text_width_pt: float | None = None,
    ) -> str:
        """HTML stampa elenco movimenti filtrati: titolo/data come saldi, descrizione ricerca, tabella 2 righe/reg."""
        page_size = "A4"
        page_margin = "0" if for_native else "7mm"
        body_pad_css = "0" if for_native else "2mm 3mm"
        h1_pt = 10.0
        meta_pt = 7.0
        tbl_pt = 5.4 if for_native else 6.2
        desc_pt = 7.8
        date_it = to_italian_date(date.today().isoformat())
        desc_esc = html_module.escape(search_desc or "(nessuna descrizione)")
        native_root_style = ""
        if native_text_width_pt is not None:
            _iw = float(native_text_width_pt)
            native_root_style = (
                f' style="width:{_iw:.2f}pt;max-width:{_iw:.2f}pt;margin:0;padding:0;box-sizing:border-box;"'
            )
        # Data/asterischi: altro +10% sui pesi attuali; compensato su Assegno; normalizzazione a 100%.
        _w_base = [6.0, 10.56, 21.0, 14.0, 0.968, 14.0, 0.968, 5.104, 24.0]
        _w_sum = sum(_w_base)
        _col_pct = [round(100.0 * x / _w_sum, 3) for x in _w_base]
        colgroup_html = "".join(f'<col style="width:{p:.3f}%" />' for p in _col_pct)
        body_lines: list[str] = []
        for _rid, reg_text, mov_vals, amount_text, amount_tag, note_text, _stripe in rows:
            dt, cat, a1, s1, a2, s2, chq = mov_vals
            fg = COLOR_AMOUNT_NEG if amount_tag == "neg" else COLOR_AMOUNT_POS
            reg_e = html_module.escape(str(reg_text))
            dt_e = html_module.escape(str(dt))
            cat_e = html_module.escape((str(cat or "")).strip()[:14])
            a1_e = html_module.escape((str(a1 or "")).strip()[:10])
            s1_e = html_module.escape(str(s1 or ""))
            a2_e = html_module.escape((str(a2 or "")).strip()[:10])
            s2_e = html_module.escape(str(s2 or ""))
            chq_e = html_module.escape(str(chq or ""))
            amt_e = html_module.escape(str(amount_text))
            note_e = html_module.escape(str(note_text or "")).replace("\n", "<br/>")
            body_lines.append(
                '<tr class="r-main">'
                f'<td class="r-num">{reg_e}</td>'
                f'<td class="r-dt">{dt_e}</td>'
                f'<td class="r-cat">{cat_e}</td>'
                f'<td class="r-a1">{a1_e}</td>'
                f'<td class="r-f1">{s1_e}</td>'
                f'<td class="r-a2">{a2_e}</td>'
                f'<td class="r-f2">{s2_e}</td>'
                f'<td class="r-chq">{chq_e}</td>'
                f'<td class="r-amt" style="color:{html_module.escape(fg)};font-weight:700;">{amt_e}</td>'
                "</tr>"
                f'<tr class="r-note"><td colspan="9"><div class="note-wrap">{note_e}</div></td></tr>'
            )
        tbody_html = "\n".join(body_lines) if body_lines else (
            '<tr><td colspan="9" style="text-align:center;">Nessuna registrazione</td></tr>'
        )
        return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8"/>
<title>Conti di casa — Stampa ricerca</title>
<style>
  @page {{ size: {page_size}; margin: {page_margin}; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
  body {{ padding: {body_pad_css}; color: #1a1a1a; }}
  .print-root {{ width: 100%; max-width: 100%; margin: 0; padding: 0; overflow-x: hidden; }}
  h1 {{ font-size: {h1_pt}pt; text-align: center; margin: 0 0 1mm 0; padding: 0; font-weight: 700; line-height: 1.1; width: 100%; }}
  .meta {{ text-align: center; margin: 0; padding: 0 0 4mm 0; font-size: {meta_pt}pt; line-height: 1.1; width: 100%; }}
  .search-desc {{ font-size: {desc_pt}pt; font-weight: 700; margin: 0 0 4mm 0; padding: 0; line-height: 1.25; }}
  table.ricerca {{
    width: 100%;
    max-width: 100%;
    min-width: 0;
    border-collapse: collapse;
    border-spacing: 0;
    font-size: {tbl_pt}pt;
    line-height: 1.15;
    table-layout: fixed;
  }}
  table.ricerca th, table.ricerca td {{
    padding: 1px 3px;
    vertical-align: top;
    word-wrap: break-word;
    overflow-wrap: anywhere;
  }}
  /* Data e asterischi: una sola riga (no a capo); overflow nascosto. */
  table.ricerca td.r-dt,
  table.ricerca td.r-f1,
  table.ricerca td.r-f2 {{
    white-space: nowrap !important;
    overflow: hidden;
    text-overflow: ellipsis;
    word-wrap: normal;
    overflow-wrap: normal;
  }}
  table.ricerca thead th:nth-child(2),
  table.ricerca thead th:nth-child(5),
  table.ricerca thead th:nth-child(7) {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .ricerca-shell {{
    width: 100%;
    max-width: 100%;
    overflow: hidden;
    box-sizing: border-box;
  }}
  /* Bordi leggeri tra celle; contorno “blocco registrazione” più scuro su r-main + r-note */
  table.ricerca thead th {{
    background: #ebebeb;
    font-weight: 700;
    text-align: center;
    border: 1px solid #2a2a2a;
  }}
  table.ricerca tr.r-main td {{
    border: 1px solid #c8c8c8;
    border-top: 1.5px solid #2a2a2a;
    border-bottom: 1px solid #c8c8c8;
  }}
  table.ricerca tr.r-main td:first-child {{ border-left: 1.5px solid #2a2a2a; }}
  table.ricerca tr.r-main td:last-child {{ border-right: 1.5px solid #2a2a2a; }}
  table.ricerca tr.r-note td {{
    font-size: {tbl_pt * 0.95:.2f}pt;
    font-weight: 400;
    background: #fafafa;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
    width: 100%;
    max-width: 100%;
    border-left: 1.5px solid #2a2a2a;
    border-right: 1.5px solid #2a2a2a;
    border-bottom: 1.5px solid #2a2a2a;
    border-top: 1px solid #c8c8c8;
    overflow: hidden;
    box-sizing: border-box;
  }}
  table.ricerca tr.r-note .note-wrap {{
    display: block;
    min-width: 0;
    max-width: 100%;
    width: 100%;
    box-sizing: border-box;
    overflow-wrap: anywhere;
    word-break: break-word;
    overflow: hidden;
  }}
  table.ricerca td.r-num {{ text-align: right; white-space: nowrap; }}
  table.ricerca td.r-dt {{ text-align: right; }}
  table.ricerca td.r-cat {{ text-align: left; }}
  table.ricerca td.r-a1 {{ text-align: left; }}
  table.ricerca td.r-f1 {{ text-align: center; }}
  table.ricerca td.r-a2 {{ text-align: left; }}
  table.ricerca td.r-f2 {{ text-align: center; }}
  table.ricerca td.r-chq {{ text-align: center; }}
  table.ricerca td.r-amt {{ text-align: right; white-space: nowrap; font-family: ui-monospace, Menlo, monospace; }}
  @media print {{
    body {{ padding: 0; margin: 0; }}
    .noprint {{ display: none !important; }}
  }}
</style>
</head>
<body>
<div class="print-root"{native_root_style}>
<h1 style="margin:0 0 1mm 0;padding:0;text-align:center;width:100%;font-weight:700;">Conti di casa</h1>
<div class="meta" style="margin:0;padding:0 0 4mm 0;text-align:center;width:100%;">Data: {html_module.escape(date_it)}</div>
<p class="search-desc">{desc_esc}</p>
<div class="ricerca-shell">
<table class="ricerca" role="table">
<colgroup>
{colgroup_html}
</colgroup>
<thead><tr>
<th>Reg #</th><th>Data</th><th>Categoria</th><th>Dal conto</th><th></th><th>al conto</th><th></th><th>Assegno</th><th>Importo</th>
</tr></thead>
<tbody>
{tbody_html}
</tbody>
</table>
</div>
</div>
{(
            '<p class="noprint" style="margin-top:8mm;font-size:9pt;color:#555;text-align:center;">'
            "Apri Stampa dal browser (Cmd+P / Ctrl+P) se necessario."
            "</p>"
            "<script>"
            'window.addEventListener("load", function () {'
            "setTimeout(function () { window.print(); }, 400);"
            "});"
            "</script>"
            if not for_native
            else ""
        )}
</body>
</html>
"""

    def _print_ricerca_direct() -> None:
        try:
            refresh_search_title()
        except Exception:
            pass
        desc = (search_title_var.get() or "").strip()
        d = cur_db()
        accounts_by_year = year_accounts_map(d)
        categories_by_year = year_categories_map(d)
        records = [r for y in d["years"] for r in y["records"]]
        records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        reg_seq_map = unified_registration_sequence_map(records)
        pool = filter_and_sort_movements_for_grid(
            records,
            reg_seq_map,
            order_by_date=filter_order_applied_var.get() == "date",
            exclude_future_dates=filter_future_applied_var.get() == "exclude",
            backward=filter_direction_applied_var.get() == "backward",
            date_from_iso=(
                date_from_applied_var.get()
                if filter_order_applied_var.get() == "date"
                else (
                    _scope_dates_for_registration(reg_preset_applied_var.get())[0]
                    if filter_order_applied_var.get() == "registration"
                    else None
                )
            ),
            date_to_iso=(
                date_to_applied_var.get()
                if filter_order_applied_var.get() == "date"
                else (
                    _scope_dates_for_registration(reg_preset_applied_var.get())[1]
                    if filter_order_applied_var.get() == "registration"
                    else None
                )
            ),
        )
        rows = _movement_rows_from_pool(pool, reg_seq_map, accounts_by_year, categories_by_year)
        n = len(rows)
        if n == 0:
            messagebox.showinfo("Stampa ricerca", "Nessuna registrazione da stampare con i filtri attuali.")
            return
        if not messagebox.askokcancel(
            "Stampa ricerca",
            f"Verranno comprese nella stampa {n} registrazioni.\n\n"
            "Puoi annullare se l’elenco è troppo lungo.",
        ):
            return
        sysname = platform.system()
        if sysname == "Darwin":

            def _mk_r(iw: float) -> str:
                return _build_ricerca_print_html(
                    rows, desc, for_native=True, native_text_width_pt=iw
                )

            if _print_balances_native_macos(_mk_r):
                return
        elif sysname == "Windows":
            html_native = _build_ricerca_print_html(rows, desc, for_native=True)
            if _print_balances_native_windows(html_native):
                return
            if _print_balances_windows_pywebview(html_native):
                return
        _print_ricerca_via_browser(_build_ricerca_print_html(rows, desc, for_native=False))

    btn_stampa_ricerca.bind("<Button-1>", lambda _e: _print_ricerca_direct())
    btn_stampa_ricerca.bind("<Enter>", lambda _e: btn_stampa_ricerca.configure(bg=_PRINT_RICERCA_RED_ACTIVE))
    btn_stampa_ricerca.bind("<Leave>", lambda _e: btn_stampa_ricerca.configure(bg=_PRINT_RICERCA_RED))

    def _print_saldi_direct() -> None:
        snap = _saldi_snapshot_for_print()
        sysname = platform.system()
        if sysname == "Darwin":

            def _mac_html(iw: float) -> str:
                return _build_saldi_print_html(snap, for_native=True, native_text_width_pt=iw)

            if _print_balances_native_macos(_mac_html):
                return
        elif sysname == "Windows":
            html_native = _build_saldi_print_html(snap, for_native=True)
            if _print_balances_native_windows(html_native):
                return
            if _print_balances_windows_pywebview(html_native):
                return
            if _print_balances_windows_fpdf(snap):
                return
        _print_saldi_via_browser(_build_saldi_print_html(snap, for_native=False))

    _PRINT_RED = "#c62828"
    _PRINT_RED_ACTIVE = "#8e0000"
    btn_stampa_saldi = tk.Label(
        balance_left,
        text="Stampa saldi",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=12,
        pady=6,
        bg=_PRINT_RED,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_stampa_saldi.pack(anchor="w")
    btn_stampa_saldi.bind("<Button-1>", lambda _e: _print_saldi_direct())
    btn_stampa_saldi.bind("<Enter>", lambda _e: btn_stampa_saldi.configure(bg=_PRINT_RED_ACTIVE))
    btn_stampa_saldi.bind("<Leave>", lambda _e: btn_stampa_saldi.configure(bg=_PRINT_RED))

    def refresh_balance_footer() -> None:
        for w in balance_center.winfo_children():
            w.destroy()
        _, names, amts_abs = compute_balances_from_2022(cur_db())
        _, _, amts_today = compute_balances_from_2022_asof(cur_db(), cutoff_date_iso=date.today().isoformat())
        total_abs = sum(amts_abs, Decimal("0"))
        total_today = sum(amts_today, Decimal("0"))
        diffs = [a - b for a, b in zip(amts_abs, amts_today)]
        total_diff = total_abs - total_today

        # Layout a tabella: intestazione + 3 righe.
        table = tk.Frame(balance_center)
        # Centra l'intera area saldi nel footer.
        table.pack(anchor=tk.CENTER)

        header_font = ("TkDefaultFont", 13, "bold")
        amount_font = ("TkDefaultFont", 13, "bold")

        def header_cell(col: int, text: str) -> None:
            tk.Label(table, text=text, font=header_font).grid(row=0, column=col, sticky="w", padx=(0, 10), pady=0)

        def label_cell(row: int, text: str) -> None:
            tk.Label(table, text=text, font=saldo_footer_font).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=0)

        def amount_cell(row: int, col: int, amt: Decimal) -> None:
            tk.Label(
                table,
                text=format_saldo_cell("E", amt),
                font=amount_font,
                fg=balance_amount_fg(amt),
                anchor=tk.E,
            ).grid(row=row, column=col, sticky="e", padx=(0, 10), pady=0)

        # Intestazione colonne (1 = totale, poi conti)
        header_cell(0, "")
        header_cell(1, "TOTALE")
        for i, name in enumerate(names, start=2):
            header_cell(i, name.strip())

        # Righe
        label_cell(1, "Saldi alla data di oggi")
        amount_cell(1, 1, total_today)
        for i, amt in enumerate(amts_today, start=2):
            amount_cell(1, i, amt)

        label_cell(2, "Differenze")
        amount_cell(2, 1, total_diff)
        for i, amt in enumerate(diffs, start=2):
            amount_cell(2, i, amt)

        label_cell(3, "Saldi assoluti")
        amount_cell(3, 1, total_abs)
        for i, amt in enumerate(amts_abs, start=2):
            amount_cell(3, i, amt)

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
        print(
            "Primo avvio: import dell'archivio legacy in corso (può richiedere tempo; attendere).",
            file=sys.stderr,
        )
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
