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

from import_legacy import (
    EURO_CONVERSION_RATE,
    MAX_CHEQUE_LEN,
    MAX_RECORD_NOTE_LEN,
    format_euro_it,
    format_money,
    normalize_euro_input,
    run_import_legacy,
)


DEFAULT_CDC_ROOT = Path("/Users/macand/Library/CloudStorage/Dropbox/CdC")
DEFAULT_OUTPUT = Path("data/unified_legacy_import.json")
DEFAULT_ENCRYPTED_DB = Path("data/conti_di_casa.enc")
DEFAULT_BACKUP_ENCRYPTED_DB = (
    Path.home() / "Library" / "Application Support" / "ContiDiCasa" / "conti_di_casa_backup.enc"
)
DEFAULT_KEY_FILE = Path("data/conti_di_casa.key")
DEBUG_LOG_PATH = "/Users/macand/Library/CloudStorage/Dropbox/CursorAppMacCdc/.cursor/debug-8c5304.log"
DEBUG_SESSION_ID = "8c5304"

# Inserimento griglia a lotti: migliaia di righe × 3 Treeview bloccano il main thread (macOS: beach ball).
MOVEMENTS_INSERT_BATCH = 400

# TODO (aggiunta / gestione conti): definire e applicare un limite massimo di conti attivi
# (coerente con DB, footer saldi, stampa, griglia). Oggi non c'è un tetto applicato nel codice.

# Stessa regola della colonna Importo nella griglia movimenti.
COLOR_AMOUNT_POS = "#006400"
COLOR_AMOUNT_NEG = "#b22222"


def app_title_text() -> str:
    return f"Conti di casa - {date.today().strftime('%d/%m/%Y')}"


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            "sessionId": DEBUG_SESSION_ID,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass


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


def parse_italian_ddmmyyyy_to_iso(s: str) -> str | None:
    """Come i campi data in Movimenti: gg/mm/aaaa o ISO YYYY-MM-DD."""
    s = (s or "").strip()
    if not s:
        return None
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


def date_minus_calendar_years(d: date, years: int) -> date:
    y = d.year - years
    m, day = d.month, d.day
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(day, last))


def record_is_within_edit_age(rec: dict, *, today: date | None = None) -> bool:
    """False se la data registrazione è più vecchia di 5 anni rispetto a oggi."""
    today = today or date.today()
    iso = str(rec.get("date_iso", "")).strip()
    if not iso:
        return False
    try:
        rd = date.fromisoformat(iso)
    except Exception:
        return False
    cutoff = date_minus_calendar_years(today, 5)
    return rd >= cutoff


def record_is_within_forza_verifica_recency(rec: dict, *, today: date | None = None) -> bool:
    """True se la registrazione non è più vecchia di 1 anno rispetto a oggi (pulsante Forza verifica)."""
    today = today or date.today()
    iso = str(rec.get("date_iso", "")).strip()
    if not iso:
        return False
    try:
        rd = date.fromisoformat(iso)
    except Exception:
        return False
    cutoff = date_minus_calendar_years(today, 1)
    return rd >= cutoff


def record_has_account_verification_flags(rec: dict) -> bool:
    """Asterisco/i accanto al conto: blocca modifica conti e importo."""
    f1 = str(rec.get("account_primary_flags") or "")
    f2 = str(rec.get("account_secondary_flags") or "")
    return "*" in f1 or "*" in f2


def category_display_name(raw: str) -> str:
    base = (raw or "").strip()
    return base[1:].strip() if base[:1] in {"+", "-", "="} else base


def sync_record_category_from_plan(rec: dict, year_categories: list[dict[str, str]], code_str: str) -> None:
    rec["category_code"] = code_str
    if str(code_str).isdigit():
        idx = int(code_str)
        if 0 <= idx < len(year_categories):
            rec["category_name"] = year_categories[idx].get("name") or rec.get("category_name") or ""


def sync_record_primary_account(rec: dict, year_accounts: list[dict[str, str]], idx0: int) -> None:
    if not (0 <= idx0 < len(year_accounts)):
        return
    code = str(idx0 + 1)
    fl = str(rec.get("account_primary_flags") or "")
    rec["account_primary_code"] = code
    rec["account_primary_with_flags"] = f"{code}{fl}" if fl else code
    rec["account_primary_name"] = year_accounts[idx0].get("name") or ""


def sync_record_secondary_account(rec: dict, year_accounts: list[dict[str, str]], idx0: int) -> None:
    if not (0 <= idx0 < len(year_accounts)):
        return
    code = str(idx0 + 1)
    fl = str(rec.get("account_secondary_flags") or "")
    rec["account_secondary_code"] = code
    rec["account_secondary_with_flags"] = f"{code}{fl}" if fl else code
    rec["account_secondary_name"] = year_accounts[idx0].get("name") or ""


def parse_lire_amount_input(s: str) -> Decimal:
    t = (s or "").replace(" ", "").replace("L", "").replace("l", "").strip()
    t = t.replace(".", "").replace(",", "")
    if not t or not t.lstrip("-").isdigit():
        raise ValueError("Importo in lire non valido")
    return Decimal(int(t))


def sanitize_single_line_text(value: str, *, max_len: int | None = None) -> str:
    """Normalizza testo utente su una riga (rimuove CR/LF) e applica trim/lunghezza."""
    out = (value or "").replace("\r", " ").replace("\n", " ").strip()
    return out[:max_len] if max_len is not None else out


def apply_amount_to_record(rec: dict, amount: Decimal) -> None:
    year = int(rec.get("year", 0))
    if year <= 2001 and rec.get("amount_lire_original") is not None:
        li = int(amount.quantize(Decimal("1")))
        rec["amount_lire_original"] = format_money(Decimal(li))
        rec["amount_eur"] = format_money((Decimal(li) / EURO_CONVERSION_RATE).quantize(Decimal("0.001")))
    else:
        rec["amount_eur"] = format_money(amount.quantize(Decimal("0.01")))


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


def _open_generated_pdf(path: str) -> None:
    sysname = platform.system()
    # #region agent log
    _debug_log("n/a", "H4", "main_app.py:_open_generated_pdf", "opening_generated_pdf", {"sysname": sysname, "path": path})
    # #endregion
    if sysname == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    if sysname == "Darwin":
        subprocess.run(["open", path], check=False)
        return
    webbrowser.open(Path(path).as_uri())


def _pdf_safe_text(value: object) -> str:
    s = str(value if value is not None else "")
    return (
        s.replace("€", "EUR")
        .replace("–", "-")
        .replace("—", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )


def _print_balances_fpdf(snap: dict) -> bool:
    """Fallback Windows: PDF A4 verticale, tabella trasposta (4 colonne come HTML)."""
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        return False
    names: list[str] = snap["names"]
    valuta: str = snap["valuta"]
    n = len(names)
    run_id = f"saldi_{int(time.time() * 1000)}"
    # #region agent log
    _debug_log(run_id, "H1", "main_app.py:_print_balances_fpdf", "enter_balances_fpdf", {"names_count": len(names)})
    # #endregion
    try:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        # Evita titoli/heading con nome file nel PDF viewer.
        try:
            pdf.set_title("")
            pdf.set_subject("")
            pdf.set_author("")
            pdf.set_creator("")
            pdf.set_keywords("")
        except Exception:
            pass
        pdf.set_margins(15, 15, 15)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(
            0,
            6,
            _pdf_safe_text(f"Conti di casa - stampa dei saldi al {snap['date_it']}"),
            align="C",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        # Spazio verticale data → tabella (~5 mm sotto la data + ~6 mm prima della tabella, come HTML).
        pdf.ln(11)

        epw = pdf.epw
        _sh = 0.88
        tw = epw * _sh
        x_table = pdf.l_margin + (epw - tw) / 2.0
        w_conti = tw * 0.16
        w_amt = tw * 0.28
        font_boost = 1.4
        line_h = (6.5 if n > 12 else 7.0) * _sh * font_boost
        fs_head = round(7 * _sh * font_boost, 2)
        fs_body = round(7 * _sh * font_boost, 2)

        def amt_cell(amt: Decimal, w: float, *, bold: bool) -> None:
            fg = balance_amount_fg(amt)
            r, g, b = _hex_to_rgb_triplet(fg)
            pdf.set_text_color(r, g, b)
            pdf.set_font("Helvetica", "B" if bold else "", fs_body)
            pdf.cell(w, line_h, _pdf_safe_text(format_saldo_cell(valuta, amt)), border=1, align="R")

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
            show_nm = _pdf_safe_text((nm or "").strip()[:10])
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
            pdf.cell(w_amt, line_h, _pdf_safe_text(format_saldo_cell(valuta, amt)), border=1, align="R", fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(line_h)

        fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="saldi_")
        os.close(fd)
        pdf.output(out_path)
        _open_generated_pdf(out_path)
        # #region agent log
        _debug_log(run_id, "H1", "main_app.py:_print_balances_fpdf", "balances_fpdf_success", {"out_path": out_path})
        # #endregion
        return True
    except Exception as exc:
        # #region agent log
        _debug_log(run_id, "H1", "main_app.py:_print_balances_fpdf", "balances_fpdf_exception", {"error": repr(exc)})
        # #endregion
        return False


def _print_ricerca_fpdf(
    rows: list[tuple[str, str, tuple[object, ...], str, str, str, str]],
    search_desc: str,
) -> bool:
    run_id = f"ricerca_{int(time.time() * 1000)}"
    # #region agent log
    _debug_log(run_id, "H1", "main_app.py:_print_ricerca_fpdf", "enter_ricerca_fpdf", {"rows_count": len(rows)})
    # #endregion
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        try:
            pdf.set_title("")
            pdf.set_subject("")
            pdf.set_author("")
            pdf.set_creator("")
            pdf.set_keywords("")
        except Exception:
            pass
        pdf.set_auto_page_break(auto=True, margin=8)
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(
            0,
            7,
            _pdf_safe_text(f"Conti di casa - {to_italian_date(date.today().isoformat())}"),
            align="C",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 8)
        pdf.multi_cell(0, 5, _pdf_safe_text(search_desc or "(nessuna descrizione)"))
        pdf.ln(1)

        headers = ["Reg #", "Data", "Categoria", "Dal conto", "*", "al conto", "*", "Assegno", "Importo"]
        widths = [12, 19.55, 34, 25, 4.5, 25, 4.5, 14.7, 48]
        row_h = 5.0
        fs_boost = 1.25

        def _header() -> None:
            pdf.set_font("Helvetica", "B", max(5.5, round(8 * fs_boost - 1, 2)))
            for h, w in zip(headers, widths):
                pdf.cell(w, row_h + 1, h, border=1, align="C")
            pdf.ln(row_h + 1)

        _header()
        thin_lw = 0.08
        outer_lw = 0.5
        total_w = sum(widths)
        for _rid, reg_text, mov_vals, amount_text, _amount_tag, note_text, _stripe in rows:
            dt, cat, a1, s1, a2, s2, chq = mov_vals
            vals = [
                _pdf_safe_text(str(reg_text)),
                _pdf_safe_text(str(dt)),
                _pdf_safe_text(str(cat)[:14]),
                _pdf_safe_text(str(a1)[:10]),
                _pdf_safe_text(str(s1)),
                _pdf_safe_text(str(a2)[:10]),
                _pdf_safe_text(str(s2)),
                _pdf_safe_text(str(chq or "")),
                _pdf_safe_text(str(amount_text)),
            ]
            if pdf.get_y() > 275:
                pdf.add_page()
                _header()
            block_x = pdf.l_margin
            block_y = pdf.get_y()
            base_body = max(5.5, round(7.5 * fs_boost - 1, 2))
            pdf.set_line_width(thin_lw)
            for i, (v, w) in enumerate(zip(vals, widths)):
                align = "R" if i in (0, 1, 8) else ("C" if i in (4, 6) else "L")
                if i == 8:
                    fg = COLOR_AMOUNT_NEG if _amount_tag == "neg" else COLOR_AMOUNT_POS
                    r, g, b = _hex_to_rgb_triplet(fg)
                    pdf.set_text_color(r, g, b)
                    pdf.set_font("Helvetica", "B", base_body)
                else:
                    pdf.set_text_color(0, 0, 0)
                    pdf.set_font("Helvetica", "", base_body)
                pdf.cell(w, row_h, v, border=1, align=align)
            pdf.ln(row_h)
            if note_text:
                note = _pdf_safe_text(str(note_text).replace("\n", " ").strip())
                pdf.set_text_color(0, 0, 0)
                pdf.set_font("Helvetica", "", max(5.5, round(7 * fs_boost - 1, 2)))
                pdf.set_line_width(thin_lw)
                pdf.cell(sum(widths), row_h, note[:260], border=1, align="L")
                pdf.ln(row_h)
            block_h = pdf.get_y() - block_y
            pdf.set_line_width(outer_lw)
            pdf.rect(block_x, block_y, total_w, block_h)

        fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="ricerca_")
        os.close(fd)
        pdf.output(out_path)
        _open_generated_pdf(out_path)
        # #region agent log
        _debug_log(run_id, "H1", "main_app.py:_print_ricerca_fpdf", "ricerca_fpdf_success", {"out_path": out_path})
        # #endregion
        return True
    except Exception as exc:
        # #region agent log
        _debug_log(run_id, "H1", "main_app.py:_print_ricerca_fpdf", "ricerca_fpdf_exception", {"error": repr(exc)})
        # #endregion
        return False


def show_record_in_movements_grid(rec: dict) -> bool:
    """Dotazione iniziale (cat.0 legacy) non più mostrata in UI."""
    if rec.get("is_cancelled"):
        return False
    cat = str(rec.get("category_code", "")).strip()
    if cat == "0":
        return False
    return True


def record_legacy_stable_key(rec: dict) -> str:
    """Chiave univoca del record nel DB unificato (come in import legacy)."""
    k = rec.get("legacy_registration_key")
    if isinstance(k, str) and k.strip():
        return k
    return f"{rec.get('year', '')}:{rec.get('source_folder', '')}:{rec.get('source_file', '')}:{rec.get('source_index', '')}"


def find_record_year_and_ref(db: dict, stable_key: str) -> tuple[dict, dict] | None:
    """Ritorna (year_dict, record) se la chiave è nel DB."""
    for yd in db.get("years", []):
        for r in yd.get("records", []):
            if record_legacy_stable_key(r) == stable_key:
                return (yd, r)
    return None


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


def save_encrypted_db_dual(
    db: dict,
    primary_output_path: Path,
    key_path: Path,
    *,
    backup_output_path: Path = DEFAULT_BACKUP_ENCRYPTED_DB,
) -> None:
    """Salva il DB cifrato su percorso principale + backup.

    - `primary_output_path`: percorso scelto in UI (file principale operativo).
    - `backup_output_path`: copia di sicurezza (default locale app).
    """
    targets: list[Path] = [primary_output_path]
    if backup_output_path != primary_output_path:
        targets.append(backup_output_path)

    errors: list[str] = []
    for t in targets:
        try:
            save_encrypted_db(db, t, key_path)
        except Exception as exc:
            errors.append(f"{t}: {exc}")

    if errors:
        raise RuntimeError(
            "Salvataggio cifrato non completato su tutti i target:\n" + "\n".join(errors)
        )


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
    data_file_var = tk.StringVar(value=str(DEFAULT_ENCRYPTED_DB.resolve()))
    key_file_var = tk.StringVar(value=str(DEFAULT_KEY_FILE))
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

    def _latest_year_frequency_maps() -> tuple[dict[str, int], dict[str, int]]:
        """Frequenze nomi categoria/conto solo sulle registrazioni dell'ultimo anno del DB."""
        d = cur_db()
        years = d.get("years", [])
        if not years:
            return {}, {}
        latest_year = max(int(y.get("year", 0)) for y in years)
        y_latest = next((y for y in years if int(y.get("year", 0)) == latest_year), None)
        if y_latest is None:
            return {}, {}
        year_accounts = y_latest.get("accounts", [])
        year_categories = y_latest.get("categories", [])
        cat_freq: dict[str, int] = {}
        acc_freq: dict[str, int] = {}
        for r in y_latest.get("records", []):
            if not show_record_in_movements_grid(r):
                continue
            c = category_name_for_record(r, year_categories).strip()
            if c:
                cat_freq[c] = cat_freq.get(c, 0) + 1
            a1 = account_name_for_record(r, year_accounts, "primary").strip()
            a2 = account_name_for_record(r, year_accounts, "secondary").strip()
            if a1:
                acc_freq[a1] = acc_freq.get(a1, 0) + 1
            if a2:
                acc_freq[a2] = acc_freq.get(a2, 0) + 1
        return cat_freq, acc_freq

    def _order_by_latest_year_frequency(
        values: set[str],
        freq_map: dict[str, int],
        *,
        pinned_order: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        present = [v for v in values if str(v).strip()]
        pinned: list[str] = []
        used: set[str] = set()
        for p in pinned_order:
            m = next((v for v in present if v.lower() == p.lower()), None)
            if m is not None:
                pinned.append(m)
                used.add(m)
        rest = [v for v in present if v not in used]
        # Prima i presenti nell'ultimo anno (freq>0, in ordine decrescente), poi eventuali extra in ordine alfabetico.
        head = sorted((v for v in rest if freq_map.get(v, 0) > 0), key=lambda s: (-freq_map.get(s, 0), s.lower()))
        tail = sorted((v for v in rest if freq_map.get(v, 0) <= 0), key=lambda s: s.lower())
        return tuple(pinned + head + tail)

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

        cat_freq, acc_freq = _latest_year_frequency_maps()
        cat_vals = (_ALL_CATEGORIES_LABEL,) + _order_by_latest_year_frequency(
            cats, cat_freq, pinned_order=("Consumi ordinari", "Girata conto/conto")
        )
        acc_vals = (_ALL_ACCOUNTS_LABEL,) + _order_by_latest_year_frequency(
            accs, acc_freq, pinned_order=("Cassa",)
        )
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

    # Correzione: solo righe presenti in griglia = già filtrate da «Cerca»; nessuna ricerca fuori dai filtri.
    # Stessa riga del tasto Modifica (col. 0) così l’altezza della barra non cambia al primo clic.
    _CORREZIONE_BLUE = "#1565c0"
    correzione_row = tk.Frame(records_frame, bg="#ffffff")
    btn_stampa_ricerca = tk.Label(
        correzione_row,
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
    btn_modifica_reg = tk.Label(
        correzione_row,
        text="Modifica registrazione",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=12,
        pady=4,
        bg=_CORREZIONE_BLUE,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    lbl_correzione_msg = tk.Label(
        correzione_row,
        text="",
        font=("TkDefaultFont", 11, "bold"),
        fg="#b71c1c",
        bg="#ffffff",
    )
    btn_forza_verifica = tk.Label(
        correzione_row,
        text="Forzare la cancellazione della verifica",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=4,
        bg="#ef6c00",
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_elimina_reg = tk.Label(
        correzione_row,
        text="Elimina registrazione",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=10,
        pady=4,
        bg="#b71c1c",
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )

    correzione_forza_revealed: list[bool] = [False]
    _correzione_bar_prev_sel_key: list[str | None] = [None]

    def refresh_correction_bar() -> None:
        """Aggiorna la barra in base alla riga selezionata. Il tasto Modifica non viene tolto
        se si passa da una registrazione modificabile a un'altra: resta visibile e l'azione usa
        sempre la selezione corrente (vedi on_modifica_reg_click)."""
        sel = mov_tree.selection()
        key = sel[0] if sel else None
        if key != _correzione_bar_prev_sel_key[0]:
            correzione_forza_revealed[0] = False
        _correzione_bar_prev_sel_key[0] = key

        want_forza = False
        want_elimina = False
        want_msg = False
        want_modifica = False
        has_verifica_flags = False
        forza_ok_recency = False
        msg_text = "Registrazione non modificabile, più vecchia di 5 anni."

        if sel:
            sk = sel[0]
            pair = find_record_year_and_ref(cur_db(), sk)
            if pair:
                _yd, rec = pair
                if record_has_account_verification_flags(rec):
                    has_verifica_flags = True
                forza_ok_recency = record_is_within_forza_verifica_recency(rec)
                if not record_is_within_edit_age(rec):
                    want_msg = True
                else:
                    want_modifica = True

        want_forza = (
            has_verifica_flags
            and want_modifica
            and forza_ok_recency
            and correzione_forza_revealed[0]
        )
        want_elimina = want_modifica and (not want_forza)

        col = 1
        if want_msg:
            lbl_correzione_msg.configure(text=msg_text)
            lbl_correzione_msg.grid(row=0, column=col, sticky="w", padx=(0, 12))
            col += 1
        else:
            lbl_correzione_msg.grid_remove()

        if want_modifica:
            btn_modifica_reg.grid(row=0, column=col, sticky="w", padx=(0, 12))
            col += 1
        else:
            btn_modifica_reg.grid_remove()

        if want_forza:
            btn_forza_verifica.grid(row=0, column=col, sticky="w", padx=(0, 12))
            col += 1
        else:
            btn_forza_verifica.grid_remove()
        if want_elimina:
            btn_elimina_reg.grid(row=0, column=col, sticky="w", padx=(0, 12))
        else:
            btn_elimina_reg.grid_remove()

    def persist_db_after_edit(reselect_key: str | None) -> None:
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
                backup_output_path=DEFAULT_BACKUP_ENCRYPTED_DB,
            )
        except Exception as exc:
            messagebox.showerror("Salvataggio", str(exc))
            return
        populate_movements_trees(reselect_stable_key=reselect_key)
        refresh_balance_footer()

    def open_edit_date(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec):
            return
        year_n = int(rec.get("year", 0))
        top = tk.Toplevel(root)
        top.title("Modifica data")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Data (gg/mm/aaaa):").grid(row=0, column=0, sticky="w")
        v = tk.StringVar(value=to_italian_date(str(rec.get("date_iso", ""))))
        ttk.Entry(frm, textvariable=v, width=14).grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            iso = parse_italian_ddmmyyyy_to_iso(v.get())
            if not iso:
                messagebox.showerror("Data", "Formato non valido (gg/mm/aaaa).", parent=top)
                return
            try:
                dnew = date.fromisoformat(iso)
            except Exception:
                messagebox.showerror("Data", "Data non valida.", parent=top)
                return
            if dnew.year != year_n:
                messagebox.showerror(
                    "Data",
                    f"La data deve restare nell'anno contabile del record ({year_n}).",
                    parent=top,
                )
                return
            cutoff = date_minus_calendar_years(date.today(), 5)
            if dnew < cutoff:
                messagebox.showerror(
                    "Data",
                    "La data risulta oltre il limite dei 5 anni consentiti per la modifica.",
                    parent=top,
                )
                return
            # Ricerca per data: la nuova data non deve uscire dall'intervallo applicato (stessi limiti della griglia).
            if filter_order_applied_var.get() == "date":
                fmin = _parse_iso_to_date(date_from_applied_var.get())
                fmax = _parse_iso_to_date(date_to_applied_var.get())
                if fmin and fmax:
                    if fmin > fmax:
                        fmin, fmax = fmax, fmin
                    if filter_future_applied_var.get() == "exclude":
                        today = date.today()
                        if fmax > today:
                            fmax = today
                        if fmin > today:
                            fmin = today
                    if dnew < fmin or dnew > fmax:
                        messagebox.showerror(
                            "Data",
                            "La nuova data deve restare nell'intervallo della ricerca attuale "
                            f"({to_italian_date(fmin.isoformat())} – {to_italian_date(fmax.isoformat())}).",
                            parent=top,
                        )
                        return
            rec["date_iso"] = iso
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_category(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec):
            return
        year_categories = year_categories_map(cur_db()).get(rec.get("year"), [])
        choices: list[tuple[str, str]] = []
        for i, c in enumerate(year_categories):
            if str(i) == "0":
                continue
            disp = category_display_name(c.get("name", ""))
            choices.append((disp, str(i)))
        cat_freq, _acc_freq = _latest_year_frequency_maps()
        choices.sort(
            key=lambda it: (
                0 if it[0].lower() == "consumi ordinari" else (1 if it[0].lower() == "girata conto/conto" else 2),
                -cat_freq.get(it[0], 0),
                it[0].lower(),
            )
        )
        if not choices:
            messagebox.showerror("Categoria", "Nessuna categoria disponibile per questo anno.")
            return
        top = tk.Toplevel(root)
        top.title("Modifica categoria")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Categoria:").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(frm, state="readonly", width=32, values=[c[0] for c in choices])
        cc = str(rec.get("category_code", ""))
        cur_disp = next((d for d, code in choices if code == cc), choices[0][0])
        cb.set(cur_disp)
        cb.grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            picked = cb.get()
            code = next((code for d, code in choices if d == picked), None)
            if code is None:
                messagebox.showerror("Categoria", "Selezione non valida.", parent=top)
                return
            sync_record_category_from_plan(rec, year_categories, code)
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_account_primary(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec) or record_has_account_verification_flags(rec):
            return
        accounts = year_accounts_map(cur_db()).get(rec.get("year"), [])
        _cat_freq, acc_freq = _latest_year_frequency_maps()
        names = [a.get("name", "") for a in accounts]
        names.sort(key=lambda n: (0 if n.lower() == "cassa" else 1, -acc_freq.get(n, 0), n.lower()))
        if not names:
            messagebox.showerror("Conto", "Nessun conto per questo anno.")
            return
        top = tk.Toplevel(root)
        top.title("Modifica conto (dal conto)")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Conto:").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(frm, state="readonly", width=28, values=names)
        code = str(rec.get("account_primary_code", "")).strip()
        idx = int(code) - 1 if code.isdigit() and int(code) >= 1 else 0
        if 0 <= idx < len(names):
            cb.set(names[idx])
        else:
            cb.set(names[0])
        cb.grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            picked = cb.get()
            if picked not in names:
                messagebox.showerror("Conto", "Selezione non valida.", parent=top)
                return
            sync_record_primary_account(rec, accounts, names.index(picked))
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_account_secondary(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec) or record_has_account_verification_flags(rec):
            return
        if not is_giroconto_record(rec):
            messagebox.showinfo("Conto", "Il secondo conto si modifica solo per categorie «Girata conto/conto».")
            return
        accounts = year_accounts_map(cur_db()).get(rec.get("year"), [])
        _cat_freq, acc_freq = _latest_year_frequency_maps()
        names = [a.get("name", "") for a in accounts]
        names.sort(key=lambda n: (0 if n.lower() == "cassa" else 1, -acc_freq.get(n, 0), n.lower()))
        if not names:
            messagebox.showerror("Conto", "Nessun conto per questo anno.")
            return
        top = tk.Toplevel(root)
        top.title("Modifica conto (al conto)")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Conto:").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(frm, state="readonly", width=28, values=names)
        code = str(rec.get("account_secondary_code", "")).strip()
        idx = int(code) - 1 if code.isdigit() and int(code) >= 1 else 0
        if 0 <= idx < len(names):
            cb.set(names[idx])
        else:
            cb.set(names[0])
        cb.grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            picked = cb.get()
            if picked not in names:
                messagebox.showerror("Conto", "Selezione non valida.", parent=top)
                return
            sync_record_secondary_account(rec, accounts, names.index(picked))
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_cheque(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec):
            return
        top = tk.Toplevel(root)
        top.title("Modifica assegno")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Assegno:").grid(row=0, column=0, sticky="w")
        v = tk.StringVar(value=str(rec.get("cheque") or ""))
        ttk.Entry(frm, textvariable=v, width=16).grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            rec["cheque"] = sanitize_single_line_text(v.get() or "", max_len=MAX_CHEQUE_LEN)
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_amount(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec) or record_has_account_verification_flags(rec):
            return
        year = int(rec.get("year", 0))
        top = tk.Toplevel(root)
        top.title("Modifica importo")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        use_lire = year <= 2001 and rec.get("amount_lire_original") is not None
        if use_lire:
            ttk.Label(frm, text="Importo (lire, intero):").grid(row=0, column=0, sticky="w")
            cur = int(to_decimal(rec["amount_lire_original"]).quantize(Decimal("1")))
            v = tk.StringVar(value=str(cur))
        else:
            ttk.Label(frm, text="Importo (€, usa . o , come decimale):").grid(row=0, column=0, sticky="w")
            v = tk.StringVar(value=format_euro_it(to_decimal(rec["amount_eur"])))
        ttk.Entry(frm, textvariable=v, width=18).grid(row=0, column=1, sticky="w", padx=(8, 0))

        def on_ok() -> None:
            try:
                if use_lire:
                    amt = parse_lire_amount_input(v.get())
                else:
                    amt = normalize_euro_input(v.get())
            except Exception as exc:
                messagebox.showerror("Importo", str(exc), parent=top)
                return
            apply_amount_to_record(rec, amt)
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def open_edit_note(stable_key: str) -> None:
        pair = find_record_year_and_ref(cur_db(), stable_key)
        if not pair:
            return
        _yd, rec = pair
        if not record_is_within_edit_age(rec):
            return
        top = tk.Toplevel(root)
        top.title("Modifica nota")
        top.transient(root)
        frm = ttk.Frame(top, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Nota:").grid(row=0, column=0, sticky="nw")
        tx = tk.Text(frm, width=52, height=5, font=("TkDefaultFont", 11))
        tx.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tx.insert("1.0", str(rec.get("note") or ""))

        def on_ok() -> None:
            rec["note"] = sanitize_single_line_text(tx.get("1.0", "end-1c") or "", max_len=MAX_RECORD_NOTE_LEN)
            top.destroy()
            persist_db_after_edit(stable_key)

        bf = ttk.Frame(frm)
        bf.grid(row=1, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Annulla", command=top.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bf, text="Salva", command=on_ok).pack(side=tk.LEFT)

    def _correzione_current_key_and_rec() -> tuple[str, dict] | None:
        sel = mov_tree.selection()
        if not sel:
            return None
        pair = find_record_year_and_ref(cur_db(), sel[0])
        if not pair:
            return None
        _yd, rec = pair
        if not record_is_within_edit_age(rec):
            return None
        return (sel[0], rec)

    def on_modifica_reg_click(event: tk.Event) -> None:
        cur = _correzione_current_key_and_rec()
        if not cur:
            return
        correzione_forza_revealed[0] = True
        refresh_correction_bar()
        _key0, rec0 = cur
        has_star = record_has_account_verification_flags(rec0)
        giro = is_giroconto_record(rec0)
        m = tk.Menu(correzione_row, tearoff=0)

        def run_edit(fn: Callable[[str], None]) -> None:
            cur2 = _correzione_current_key_and_rec()
            if cur2:
                fn(cur2[0])

        m.add_command(label="Data", command=lambda: run_edit(open_edit_date))
        m.add_command(label="Categoria", command=lambda: run_edit(open_edit_category))
        if not has_star:
            m.add_command(label="Dal conto", command=lambda: run_edit(open_edit_account_primary))
            if giro:
                m.add_command(label="al conto", command=lambda: run_edit(open_edit_account_secondary))
            m.add_command(label="Importo", command=lambda: run_edit(open_edit_amount))
        m.add_command(label="Assegno", command=lambda: run_edit(open_edit_cheque))
        m.add_command(label="Nota", command=lambda: run_edit(open_edit_note))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                m.grab_release()
            except Exception:
                pass

    def _flags_star_count(flags: str) -> int:
        return str(flags or "").count("*")

    def _flags_set_star_count(flags: str, stars: int) -> str:
        base = str(flags or "").replace("*", "")
        n = max(0, int(stars))
        return f"{base}{'*' * n}" if (base or n) else ""

    def _set_account_flags(rec: dict, which: str, stars: int) -> None:
        fk = "account_primary_flags" if which == "primary" else "account_secondary_flags"
        ck = "account_primary_code" if which == "primary" else "account_secondary_code"
        wk = "account_primary_with_flags" if which == "primary" else "account_secondary_with_flags"
        rec[fk] = _flags_set_star_count(str(rec.get(fk) or ""), stars)
        code = str(rec.get(ck) or "").strip()
        fl = str(rec.get(fk) or "")
        rec[wk] = f"{code}{fl}" if code else ""

    def _build_reg_index_maps() -> tuple[list[dict], dict[str, int]]:
        all_records = [r for y in cur_db().get("years", []) for r in y.get("records", [])]
        all_records.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        reg_map = unified_registration_sequence_map(all_records)
        return all_records, reg_map

    def on_forza_verifica_click(_event: tk.Event | None = None) -> None:
        cur = _correzione_current_key_and_rec()
        if not cur:
            return
        stable_key, rec = cur
        if not record_has_account_verification_flags(rec):
            return
        if not record_is_within_forza_verifica_recency(rec):
            return

        d = cur_db()
        acc_by_year = year_accounts_map(d)
        reg_all, reg_map = _build_reg_index_maps()
        selected_reg_n = reg_map.get(stable_key)
        if selected_reg_n is None:
            return

        y_accounts = acc_by_year.get(rec.get("year"), [])
        acc_a = account_name_for_record(rec, y_accounts, "primary")
        acc_b = account_name_for_record(rec, y_accounts, "secondary")
        st_a = _flags_star_count(str(rec.get("account_primary_flags") or ""))
        st_b = _flags_star_count(str(rec.get("account_secondary_flags") or ""))

        side: str | None = None
        target_account_name = ""
        if st_a > 0 and st_b > 0 and is_giroconto_record(rec) and acc_a and acc_b:
            choice = messagebox.askyesnocancel(
                "Forza cancellazione verifica",
                f"La registrazione ha verifica su entrambi i conti.\n"
                f"Scegli il conto da cui togliere la verifica:\n"
                f"Sì = {acc_a}\nNo = {acc_b}",
            )
            if choice is None:
                return
            side = "primary" if choice else "secondary"
            target_account_name = acc_a if choice else acc_b
        elif st_a > 0:
            side = "primary"
            target_account_name = acc_a
        elif st_b > 0:
            side = "secondary"
            target_account_name = acc_b
        else:
            return

        if not target_account_name:
            messagebox.showerror("Forza cancellazione verifica", "Conto non identificabile per la registrazione selezionata.")
            return

        selected_stars = st_a if side == "primary" else st_b
        found_higher_double = False

        # 1) Pulizia secondi asterischi sulle registrazioni successive con lo stesso conto.
        for rr in reg_all:
            k = record_legacy_stable_key(rr)
            nreg = reg_map.get(k, 0)
            if nreg <= selected_reg_n:
                continue
            y_acc = acc_by_year.get(rr.get("year"), [])
            r_a = account_name_for_record(rr, y_acc, "primary")
            r_b = account_name_for_record(rr, y_acc, "secondary")
            touched = False
            if r_a == target_account_name:
                sc = _flags_star_count(str(rr.get("account_primary_flags") or ""))
                if sc >= 2:
                    _set_account_flags(rr, "primary", 1)
                    found_higher_double = True
                    touched = True
            if r_b == target_account_name:
                sc = _flags_star_count(str(rr.get("account_secondary_flags") or ""))
                if sc >= 2:
                    _set_account_flags(rr, "secondary", 1)
                    found_higher_double = True
                    touched = True
            if touched:
                continue

        # 2) Se richiesto, promuovi la registrazione precedente dello stesso conto al doppio asterisco.
        must_promote_previous = (selected_stars >= 2) or found_higher_double
        if must_promote_previous:
            prev_rec: dict | None = None
            prev_side: str | None = None
            prev_reg = -1
            for rr in reg_all:
                k = record_legacy_stable_key(rr)
                nreg = reg_map.get(k, 0)
                if nreg >= selected_reg_n or nreg <= prev_reg:
                    continue
                y_acc = acc_by_year.get(rr.get("year"), [])
                r_a = account_name_for_record(rr, y_acc, "primary")
                r_b = account_name_for_record(rr, y_acc, "secondary")
                if r_a == target_account_name:
                    prev_rec, prev_side, prev_reg = rr, "primary", nreg
                elif r_b == target_account_name:
                    prev_rec, prev_side, prev_reg = rr, "secondary", nreg
            if prev_rec is not None and prev_side is not None:
                fk = "account_primary_flags" if prev_side == "primary" else "account_secondary_flags"
                cur_st = _flags_star_count(str(prev_rec.get(fk) or ""))
                if cur_st < 2:
                    _set_account_flags(prev_rec, prev_side, 2)

        # 3) Rimuovi la verifica dalla registrazione corrente (tutti gli asterischi lato conto scelto).
        _set_account_flags(rec, side, 0)

        # Persistenza + refresh UI
        persist_db_after_edit(stable_key)

        amount_text, _amount_tag = format_amount_for_output(rec)
        info_text = (
            f"E' stata tolta la spunta di verifica alla registrazione {selected_reg_n} "
            f"(conto: {target_account_name}, importo: {amount_text}).\n\n"
            "Vuoi stampare un promemoria?"
        )
        want_print = messagebox.askyesno("Verifica rimossa", info_text)
        if not want_print:
            return

        try:
            date_it = to_italian_date(date.today().isoformat())
            mov_vals = (
                to_italian_date(str(rec.get("date_iso", ""))),
                category_name_for_record(rec, year_categories_map(d).get(rec.get("year"), [])),
                account_name_for_record(rec, acc_by_year.get(rec.get("year"), []), "primary"),
                str(rec.get("account_primary_flags") or ""),
                account_name_for_record(rec, acc_by_year.get(rec.get("year"), []), "secondary"),
                str(rec.get("account_secondary_flags") or ""),
                str(rec.get("cheque") or ""),
            )
            _d, _cat, a1, f1, a2, f2, chq = mov_vals
            note_e = html_module.escape(str(rec.get("note") or "")).replace("\n", "<br/>")
            html_doc = f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"/><title>Promemoria verifica</title>
<style>
body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:#1a1a1a; padding:8mm; }}
p {{ margin:0 0 3mm 0; }}
table {{ width:100%; border-collapse:collapse; font-size:10pt; }}
th, td {{ border:1px solid #999; padding:4px 6px; vertical-align:top; }}
th {{ background:#efefef; text-align:left; }}
</style></head><body>
<p>Data: {html_module.escape(date_it)}</p>
<p><b>E' stata tolta la spunta di verifica alla registrazione {selected_reg_n}</b></p>
<table>
<tr><th>Data</th><td>{html_module.escape(to_italian_date(str(rec.get("date_iso", ""))))}</td></tr>
<tr><th>Categoria</th><td>{html_module.escape(category_name_for_record(rec, year_categories_map(d).get(rec.get("year"), [])))}</td></tr>
<tr><th>Dal conto</th><td>{html_module.escape(str(a1))} {html_module.escape(str(f1))}</td></tr>
<tr><th>Al conto</th><td>{html_module.escape(str(a2))} {html_module.escape(str(f2))}</td></tr>
<tr><th>Assegno</th><td>{html_module.escape(str(chq))}</td></tr>
<tr><th>Importo</th><td>{html_module.escape(amount_text)}</td></tr>
<tr><th>Conto verifica rimossa</th><td>{html_module.escape(target_account_name)}</td></tr>
<tr><th>Nota</th><td>{note_e}</td></tr>
</table>
</body></html>"""
            _print_ricerca_via_browser(html_doc)
        except Exception as exc:
            messagebox.showerror("Stampa promemoria", str(exc))

    def on_elimina_reg_click(_event: tk.Event | None = None) -> None:
        cur = _correzione_current_key_and_rec()
        if not cur:
            return
        stable_key, rec = cur
        _reg_all, reg_map = _build_reg_index_maps()
        reg_n = reg_map.get(stable_key)
        if rec.get("is_cancelled"):
            return
        ask = messagebox.askyesno(
            "Elimina registrazione",
            "Confermi l'annullamento della registrazione selezionata?\n"
            "La registrazione verra' rimossa dalla griglia Movimenti e i saldi saranno ricalcolati.",
        )
        if not ask:
            return
        rec["is_cancelled"] = True
        persist_db_after_edit(None)
        if reg_n is not None:
            messagebox.showinfo("Registrazione eliminata", f"Registrazione {reg_n} annullata.")

    btn_modifica_reg.bind("<Button-1>", on_modifica_reg_click)
    btn_forza_verifica.bind("<Button-1>", on_forza_verifica_click)
    btn_elimina_reg.bind("<Button-1>", on_elimina_reg_click)

    def _on_selection_refresh_correction(_event: tk.Event | None = None) -> None:
        refresh_correction_bar()

    for _t in (mov_tree, amt_tree, note_tree):
        _t.bind("<<TreeviewSelect>>", _on_selection_refresh_correction, add="+")

    # Colonne griglia: mov | sep | amt | sep | note | scrollbar
    records_frame.grid_columnconfigure(0, weight=1, minsize=120)
    records_frame.grid_columnconfigure(1, weight=0, minsize=_SEP_CH_W)
    records_frame.grid_columnconfigure(2, weight=0, minsize=104)
    records_frame.grid_columnconfigure(3, weight=0, minsize=_SEP_CH_W)
    records_frame.grid_columnconfigure(4, weight=1, minsize=100)
    records_frame.grid_columnconfigure(5, weight=0, minsize=20)
    records_frame.grid_rowconfigure(0, weight=0)
    records_frame.grid_rowconfigure(1, weight=0)
    records_frame.grid_rowconfigure(2, weight=0)
    records_frame.grid_rowconfigure(3, weight=1)
    search_title_row.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 6))
    correzione_row.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(0, 4))
    btn_stampa_ricerca.grid(row=0, column=0, sticky="w", padx=(0, 10))
    header_row.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(0, 2))
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
    mov_tree.grid(row=3, column=0, sticky="nsew")
    sep_1.grid(row=3, column=1, sticky="nsw")
    amt_tree.grid(row=3, column=2, sticky="nsew")
    sep_2.grid(row=3, column=3, sticky="nsw")
    note_tree.grid(row=3, column=4, sticky="nsew")
    yscroll.grid(row=3, column=5, sticky="ns", padx=(2, 0))

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
            if is_dotazione_record(r):
                continue
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
            rid = record_legacy_stable_key(r)
            reg_text = str(reg_seq_map[rid])
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

    def populate_movements_trees(reselect_stable_key: str | None = None) -> None:
        nonlocal movements_population_seq
        movements_population_seq += 1
        token_local = movements_population_seq
        reselect_key = reselect_stable_key
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

                def _reselect_and_bar() -> None:
                    if token_local != movements_population_seq:
                        return
                    if reselect_key:
                        try:
                            if mov_tree.exists(reselect_key):
                                mov_tree.selection_set(reselect_key)
                                mov_tree.see(reselect_key)
                        except Exception:
                            pass
                    try:
                        refresh_correction_bar()
                    except Exception:
                        pass

                root.after_idle(_reselect_and_bar)

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
        _cat_freq, acc_freq = _latest_year_frequency_maps()
        acc_vals = (_ALL_ACCOUNTS_LABEL,) + _order_by_latest_year_frequency(
            accs, acc_freq, pinned_order=("Cassa",)
        )
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
        table_pt = (5.8 if n_acc <= 10 else 5.2) * 1.4
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
<title></title>
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
        tbl_pt = (5.4 if for_native else 6.2) * 1.25
        desc_pt = 7.8
        date_it = to_italian_date(date.today().isoformat())
        desc_esc = html_module.escape(search_desc or "(nessuna descrizione)")
        native_root_style = ""
        if native_text_width_pt is not None:
            _iw = float(native_text_width_pt)
            native_root_style = (
                f' style="width:{_iw:.2f}pt;max-width:{_iw:.2f}pt;margin:0;padding:0;box-sizing:border-box;"'
            )
        # Stampa registrazioni: asterischi +25% rispetto all'assetto corrente; assegno invariato; poi normalizzazione.
        _w_base = [6.0, 10.56, 21.0, 14.0, 1.815, 14.0, 1.815, 6.6352, 24.0]
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
<title></title>
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
        run_id = f"ui_ricerca_{int(time.time() * 1000)}"
        # #region agent log
        _debug_log(run_id, "H2", "main_app.py:_print_ricerca_direct", "enter_print_ricerca_direct", {})
        # #endregion
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
        fpdf_ok = _print_ricerca_fpdf(rows, desc)
        # #region agent log
        _debug_log(run_id, "H2", "main_app.py:_print_ricerca_direct", "ricerca_fpdf_result", {"fpdf_ok": fpdf_ok, "rows": n})
        # #endregion
        if fpdf_ok:
            return
        sysname = platform.system()
        if sysname == "Darwin":

            def _mk_r(iw: float) -> str:
                return _build_ricerca_print_html(
                    rows, desc, for_native=True, native_text_width_pt=iw
                )

            if _print_balances_native_macos(_mk_r):
                # #region agent log
                _debug_log(run_id, "H3", "main_app.py:_print_ricerca_direct", "fallback_native_macos_used", {})
                # #endregion
                return
        elif sysname == "Windows":
            html_native = _build_ricerca_print_html(rows, desc, for_native=True)
            if _print_balances_native_windows(html_native):
                return
            if _print_balances_windows_pywebview(html_native):
                return
        _print_ricerca_via_browser(_build_ricerca_print_html(rows, desc, for_native=False))
        # #region agent log
        _debug_log(run_id, "H3", "main_app.py:_print_ricerca_direct", "fallback_browser_used", {})
        # #endregion

    btn_stampa_ricerca.bind("<Button-1>", lambda _e: _print_ricerca_direct())
    btn_stampa_ricerca.bind("<Enter>", lambda _e: btn_stampa_ricerca.configure(bg=_PRINT_RICERCA_RED_ACTIVE))
    btn_stampa_ricerca.bind("<Leave>", lambda _e: btn_stampa_ricerca.configure(bg=_PRINT_RICERCA_RED))

    def _print_saldi_direct() -> None:
        run_id = f"ui_saldi_{int(time.time() * 1000)}"
        # #region agent log
        _debug_log(run_id, "H2", "main_app.py:_print_saldi_direct", "enter_print_saldi_direct", {})
        # #endregion
        snap = _saldi_snapshot_for_print()
        fpdf_ok = _print_balances_fpdf(snap)
        # #region agent log
        _debug_log(run_id, "H2", "main_app.py:_print_saldi_direct", "saldi_fpdf_result", {"fpdf_ok": fpdf_ok})
        # #endregion
        if fpdf_ok:
            return
        sysname = platform.system()
        if sysname == "Darwin":

            def _mac_html(iw: float) -> str:
                return _build_saldi_print_html(snap, for_native=True, native_text_width_pt=iw)

            if _print_balances_native_macos(_mac_html):
                # #region agent log
                _debug_log(run_id, "H3", "main_app.py:_print_saldi_direct", "fallback_native_macos_used", {})
                # #endregion
                return
        elif sysname == "Windows":
            html_native = _build_saldi_print_html(snap, for_native=True)
            if _print_balances_native_windows(html_native):
                return
            if _print_balances_windows_pywebview(html_native):
                return
        _print_saldi_via_browser(_build_saldi_print_html(snap, for_native=False))
        # #region agent log
        _debug_log(run_id, "H3", "main_app.py:_print_saldi_direct", "fallback_browser_used", {})
        # #endregion

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

    # Pagina Nuovi dati
    pack_centered_page_title(nuovi_dati_frame)
    nuovi_top = ttk.Frame(nuovi_dati_frame)
    nuovi_top.pack(fill=tk.X, pady=(0, 10))
    _NUOVI_BLUE = "#1565c0"
    _NUOVI_GRAY = "#666666"
    btn_nuova_reg = tk.Label(
        nuovi_top, text="Nuova registrazione", cursor="hand2", highlightthickness=0,
        font=filter_ui_font, padx=10, pady=5, bg=_NUOVI_BLUE, fg="#ffffff", relief=tk.RAISED, bd=1
    )
    btn_reg_periodiche = tk.Label(
        nuovi_top, text="Registrazioni periodiche", cursor="hand2", highlightthickness=0,
        font=filter_ui_font, padx=10, pady=5, bg=_NUOVI_GRAY, fg="#ffffff", relief=tk.RAISED, bd=1
    )
    btn_nuova_reg.pack(side=tk.LEFT, padx=(0, 8))
    btn_reg_periodiche.pack(side=tk.LEFT)

    nuovi_status_var = tk.StringVar(value="")
    ttk.Label(nuovi_dati_frame, textvariable=nuovi_status_var).pack(anchor=tk.W, pady=(0, 8))

    nuova_form = ttk.Frame(nuovi_dati_frame, padding=8)
    nuova_form.pack(fill=tk.X)
    periodiche_placeholder = ttk.Label(nuovi_dati_frame, text="Registrazioni periodiche: in preparazione")
    periodiche_placeholder.pack_forget()

    newreg_no_var = tk.StringVar(value="-")
    newreg_date_var = tk.StringVar(value=to_italian_date(date.today().isoformat()))
    newreg_cat_var = tk.StringVar(value="")
    newreg_cat_note_var = tk.StringVar(value="-")
    newreg_acc1_var = tk.StringVar(value="")
    newreg_acc2_var = tk.StringVar(value="")
    newreg_amount_var = tk.StringVar(value="")
    newreg_sign_var = tk.StringVar(value="+")
    newreg_cheque_var = tk.StringVar(value="")
    newreg_note_var = tk.StringVar(value="")
    newreg_cat_code_var = tk.StringVar(value="")
    newreg_calendar_popup: list[tk.Toplevel | None] = [None]
    _NEWREG_DATE_MASK = "__/__/____"
    _NEWREG_DATE_POS = (0, 1, 3, 4, 6, 7, 8, 9)

    last_date_iso = date.today().isoformat()
    last_cat_code = ""
    last_acc1_code = ""
    last_acc2_code = ""

    def _all_records_sorted() -> list[dict]:
        rs = [r for y in cur_db().get("years", []) for r in y.get("records", [])]
        rs.sort(key=lambda r: (r["year"], r["source_folder"], r["source_file"], r["source_index"]))
        return rs

    def _next_registration_number() -> int:
        rs = _all_records_sorted()
        if not rs:
            return 1
        return len(unified_registration_sequence_map(rs)) + 1

    def _ensure_year_bucket(target_year: int) -> dict:
        d = cur_db()
        for y in d.get("years", []):
            if int(y.get("year", 0)) == int(target_year):
                return y
        latest = max(d["years"], key=lambda yy: int(yy["year"]))
        new_y = {
            "year": int(target_year),
            "accounts": json.loads(json.dumps(latest.get("accounts", []))),
            "categories": json.loads(json.dumps(latest.get("categories", []))),
            "records": [],
        }
        d["years"].append(new_y)
        d["years"].sort(key=lambda yy: int(yy["year"]))
        return new_y

    def _cat_and_acc_options() -> tuple[
        list[tuple[str, str]],
        list[tuple[str, str]],
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        d = cur_db()
        latest_year = max(d["years"], key=lambda yy: int(yy["year"]))
        rs = latest_year.get("records", [])
        cats = latest_year.get("categories", [])
        accs = latest_year.get("accounts", [])
        cat_freq: dict[str, int] = {}
        acc_freq: dict[str, int] = {}
        cat_note_by_code: dict[str, str] = {}
        cat_sign_by_code: dict[str, str] = {}
        cat_raw_name_by_code: dict[str, str] = {}
        for i, c in enumerate(cats):
            code = str(c.get("code", i))
            if code == "0":
                continue
            raw_name = str(c.get("name", "")).strip()
            cat_raw_name_by_code[code] = raw_name
            sign = raw_name[:1] if raw_name[:1] in {"+", "-", "="} else ""
            cat_sign_by_code[code] = sign
            n0 = str(c.get("note", "") or c.get("category_note", "")).strip()
            if n0:
                cat_note_by_code[code] = n0
        for r in rs:
            c = str(r.get("category_code", "")).strip()
            if c:
                cat_freq[c] = cat_freq.get(c, 0) + 1
            if str(r.get("category_note", "")).strip() and c not in cat_note_by_code:
                cat_note_by_code[c] = str(r.get("category_note", "")).strip()
            for side in ("primary", "secondary"):
                k = "account_primary_code" if side == "primary" else "account_secondary_code"
                a = str(r.get(k, "")).strip()
                if a:
                    acc_freq[a] = acc_freq.get(a, 0) + 1
        cat_opts: list[tuple[str, str]] = []
        for i, c in enumerate(cats):
            code = str(c.get("code", i))
            if code == "0":
                continue
            name = category_display_name(c.get("name", ""))
            cat_opts.append((name, code))
        def _norm_cat(s: str) -> str:
            return " ".join((s or "").strip().lower().replace(".", " ").replace("/", " / ").split())

        def _cat_rank(item: tuple[str, str]) -> tuple[int, int, str]:
            n, c = item
            nn = _norm_cat(n)
            if "consumi ordinari" in nn:
                return (0, 0, n)
            if ("girata conto / conto" in nn) or ("girata conto conto" in nn):
                return (1, 0, n)
            return (2, -cat_freq.get(c, 0), n.lower())
        cat_opts.sort(key=_cat_rank)
        if not cat_opts:
            cat_opts = [(category_display_name(c.get("name", "")), str(i)) for i, c in enumerate(cats)]

        acc_opts: list[tuple[str, str]] = []
        for i, a in enumerate(accs):
            code = str(i + 1)
            name = str(a.get("name", "")).strip()
            acc_opts.append((name, code))
        def _acc_rank(item: tuple[str, str]) -> tuple[int, int, str]:
            n, c = item
            if n.strip().lower() == "cassa":
                return (0, 0, n)
            return (1, -acc_freq.get(c, 0), n.lower())
        acc_opts.sort(key=_acc_rank)
        if not acc_opts:
            acc_opts = [(str(a.get("name", "")).strip(), str(i + 1)) for i, a in enumerate(accs)]
        return cat_opts, acc_opts, cat_note_by_code, cat_sign_by_code, cat_raw_name_by_code

    newreg_ui_font = ("TkDefaultFont", 17, "bold")
    ttk.Style(root).configure("NewReg.TLabel", font=newreg_ui_font)
    ttk.Style(root).configure("NewReg.TEntry", font=newreg_ui_font)
    ttk.Style(root).configure("NewReg.TCombobox", font=newreg_ui_font)
    ttk.Style(root).configure("NewReg.TButton", font=newreg_ui_font)

    _newreg_py = 4
    _newreg_px = 12
    ttk.Label(nuova_form, textvariable=newreg_no_var, font=("TkDefaultFont", 17, "bold"), style="NewReg.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
    ttk.Label(nuova_form, text="Data (gg/mm/aaaa)", style="NewReg.TLabel").grid(row=1, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_date = ttk.Frame(nuova_form)
    ent_date = ttk.Entry(row_date, textvariable=newreg_date_var, width=24, style="NewReg.TEntry")
    ent_date.pack(side=tk.LEFT)
    btn_oggi = ttk.Button(row_date, text="Oggi", style="NewReg.TButton")
    btn_oggi.pack(side=tk.LEFT, padx=(8, 0))
    row_date.grid(row=1, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Categoria", style="NewReg.TLabel").grid(row=2, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    cb_cat = ttk.Combobox(nuova_form, textvariable=newreg_cat_var, state="readonly", width=48, style="NewReg.TCombobox")
    cb_cat.grid(row=2, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(
        nuova_form,
        textvariable=newreg_cat_note_var,
        font=("TkDefaultFont", 11, "normal"),
        foreground="#9a9a9a",
    ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 10))
    ttk.Label(nuova_form, text="Conto", style="NewReg.TLabel").grid(row=4, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    cb_acc1 = ttk.Combobox(nuova_form, textvariable=newreg_acc1_var, state="readonly", width=38, style="NewReg.TCombobox")
    cb_acc1.grid(row=4, column=1, sticky="w", pady=_newreg_py)
    lbl_acc2 = ttk.Label(nuova_form, text="Secondo conto", style="NewReg.TLabel")
    cb_acc2 = ttk.Combobox(nuova_form, textvariable=newreg_acc2_var, state="readonly", width=38, style="NewReg.TCombobox")
    lbl_acc2.grid(row=5, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    cb_acc2.grid(row=5, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Importo (€)", style="NewReg.TLabel").grid(row=6, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_amt = ttk.Frame(nuova_form)
    ent_amt = ttk.Entry(row_amt, textvariable=newreg_amount_var, width=26, style="NewReg.TEntry")
    ent_amt.pack(side=tk.LEFT)
    btn_plus = tk.Label(row_amt, text="+", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#e0f2f1", relief=tk.RAISED, bd=1)
    btn_minus = tk.Label(row_amt, text="-", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#ffebee", relief=tk.RAISED, bd=1)
    btn_plus.pack(side=tk.LEFT, padx=(6, 2))
    btn_minus.pack(side=tk.LEFT, padx=(2, 0))
    row_amt.grid(row=6, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Assegno", style="NewReg.TLabel").grid(row=7, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    ent_chq = ttk.Entry(nuova_form, textvariable=newreg_cheque_var, width=26, style="NewReg.TEntry")
    ent_chq.grid(row=7, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Nota", style="NewReg.TLabel").grid(row=8, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    ent_note = ttk.Entry(nuova_form, textvariable=newreg_note_var, width=84, style="NewReg.TEntry")
    ent_note.grid(row=8, column=1, sticky="w", pady=_newreg_py)

    row_btns = ttk.Frame(nuova_form)
    row_btns.grid(row=9, column=0, columnspan=3, sticky="w", pady=(18, 0))
    btn_confirm = ttk.Button(row_btns, text="Conferma immissione", style="NewReg.TButton")
    btn_clear = ttk.Button(row_btns, text="Cancella valori", style="NewReg.TButton")
    btn_finish = ttk.Button(row_btns, text="Concludi immissione", style="NewReg.TButton")
    btn_confirm.pack(side=tk.LEFT, padx=(0, 8))
    btn_clear.pack(side=tk.LEFT, padx=(0, 8))
    btn_finish.pack(side=tk.LEFT)

    cat_opts_cache: list[tuple[str, str]] = []
    acc_opts_cache: list[tuple[str, str]] = []
    cat_note_by_code_cache: dict[str, str] = {}
    cat_sign_by_code_cache: dict[str, str] = {}
    cat_raw_name_by_code_cache: dict[str, str] = {}

    def _is_giro_label(lbl: str) -> bool:
        return "GIRATA" in (lbl or "").upper() and "CONTO/CONTO" in (lbl or "").upper()

    def _newreg_date_mask_set_at(s: str, idx: int, ch: str) -> str:
        return s[:idx] + ch + s[idx + 1 :]

    def _newreg_date_mask_next_slot(s: str, start_pos: int) -> int | None:
        for i in _NEWREG_DATE_POS:
            if i >= start_pos and s[i] == "_":
                return i
        for i in _NEWREG_DATE_POS:
            if s[i] == "_":
                return i
        return None

    def _newreg_date_mask_prev_filled(s: str, start_pos: int) -> int | None:
        for i in reversed(_NEWREG_DATE_POS):
            if i < start_pos and s[i] != "_":
                return i
        for i in reversed(_NEWREG_DATE_POS):
            if s[i] != "_":
                return i
        return None

    def _normalize_newreg_date_display() -> None:
        raw = (newreg_date_var.get() or "").strip()
        if raw == _NEWREG_DATE_MASK:
            return
        iso = parse_italian_ddmmyyyy_to_iso(raw)
        if not iso:
            return
        newreg_date_var.set(to_italian_date(iso))

    def _newreg_date_keypress(event: tk.Event) -> str | None:
        entry = ent_date
        var = newreg_date_var
        s = var.get() or ""
        if len(s) != len(_NEWREG_DATE_MASK) or s[2] != "/" or s[5] != "/":
            if parse_italian_ddmmyyyy_to_iso(s):
                return None
            s = _NEWREG_DATE_MASK
            var.set(s)
        keysym = getattr(event, "keysym", "")
        ch = getattr(event, "char", "")
        if keysym in ("Left", "Right", "Home", "End", "Tab", "ISO_Left_Tab", "Return"):
            return None
        if keysym == "BackSpace":
            pos = entry.index(tk.INSERT)
            prev_i = _newreg_date_mask_prev_filled(s, pos)
            if prev_i is not None:
                s2 = _newreg_date_mask_set_at(s, prev_i, "_")
                var.set(s2)
                entry.icursor(prev_i)
            return "break"
        if ch.isdigit():
            pos = entry.index(tk.INSERT)
            if pos >= len(_NEWREG_DATE_MASK):
                pos = 0
            next_i = _newreg_date_mask_next_slot(s, pos)
            if next_i is None:
                return "break"
            s2 = _newreg_date_mask_set_at(s, next_i, ch)
            def _digits_at(ix1: int, ix2: int) -> str:
                return (s2[ix1] if ix1 < len(s2) else "_") + (s2[ix2] if ix2 < len(s2) else "_")
            dd = _digits_at(0, 1)
            mm = _digits_at(3, 4)
            # controllo immediato giorno/mese
            if next_i in (0, 1):
                if next_i == 0 and ch not in ("0", "1", "2", "3"):
                    return "break"
                if dd[0] != "_" and dd[1] != "_":
                    day = int(dd)
                    if day < 1 or day > 31:
                        return "break"
                if next_i == 1 and dd[0] != "_":
                    if dd[0] == "3" and ch not in ("0", "1"):
                        return "break"
                    if dd[0] == "0" and ch == "0":
                        return "break"
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
            # controllo immediato anno: il prefisso digitato deve essere compatibile col range consentito.
            if next_i in (6, 7, 8, 9):
                y_min = date_minus_calendar_years(date.today(), 1).year
                y_max = date_minus_calendar_years(date.today(), -1).year
                y_slots = [s2[i] for i in (6, 7, 8, 9)]
                y_pref = ""
                for yy in y_slots:
                    if yy == "_":
                        break
                    y_pref += yy
                if y_pref:
                    if not any(str(y).startswith(y_pref) for y in range(y_min, y_max + 1)):
                        return "break"
            # se data completa, verifica validità calendario e range subito
            if all(s2[i].isdigit() for i in _NEWREG_DATE_POS):
                try:
                    dsel = date(int(s2[6:10]), int(s2[3:5]), int(s2[0:2]))
                except Exception:
                    return "break"
                dmin = date_minus_calendar_years(date.today(), 1)
                dmax = date_minus_calendar_years(date.today(), -1)
                if dsel < dmin or dsel > dmax:
                    return "break"
            var.set(s2)
            after = next_i + 1
            if after in (2, 5):
                after += 1
            entry.icursor(after)
            return "break"
        if ch:
            return "break"
        return None

    def _sync_cat_note_and_second_account() -> None:
        code = newreg_cat_code_var.get().strip()
        if not code:
            code = next((c for n, c in cat_opts_cache if n == newreg_cat_var.get()), "")
            newreg_cat_code_var.set(code)
        newreg_cat_note_var.set(cat_note_by_code_cache.get(code, "-") or "-")
        sign = cat_sign_by_code_cache.get(code, "")
        if sign == "+":
            _apply_sign("+")
        elif sign == "-":
            _apply_sign("-")
        is_giro = _is_giro_label(newreg_cat_var.get())
        if is_giro:
            lbl_acc2.grid()
            cb_acc2.grid()
            if not newreg_acc2_var.get() and acc_opts_cache:
                names = [n for n, _c in acc_opts_cache]
                pick = names[1] if len(names) > 1 else names[0]
                if pick == newreg_acc1_var.get() and len(names) > 1:
                    pick = names[0]
                newreg_acc2_var.set(pick)
            # Controllo immediato: i due conti non possono coincidere.
            if newreg_acc1_var.get().strip() and newreg_acc1_var.get().strip() == newreg_acc2_var.get().strip():
                if acc_opts_cache:
                    for n, _c in acc_opts_cache:
                        if n != newreg_acc1_var.get().strip():
                            newreg_acc2_var.set(n)
                            break
                if newreg_acc1_var.get().strip() == newreg_acc2_var.get().strip():
                    nuovi_status_var.set("Attenzione: i due conti del giroconto devono essere diversi.")
        else:
            lbl_acc2.grid_remove()
            cb_acc2.grid_remove()
            newreg_acc2_var.set("")

    def _selected_category_code() -> str:
        try:
            idx = int(cb_cat.current())
        except Exception:
            idx = -1
        if 0 <= idx < len(cat_opts_cache):
            return cat_opts_cache[idx][1]
        return newreg_cat_code_var.get().strip()

    def _set_category_by_code(code: str) -> None:
        target_idx = next((i for i, (_n, c) in enumerate(cat_opts_cache) if c == code), -1)
        if target_idx >= 0:
            try:
                cb_cat.current(target_idx)
            except Exception:
                newreg_cat_var.set(cat_opts_cache[target_idx][0])
            newreg_cat_code_var.set(cat_opts_cache[target_idx][1])
        elif cat_opts_cache:
            try:
                cb_cat.current(0)
            except Exception:
                newreg_cat_var.set(cat_opts_cache[0][0])
            newreg_cat_code_var.set(cat_opts_cache[0][1])

    def _apply_sign(sign: str) -> None:
        newreg_sign_var.set(sign)
        raw = (newreg_amount_var.get() or "").strip().replace(" ", "")
        if not raw:
            return
        if raw.startswith(("+", "-")):
            raw = raw[1:]
        newreg_amount_var.set((("-" if sign == "-" else "+") + raw).strip())

    def _format_amount_entry() -> None:
        raw = (newreg_amount_var.get() or "").strip()
        if not raw:
            return
        try:
            amt = normalize_euro_input(raw)
            if newreg_sign_var.get() == "-":
                amt = -abs(amt)
            else:
                amt = abs(amt)
            txt = format_euro_it(abs(amt))
            newreg_amount_var.set(("-" if amt < 0 else "+") + txt)
        except Exception:
            pass

    def _open_newreg_calendar() -> None:
        # Toggle: se già aperto, chiudi e passa a immissione manuale.
        if newreg_calendar_popup[0] is not None:
            try:
                newreg_calendar_popup[0].destroy()
            except Exception:
                pass
            newreg_calendar_popup[0] = None
            try:
                ent_date.focus_set()
                ent_date.icursor(0)
            except Exception:
                pass
            return
        today = date.today()
        dmin = date_minus_calendar_years(today, 1)
        dmax = date_minus_calendar_years(today, -1)
        cur_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get()) or today.isoformat()
        try:
            cur = date.fromisoformat(cur_iso)
        except Exception:
            cur = today
        if cur < dmin:
            cur = dmin
        if cur > dmax:
            cur = dmax

        top = tk.Toplevel(root)
        top.title("Seleziona data")
        top.transient(root)
        try:
            top.withdraw()
        except Exception:
            pass
        newreg_calendar_popup[0] = top
        top.protocol("WM_DELETE_WINDOW", lambda: (top.destroy(),))
        def _on_destroy(_e: tk.Event | None = None) -> None:
            newreg_calendar_popup[0] = None
        top.bind("<Destroy>", _on_destroy)
        try:
            top.focus_force()
        except Exception:
            pass
        try:
            top.update_idletasks()
            x = int(ent_date.winfo_rootx() + ent_date.winfo_width() + 18)
            y = int(ent_date.winfo_rooty() - 6)
            top.geometry(f"+{x}+{y}")
        except Exception:
            pass

        cur_year = cur.year
        cur_month = cur.month
        header = ttk.Frame(top, padding=14)
        header.pack(fill=tk.X)
        title_lbl = ttk.Label(header, font=("TkDefaultFont", 18, "bold"))
        title_lbl.pack(side=tk.LEFT)
        nav = ttk.Frame(header)
        nav.pack(side=tk.RIGHT)
        days = ttk.Frame(top, padding=14)
        days.pack(fill=tk.BOTH, expand=True)
        ttk.Style(top).configure("NewRegCalNav.TButton", font=("TkDefaultFont", 14, "bold"))

        def _prev(y: int, m: int) -> tuple[int, int]:
            return (y - 1, 12) if m == 1 else (y, m - 1)

        def _next(y: int, m: int) -> tuple[int, int]:
            return (y + 1, 1) if m == 12 else (y, m + 1)

        def _render() -> None:
            nonlocal cur_year, cur_month
            for w in list(days.winfo_children()):
                w.destroy()
            title_lbl.configure(text=f"{calendar.month_name[cur_month]} {cur_year}")
            first_wd = date(cur_year, cur_month, 1).weekday()
            dim = calendar.monthrange(cur_year, cur_month)[1]
            for i in range(first_wd):
                ttk.Label(days, text="", font=("TkDefaultFont", 14, "bold")).grid(row=0, column=i, padx=3, pady=3)
            for dnum in range(1, dim + 1):
                idx = first_wd + dnum - 1
                rr = idx // 7
                cc = idx % 7
                dsel = date(cur_year, cur_month, dnum)
                enabled = dmin <= dsel <= dmax
                cell = tk.Label(
                    days,
                    text=str(dnum),
                    width=5,
                    padx=6,
                    pady=6,
                    font=("TkDefaultFont", 15, "bold"),
                    bg="#ffffff",
                    relief=tk.RAISED,
                    bd=1,
                )
                if enabled:
                    cell.configure(cursor="hand2")
                    cell.bind("<Button-1>", lambda _e, dd=dsel: _pick(dd))
                else:
                    cell.configure(fg="#999999", bg="#f5f5f5")
                cell.grid(row=rr + 1, column=cc, padx=2, pady=2, sticky="nsew")

        def _pick(dsel: date) -> None:
            newreg_date_var.set(to_italian_date(dsel.isoformat()))
            top.destroy()

        def _jump(delta: int) -> None:
            nonlocal cur_year, cur_month
            y, m = cur_year, cur_month
            if delta < 0:
                y, m = _prev(y, m)
            else:
                y, m = _next(y, m)
            if date(y, m, 1) < date(dmin.year, dmin.month, 1) or date(y, m, 1) > date(dmax.year, dmax.month, 1):
                return
            cur_year, cur_month = y, m
            _render()

        ttk.Button(nav, text="<<", style="NewRegCalNav.TButton", command=lambda: _jump(-1)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(nav, text=">>", style="NewRegCalNav.TButton", command=lambda: _jump(1)).pack(side=tk.LEFT)
        _render()
        try:
            top.deiconify()
            top.lift()
        except Exception:
            pass

    def _populate_form_defaults(*, keep_last: bool) -> None:
        nonlocal cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache
        cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache = _cat_and_acc_options()
        cb_cat.configure(values=[n for n, _c in cat_opts_cache])
        cb_acc1.configure(values=[n for n, _c in acc_opts_cache])
        cb_acc2.configure(values=[n for n, _c in acc_opts_cache])
        newreg_no_var.set(f"Nuova registrazione n. {_next_registration_number()}")
        if keep_last:
            newreg_date_var.set(to_italian_date(last_date_iso))
            _set_category_by_code(last_cat_code if last_cat_code else next((c for n, c in cat_opts_cache if n.lower() == "consumi ordinari"), ""))
            a1_name = next((n for n, c in acc_opts_cache if c == last_acc1_code), "Cassa")
            newreg_acc1_var.set(a1_name if a1_name else (acc_opts_cache[0][0] if acc_opts_cache else ""))
            a2_name = next((n for n, c in acc_opts_cache if c == last_acc2_code), "")
            newreg_acc2_var.set(a2_name)
        else:
            newreg_date_var.set(to_italian_date(date.today().isoformat()))
            _set_category_by_code(
                next(
                    (
                        c
                        for n, c in cat_opts_cache
                        if "consumi ordinari" in " ".join(n.strip().lower().replace(".", " ").replace("/", " / ").split())
                    ),
                    "",
                )
            )
            newreg_acc1_var.set(next((n for n, _c in acc_opts_cache if n == "Cassa"), acc_opts_cache[0][0] if acc_opts_cache else ""))
            newreg_acc2_var.set("")
        newreg_amount_var.set("")
        newreg_sign_var.set("+")
        newreg_cheque_var.set("")
        newreg_note_var.set("")
        _sync_cat_note_and_second_account()

    def _collect_new_record_payload() -> tuple[dict, str] | None:
        d_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
        if not d_iso:
            messagebox.showerror("Nuova registrazione", "Data non valida (gg/mm/aaaa).")
            return None
        dsel = date.fromisoformat(d_iso)
        if dsel < date_minus_calendar_years(date.today(), 1) or dsel > date_minus_calendar_years(date.today(), -1):
            messagebox.showerror("Nuova registrazione", "Data fuori intervallo consentito (da -1 anno a +1 anno).")
            return None
        cat_name = newreg_cat_var.get().strip()
        cat_code = _selected_category_code() or newreg_cat_code_var.get().strip()
        if not cat_code:
            messagebox.showerror("Nuova registrazione", "Categoria obbligatoria.")
            return None
        acc1_name = newreg_acc1_var.get().strip()
        acc1_code = next((c for n, c in acc_opts_cache if n == acc1_name), "")
        if not acc1_code:
            messagebox.showerror("Nuova registrazione", "Conto obbligatorio.")
            return None
        giro = _is_giro_label(cat_name)
        acc2_name = newreg_acc2_var.get().strip() if giro else ""
        acc2_code = next((c for n, c in acc_opts_cache if n == acc2_name), "") if giro else ""
        if giro and (not acc2_code or acc2_code == acc1_code):
            messagebox.showerror("Nuova registrazione", "Nel giroconto il secondo conto è obbligatorio e diverso dal primo.")
            return None
        raw_amt = (newreg_amount_var.get() or "").strip()
        if not raw_amt:
            messagebox.showerror("Nuova registrazione", "Importo obbligatorio.")
            return None
        try:
            amt = normalize_euro_input(raw_amt)
        except Exception as exc:
            messagebox.showerror("Nuova registrazione", str(exc))
            return None
        if newreg_sign_var.get() == "-":
            amt = -abs(amt)
        else:
            amt = abs(amt)
        if amt == Decimal("0.00"):
            messagebox.showerror("Nuova registrazione", "Importo a zero non ammesso.")
            return None
        chq = sanitize_single_line_text(newreg_cheque_var.get() or "", max_len=MAX_CHEQUE_LEN)
        note = sanitize_single_line_text(newreg_note_var.get() or "", max_len=MAX_RECORD_NOTE_LEN)
        if not chq:
            chq = "-"
        if not note:
            note = "-"

        target_year = int(dsel.year)
        y_bucket = _ensure_year_bucket(target_year)
        y_records = y_bucket.get("records", [])
        source_index = len(y_records) + 1
        legacy_key = f"APP:manual:{target_year}:{source_index}"
        rec = {
            "year": target_year,
            "source_folder": "APP",
            "source_file": "manual",
            "source_index": source_index,
            "legacy_registration_number": source_index,
            "legacy_registration_key": legacy_key,
            "date_iso": d_iso,
            "category_code": cat_code,
            "category_name": cat_raw_name_by_code_cache.get(cat_code, cat_name),
            "category_note": cat_note_by_code_cache.get(cat_code, "") or "",
            "account_primary_code": acc1_code,
            "account_primary_flags": "",
            "account_primary_with_flags": acc1_code,
            "account_primary_name": acc1_name,
            "account_secondary_code": acc2_code if giro else "",
            "account_secondary_flags": "",
            "account_secondary_with_flags": acc2_code if giro else "",
            "account_secondary_name": acc2_name if giro else "",
            "amount_eur": format_money(amt),
            "amount_lire_original": None,
            "note": note,
            "cheque": chq,
            "raw_flags": "",
            "is_cancelled": False,
            "source_currency": "E",
            "display_currency": "E",
            "display_amount": format_money(amt),
            "raw_record": "",
        }
        amt_preview = ("+" if amt >= 0 else "") + format_euro_it(amt)
        preview = f"Data {to_italian_date(d_iso)}, {cat_name}, {acc1_name}" + (f", {acc2_name}" if giro else "") + f", {amt_preview} EUR"
        return rec, preview

    def _commit_new_record(*, finish: bool) -> None:
        nonlocal last_date_iso, last_cat_code, last_acc1_code, last_acc2_code
        payload = _collect_new_record_payload()
        if payload is None:
            if finish and messagebox.askyesno("Concludi immissione", "Dati incompleti/non validi. Chiudere comunque e tornare a Movimenti?"):
                notebook.select(movimenti_frame)
            return
        rec, preview = payload
        title = "Concludi immissione" if finish else "Conferma immissione"
        if not messagebox.askyesno(title, f"Confermi l'inserimento della registrazione?\n\n{preview}"):
            return
        y_bucket = _ensure_year_bucket(int(rec["year"]))
        y_bucket["records"].append(rec)
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
                backup_output_path=DEFAULT_BACKUP_ENCRYPTED_DB,
            )
        except Exception as exc:
            messagebox.showerror("Nuova registrazione", str(exc))
            return
        populate_movements_trees()
        refresh_balance_footer()
        last_date_iso = str(rec["date_iso"])
        last_cat_code = str(rec["category_code"])
        last_acc1_code = str(rec["account_primary_code"])
        last_acc2_code = str(rec.get("account_secondary_code", ""))
        nuovi_status_var.set("Registrazione inserita.")
        if finish:
            notebook.select(movimenti_frame)
        else:
            _populate_form_defaults(keep_last=True)

    def _clear_values() -> None:
        if not messagebox.askyesno("Cancella valori", "Confermi cancellazione valori immessi?"):
            return
        _populate_form_defaults(keep_last=False)

    def _show_mode(mode: str) -> None:
        if mode == "new":
            nuova_form.pack(fill=tk.X)
            periodiche_placeholder.pack_forget()
            btn_nuova_reg.configure(bg=_NUOVI_BLUE)
            btn_reg_periodiche.configure(bg=_NUOVI_GRAY)
            _populate_form_defaults(keep_last=False)
            try:
                ent_date.focus_set()
            except Exception:
                pass
        else:
            nuova_form.pack_forget()
            periodiche_placeholder.pack(anchor=tk.W)
            btn_nuova_reg.configure(bg=_NUOVI_GRAY)
            btn_reg_periodiche.configure(bg=_NUOVI_BLUE)

    def _on_cat_selected(_e: tk.Event | None = None) -> None:
        code = _selected_category_code()
        newreg_cat_code_var.set(code)
        _sync_cat_note_and_second_account()

    cb_cat.bind("<<ComboboxSelected>>", _on_cat_selected)
    cb_acc1.bind("<<ComboboxSelected>>", lambda _e: _sync_cat_note_and_second_account())
    cb_acc2.bind("<<ComboboxSelected>>", lambda _e: _sync_cat_note_and_second_account())
    ent_date.bind("<KeyPress>", _newreg_date_keypress)
    ent_date.bind("<FocusOut>", lambda _e: _normalize_newreg_date_display())
    ent_date.bind("<Button-1>", lambda _e: (_open_newreg_calendar(), "break")[1])
    def _on_oggi_click() -> None:
        newreg_date_var.set(to_italian_date(date.today().isoformat()))
        try:
            ent_date.focus_set()
            ent_date.icursor(len(newreg_date_var.get() or ""))
        except Exception:
            pass
    btn_oggi.configure(command=_on_oggi_click)
    def _on_date_enter(_e: tk.Event) -> str:
        _normalize_newreg_date_display()
        try:
            cb_cat.focus_set()
        except Exception:
            pass
        return "break"
    ent_date.bind("<Return>", _on_date_enter)

    def _on_cat_enter(_e: tk.Event) -> str:
        _on_cat_selected()
        try:
            cb_acc1.focus_set()
        except Exception:
            pass
        return "break"
    cb_cat.bind("<Return>", _on_cat_enter)

    def _on_acc1_enter(_e: tk.Event) -> str:
        _sync_cat_note_and_second_account()
        try:
            if _is_giro_label(newreg_cat_var.get()) and cb_acc2.winfo_ismapped():
                cb_acc2.focus_set()
            else:
                ent_amt.focus_set()
        except Exception:
            pass
        return "break"
    cb_acc1.bind("<Return>", _on_acc1_enter)

    def _on_acc2_enter(_e: tk.Event) -> str:
        try:
            ent_amt.focus_set()
        except Exception:
            pass
        return "break"
    cb_acc2.bind("<Return>", _on_acc2_enter)
    def _on_amt_enter(_e: tk.Event) -> str:
        raw = (newreg_amount_var.get() or "").strip()
        if not raw:
            try:
                ent_amt.focus_set()
            except Exception:
                pass
            return "break"
        try:
            amt_chk = normalize_euro_input(raw)
            amt_chk = -abs(amt_chk) if newreg_sign_var.get() == "-" else abs(amt_chk)
            if amt_chk == Decimal("0.00"):
                try:
                    ent_amt.focus_set()
                except Exception:
                    pass
                return "break"
        except Exception:
            try:
                ent_amt.focus_set()
            except Exception:
                pass
            return "break"
        _format_amount_entry()
        try:
            ent_chq.focus_set()
        except Exception:
            pass
        return "break"

    def _on_chq_enter(_e: tk.Event) -> str:
        try:
            ent_note.focus_set()
        except Exception:
            pass
        return "break"

    def _on_note_enter(_e: tk.Event) -> str:
        try:
            btn_confirm.focus_set()
        except Exception:
            pass
        return "break"

    ent_amt.bind("<Return>", _on_amt_enter)
    ent_chq.bind("<Return>", _on_chq_enter)
    ent_note.bind("<Return>", _on_note_enter)
    btn_plus.bind("<Button-1>", lambda _e: _apply_sign("+"))
    btn_minus.bind("<Button-1>", lambda _e: _apply_sign("-"))
    btn_confirm.configure(command=lambda: _commit_new_record(finish=False))
    btn_confirm.bind("<Return>", lambda _e: (_commit_new_record(finish=False), "break")[1])
    btn_finish.configure(command=lambda: _commit_new_record(finish=True))
    btn_clear.configure(command=_clear_values)
    btn_nuova_reg.bind("<Button-1>", lambda _e: _show_mode("new"))
    btn_reg_periodiche.bind("<Button-1>", lambda _e: _show_mode("periodiche"))
    _show_mode("new")

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
    ttk.Label(
        opzioni_inner,
        text=f"Backup attivo in {DEFAULT_BACKUP_ENCRYPTED_DB.resolve()}",
    ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

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

    ttk.Label(opzioni_inner, text="File chiave cifratura").grid(row=5, column=0, sticky="w", pady=(12, 6))
    key_entry = ttk.Entry(opzioni_inner, textvariable=key_file_var, width=80)
    key_entry.grid(row=6, column=0, sticky="we", padx=(0, 8))

    def browse_key_file() -> None:
        picked = filedialog.asksaveasfilename(
            initialdir=str(Path(key_file_var.get()).parent),
            initialfile=Path(key_file_var.get()).name,
            defaultextension=".key",
            filetypes=[("Key files", "*.key"), ("All files", "*.*")],
        )
        if picked:
            key_file_var.set(picked)

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_key_file).grid(row=6, column=1, sticky="w")

    status_var = tk.StringVar(value="")
    ttk.Label(opzioni_inner, textvariable=status_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 0))

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
            save_encrypted_db_dual(
                new_db,
                Path(data_file_var.get()),
                Path(key_file_var.get()),
                backup_output_path=DEFAULT_BACKUP_ENCRYPTED_DB,
            )
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
    ).grid(row=7, column=0, sticky="w", pady=(16, 0))

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
