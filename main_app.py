#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import html as html_module
import json
import os
import re
from difflib import SequenceMatcher
import shutil
import calendar
import platform
import subprocess
import sys
import time
import tempfile
import tkinter as tk
import webbrowser
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from datetime import date, datetime, timedelta

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - runtime optional dependency check
    Fernet = None
    InvalidToken = Exception

import cloud_sync_wait
import email_client
import os_boot_time
import data_workspace
import mail_gate
import periodiche
import security_auth

# Sfondo pagina Movimenti (allineato al login).
MOVIMENTI_PAGE_BG = security_auth.CDC_AZZURRO_CHIARO_BG
# Toni azzurri per griglie, calendari e campi (coerenza tra tutte le schede).
CDC_GRID_STRIPE0_BG = "#d0e8f4"
CDC_GRID_STRIPE1_BG = "#e4f3fa"
CDC_GRID_HEADING_BG = "#bdddf0"
CDC_ENTRY_FIELD_BG = "#f2f9fc"
CDC_CAL_CELL_BG = "#f6fbfe"
CDC_CAL_SELECTED_BG = "#8ecae6"
CDC_CAL_DISABLED_BG = "#dfeaf1"

from import_legacy import (
    EURO_CONVERSION_RATE,
    MAX_ACCOUNT_NAME_LEN,
    MAX_ACCOUNTS_COUNT,
    MAX_CATEGORY_NAME_LEN,
    MAX_CATEGORIES_COUNT,
    MAX_CATEGORY_NOTE_LEN,
    MAX_CHEQUE_LEN,
    MAX_RECORD_NOTE_LEN,
    clip_text,
    format_euro_it,
    format_money,
    normalize_euro_input,
    run_import_legacy,
)


DEFAULT_CDC_ROOT = Path("/Users/macand/Library/CloudStorage/Dropbox/CdC")
# Cartella dati (`.key`, `.enc`, `legacy_import/`): configurata dall'utente; vedi ``data_workspace``.
DEFAULT_VIRTUALE_SALDO_FILE = Path.home() / "Library/Application Support/ContiDiCasa/memoria_cassa.json"
VIRTUALE_ACCOUNT_NAME = "VIRTUALE"
DEBUG_LOG_PATH = "/Users/macand/Library/CloudStorage/Dropbox/CursorAppMacCdc/.cursor/debug-8c5304.log"
DEBUG_SESSION_ID = "8c5304"

# Inserimento griglia a lotti: migliaia di righe × 3 Treeview bloccano il main thread (macOS: beach ball).
MOVEMENTS_INSERT_BATCH = 400

# Dopo un boot recente, chiedere conferma Dropbox prima di aprire il database cifrato.
# L’attesa “file stabile” in cartelle Dropbox è in ``cloud_sync_wait`` (variabili ``CONTI_SKIP_CLOUD_SYNC_WAIT`` / ``CONTI_VERBOSE_CLOUD_WAIT``).
_BOOT_DROPBOX_CONFIRM_WITHIN_SECONDS = 5 * 60

# Limite numerico categorie/conti: ``MAX_CATEGORIES_COUNT`` / ``MAX_ACCOUNTS_COUNT`` in ``import_legacy``.

# Stessa regola della colonna Importo nella griglia movimenti.
COLOR_AMOUNT_POS = "#006400"
COLOR_AMOUNT_NEG = "#b22222"


def app_title_text() -> str:
    return f"Conti di casa - {date.today().strftime('%d/%m/%Y')}"


# Suffisso titolo/intestazione quando la registrazione non è ancora confermata (in attesa email REGISTRA:/REGISTRATO:).
GUEST_DISPLAY_SUBTITLE = "di capitan Uncino"


def window_title_for_session(db: dict, session: security_auth.AppSession) -> str:
    """Titolo finestra principale: «di capitan Uncino» se registrazione non verificata; altrimenti suffisso utente."""
    security_auth.ensure_security(db)
    d = date.today().strftime("%d/%m/%Y")
    up = db.get("user_profile") or {}
    if not bool(up.get("registration_verified")):
        return f"Conti di casa {GUEST_DISPLAY_SUBTITLE} — {d}"
    suf = (up.get("display_name_suffix") or "").strip()
    return f"Conti di casa {suf} — {d}" if suf else f"Conti di casa — {d}"


def print_user_header_text(db: dict, session: security_auth.AppSession | None = None) -> str:
    """Riga intestazione stampa saldi/ricerca: allineata al titolo finestra."""
    security_auth.ensure_security(db)
    up = db.get("user_profile") or {}
    if not bool(up.get("registration_verified")):
        return f"Conti di casa {GUEST_DISPLAY_SUBTITLE}"
    suf = (up.get("display_name_suffix") or "").strip()
    if suf:
        return f"Conti di casa {suf}"
    email = (up.get("email") or "").strip()
    if email:
        return f"Conti di casa · {email}"
    return "Conti di casa"


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


def pack_centered_page_title(
    parent: tk.Widget,
    *,
    title: str | None = None,
    banner_style: str | None = None,
    title_bg: str | None = None,
    banner_tk_bg: str | None = None,
) -> None:
    """Titolo app ripetuto in cima a ogni scheda, centrato e ben visibile."""
    if banner_tk_bg is not None:
        bar = tk.Frame(parent, bg=banner_tk_bg, highlightthickness=0)
    elif banner_style:
        bar = ttk.Frame(parent, style=banner_style)
    else:
        bar = ttk.Frame(parent)
    bar.pack(fill=tk.X, pady=(0, 14))
    lab_kw: dict[str, object] = {
        "master": bar,
        "text": title if title is not None else app_title_text(),
        "font": title_banner_font(),
        "fg": "#111111",
        "anchor": tk.CENTER,
    }
    lbl_bg = title_bg if title_bg is not None else banner_tk_bg
    if lbl_bg is not None:
        lab_kw["bg"] = lbl_bg
    tk.Label(**lab_kw).pack(fill=tk.X)


def to_decimal(value: str) -> Decimal:
    return Decimal(str(value).replace(",", "."))


def bind_return_and_kp_enter(widget: tk.Misc, callback: Callable[..., object], *, add: bool = False) -> None:
    """Invio principale e Invio del tastierino numerico eseguono lo stesso handler."""
    widget.bind("<Return>", callback, add=add)
    widget.bind("<KP_Enter>", callback, add=add)


def read_virtuale_saldo() -> Decimal:
    """Saldo virtuale residuo da scaricare (persistente tra sessioni)."""
    try:
        if DEFAULT_VIRTUALE_SALDO_FILE.exists():
            return Decimal(str(json.loads(DEFAULT_VIRTUALE_SALDO_FILE.read_text(encoding="utf-8")).get("euro", "0")))
    except Exception:
        pass
    return Decimal("0")


def write_virtuale_saldo(value: Decimal) -> None:
    try:
        DEFAULT_VIRTUALE_SALDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        v = value.quantize(Decimal("0.01"))
        if v <= 0:
            if DEFAULT_VIRTUALE_SALDO_FILE.exists():
                DEFAULT_VIRTUALE_SALDO_FILE.unlink()
        else:
            DEFAULT_VIRTUALE_SALDO_FILE.write_text(json.dumps({"euro": str(v)}), encoding="utf-8")
    except Exception:
        pass


def bind_entry_first_char_uppercase(var: tk.StringVar, entry: tk.Misc) -> None:
    """Il primo carattere del testo viene forzato in maiuscolo se immesso minuscolo."""
    lock: list[bool] = [False]

    def _on_write(*_args: object) -> None:
        if lock[0]:
            return
        s = var.get()
        if not s:
            return
        c0 = s[0]
        if not c0.islower():
            return
        try:
            pos = entry.index(tk.INSERT)
        except Exception:
            pos = None
        lock[0] = True
        try:
            var.set(c0.upper() + s[1:])
            if pos is not None:
                entry.icursor(min(pos, len(var.get())))
        finally:
            lock[0] = False

    var.trace_add("write", _on_write)


def bind_euro_amount_entry_validation(
    entry: tk.Misc, var: tk.StringVar, *, allow_leading_sign: bool = True
) -> None:
    """
    Limita immissione e incolla a importi euro: cifre e separatori . e ,; + e − solo come primo carattere
    (sostituisce il segno esistente). Con allow_leading_sign=False (es. saldo cassa) non ammette segno.
    """

    def _keypress(event: tk.Event) -> str | None:
        keysym = getattr(event, "keysym", "")
        if keysym in (
            "BackSpace",
            "Delete",
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Tab",
            "ISO_Left_Tab",
            "Return",
            "KP_Enter",
            "Escape",
            "Prior",
            "Next",
        ):
            return None
        ch = event.char or ""
        if not ch:
            return None
        st = int(getattr(event, "state", 0) or 0)
        if st & (0x0004 | 0x0008 | 0x20000 | 0x100000):
            return None
        if ord(ch) < 32:
            return None

        w = event.widget
        try:
            pos = int(w.index(tk.INSERT))
        except (tk.TclError, ValueError, TypeError):
            pos = 0
        s = var.get() or ""

        if ch in "+-":
            if not allow_leading_sign:
                return "break"
            if pos != 0:
                return "break"
            try:
                if w.selection_present():
                    if int(w.index("sel.first")) != 0:
                        return "break"
                elif s[:1] in "+-" and s:
                    if ch != s[0]:
                        var.set(ch + s[1:])
                    return "break"
            except tk.TclError:
                pass
            return None

        if ch.isdigit():
            return None
        if ch in ",.":
            return None
        return "break"

    def _paste(event: tk.Event) -> str:
        try:
            clip = event.widget.clipboard_get()
        except tk.TclError:
            return "break"
        t = clip.strip().replace(" ", "")
        if not t:
            return "break"
        pat = r"[+-]?[0-9.,]*" if allow_leading_sign else r"[0-9.,]*"
        if not re.fullmatch(pat, t):
            return "break"
        try:
            normalize_euro_input(t)
        except Exception:
            return "break"
        w = event.widget
        s = var.get() or ""
        try:
            a = int(w.index("sel.first"))
            b = int(w.index("sel.last"))
        except tk.TclError:
            try:
                p = int(w.index(tk.INSERT))
            except tk.TclError:
                return "break"
            a = b = p
        merged = s[:a] + t + s[b:]
        if merged.strip():
            try:
                normalize_euro_input(merged.replace(" ", ""))
            except Exception:
                return "break"
        var.set(merged)
        try:
            w.icursor(min(a + len(t), len(merged)))
        except tk.TclError:
            pass
        return "break"

    entry.bind("<KeyPress>", _keypress, add="+")
    entry.bind("<<Paste>>", _paste, add="+")


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


def immissione_date_bounds(today: date | None = None) -> tuple[date, date]:
    """Intervallo date per nuova registrazione e periodiche: −1 anno / +1 anno da oggi."""
    t = today or date.today()
    return (date_minus_calendar_years(t, 1), date_minus_calendar_years(t, -1))


def build_immissione_calendar_toplevel(
    root: tk.Misc,
    *,
    title: str,
    anchor: tk.Misc,
    field_min: date,
    field_max: date,
    current: date,
    on_date_chosen: Callable[[date], None],
    ui_font: tuple = ("TkDefaultFont", 12, "bold"),
) -> tk.Toplevel:
    """
    Popup calendario allineato ai filtri data Movimenti (layout compatto, sotto il campo,
    anni nel range, giorni fuori range disabilitati). Non modale (grab rilasciato).
    """
    if field_min > field_max:
        field_min, field_max = field_max, field_min
    cur = current
    if cur < field_min:
        cur = field_min
    if cur > field_max:
        cur = field_max

    top = tk.Toplevel(root)
    top.title(title)
    top.transient(root)
    try:
        top.withdraw()
    except Exception:
        pass
    try:
        top.grab_release()
    except Exception:
        pass
    top.protocol("WM_DELETE_WINDOW", lambda: top.destroy())

    selected_date = cur
    cur_year = cur.year
    cur_month = cur.month

    years_available = [y for y in range(field_min.year, field_max.year + 1)]
    if not years_available:
        years_available = [cur_year]
    if cur_year not in years_available:
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

    def _cell_pick(dsel: date) -> None:
        on_date_chosen(dsel)
        try:
            top.destroy()
        except Exception:
            pass

    def render() -> None:
        nonlocal cur_year, cur_month
        for child in list(days_frame.winfo_children()):
            child.destroy()
        title_lbl.configure(text=f"{calendar.month_name[cur_month]} {cur_year}")
        _update_month_nav_state()
        nonlocal suppress_year_trace
        if year_var.get() != str(cur_year):
            suppress_year_trace = True
            year_var.set(str(cur_year))
            suppress_year_trace = False

        first_wd = date(cur_year, cur_month, 1).weekday()
        days_in_month = calendar.monthrange(cur_year, cur_month)[1]

        for i in range(first_wd):
            ttk.Label(days_frame, text="").grid(row=0, column=i, padx=1, pady=1, sticky="nsew")

        for day_num in range(1, days_in_month + 1):
            idx = first_wd + day_num - 1
            row = idx // 7
            col = idx % 7
            dsel = date(cur_year, cur_month, day_num)
            in_bounds = field_min <= dsel <= field_max
            cell = tk.Label(
                days_frame,
                text=str(day_num),
                width=3,
                padx=2,
                pady=2,
                fg="#111111",
                bg=CDC_CAL_CELL_BG,
                relief=tk.RAISED,
                bd=1,
                highlightthickness=0,
                font=ui_font,
            )
            if in_bounds:
                cell.configure(cursor="hand2")
                cell.bind("<Button-1>", lambda _e, dd=dsel: _cell_pick(dd))
            else:
                cell.configure(fg="#999999", bg=CDC_CAL_DISABLED_BG)

            if dsel == selected_date:
                cell.configure(
                    bg=CDC_CAL_SELECTED_BG,
                    relief=tk.SUNKEN,
                    bd=2,
                    highlightthickness=1,
                    highlightbackground="#5fa8c4",
                    highlightcolor="#5fa8c4",
                )

            cell.grid(row=row + 1, column=col, padx=1, pady=1, sticky="nsew")

        for c in range(7):
            days_frame.grid_columnconfigure(c, weight=1)

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
        nonlocal suppress_year_trace
        if year_var.get() != str(cur_year):
            suppress_year_trace = True
            year_var.set(str(cur_year))
            suppress_year_trace = False
        render()

    labels = ttk.Frame(top, padding=(6, 0, 6, 0))
    labels.pack(fill=tk.X)
    for i, name in enumerate(["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]):
        ttk.Label(labels, text=name, font=ui_font).grid(row=0, column=i, padx=1, pady=2, sticky="nsew")

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
        tdy = date.today()
        picked = max(field_min, min(tdy, field_max))
        on_date_chosen(picked)
        try:
            top.destroy()
        except Exception:
            pass

    render()

    def _place_calendar_below_anchor() -> None:
        try:
            top.update_idletasks()
            root.update_idletasks()
            ex = int(anchor.winfo_rootx())
            ey_top = int(anchor.winfo_rooty())
            ey_bottom = int(ey_top + anchor.winfo_height())
            w = max(1, int(top.winfo_reqwidth()))
            h = max(1, int(top.winfo_reqheight()))
            scr_w = int(top.winfo_screenwidth())
            scr_h = int(top.winfo_screenheight())
            gap = 4
            x = ex
            y = ey_bottom + gap
            if x + w > scr_w - 10:
                x = max(10, scr_w - w - 10)
            if y + h > scr_h - 10:
                y = ey_top - h - gap
            if y < 10:
                y = 10
            top.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    _place_calendar_below_anchor()
    try:
        top.deiconify()
        top.lift()
    except Exception:
        pass
    try:
        top.focus_force()
    except Exception:
        pass
    return top


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


def record_is_within_recent_mod_delete_window(rec: dict, *, today: date | None = None) -> bool:
    """
    Modifica/elimina in Movimenti consentite solo da inizio anno precedente (es. nel 2026: da 01/01/2025).
    """
    today = today or date.today()
    iso = str(rec.get("date_iso", "")).strip()
    if not iso:
        return False
    try:
        rd = date.fromisoformat(iso)
    except Exception:
        return False
    cutoff = date(today.year - 1, 1, 1)
    return rd >= cutoff


def record_contains_any_asterisk(rec: dict) -> bool:
    """True se qualunque campo stringa della registrazione contiene '*'."""
    for v in rec.values():
        if isinstance(v, str) and "*" in v:
            return True
    return False


def category_display_name(raw: str) -> str:
    base = (raw or "").strip()
    return base[1:].strip() if base[:1] in {"+", "-", "="} else base


def is_hidden_dotazione_category_name(raw: str) -> bool:
    """True se l’etichetta è la categoria legacy «dotazione iniziale» (mai mostrata in elenchi/UI)."""
    disp = category_display_name(raw or "").strip().lower()
    if not disp:
        return False
    norm = " ".join(disp.replace(".", " ").split())
    return "dotazione" in norm


def latest_year_bucket(db: dict) -> dict | None:
    """Bucket dell’anno massimo nel DB (piano conti «corrente» per nuove registrazioni)."""
    years = db.get("years") or []
    if not years:
        return None
    return max(years, key=lambda y: int(y.get("year", 0)))


# Piano categorie/conti per Nuove registrazioni e pagina «Categorie e conti»: anno di riferimento legacy.
PLAN_REFERENCE_YEAR = 2026
# Dotazione iniziale (categoria 0) solo nell’anno legacy previsto; altre annate senza dotazione.
LEGACY_DOTAZIONE_YEAR = 1990


def year_bucket_for_calendar_year(db: dict, year: int) -> dict | None:
    for yb in db.get("years") or []:
        if int(yb.get("year", 0)) == int(year):
            return yb
    return None


def chart_clone_source_bucket(db: dict) -> dict | None:
    """Template per clonare piano su nuovi anni: bucket 2026 se presente, altrimenti ultimo anno."""
    yb = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    if yb is not None:
        return yb
    return latest_year_bucket(db)


GIRATA_NOTE_DEFAULT = "Serve a girare importi da un conto all'altro, e non indica una spesa reale"


def plan_conti_reference_bucket(db: dict) -> dict | None:
    """Riferimento UI piano conti: anno 2026 se presente, altrimenti il bucket più completo."""
    y26 = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    if y26 is not None:
        return y26
    years = db.get("years") or []
    if not years:
        return None
    return max(
        years,
        key=lambda y: (
            len([c for c in (y.get("categories") or []) if str(c.get("code", "")) != "0"]),
            len(y.get("accounts") or []),
            int(y.get("year", 0)),
        ),
    )


def plan_conti_category_name_locked(name_raw: str) -> bool:
    """Nome categoria non modificabile: Consumi ordinari, Girata conto/conto."""
    disp = category_display_name(name_raw).strip().lower()
    if disp == "consumi ordinari":
        return True
    nn = " ".join(disp.replace(".", " ").replace("/", " / ").split())
    if "girata conto / conto" in nn or "girata conto conto" in nn:
        return True
    return False


def plan_conti_category_note_locked(name_raw: str) -> bool:
    """Solo Girata: nota predefinita e non editabile da qui."""
    disp = category_display_name(name_raw).strip().lower()
    nn = " ".join(disp.replace(".", " ").replace("/", " / ").split())
    if "girata conto / conto" in nn or "girata conto conto" in nn:
        return True
    return False


def plan_conti_account_is_cassa(name_raw: str) -> bool:
    return category_display_name(name_raw).strip().lower() == "cassa"


def plan_conti_names_have_attinenza(old_raw: str, new_raw: str) -> bool:
    """True se nome nuovo è «vicino» al vecchio (SequenceMatcher >= 0.55 oppure inclusione >= 4 char)."""
    na = category_display_name(old_raw).strip().lower()
    nb = category_display_name(new_raw).strip().lower()
    if not na or not nb or na == nb:
        return False
    if SequenceMatcher(None, na, nb).ratio() >= 0.55:
        return True
    if len(nb) >= 4 and (nb in na or na in nb):
        return True
    if len(na) >= 4 and (nb in na or na in nb):
        return True
    return False


def propagate_category_chart_by_code(db: dict, code: str, name: str, note: str | None) -> None:
    nt = note if (note or "").strip() else None
    sc = str(code).strip()
    for yb in db.get("years", []) or []:
        found = False
        for c in yb.get("categories", []) or []:
            if str(c.get("code", "")).strip() == sc:
                c["name"] = name
                c["note"] = nt
                if "category_note" in c:
                    c["category_note"] = nt
                found = True
                break
        if not found:
            yb.setdefault("categories", []).append({"code": sc, "name": name, "note": nt})


def propagate_account_chart_by_code(db: dict, code: str, name: str) -> None:
    sc = str(code).strip()
    for yb in db.get("years", []) or []:
        found = False
        for a in yb.get("accounts", []) or []:
            if str(a.get("code", "")).strip() == sc:
                a["name"] = name
                found = True
                break
        if not found:
            yb.setdefault("accounts", []).append({"code": sc, "name": name})


def sync_record_category_names_for_code(db: dict, code: str, canonical_name: str) -> None:
    for yb in db.get("years", []) or []:
        for r in yb.get("records", []) or []:
            if str(r.get("category_code", "")).strip() != str(code).strip():
                continue
            r["category_name"] = canonical_name


def sync_record_account_names_for_code(db: dict, code: str, new_name: str) -> None:
    c = str(code).strip()
    for yb in db.get("years", []) or []:
        for r in yb.get("records", []) or []:
            if str(r.get("account_primary_code", "")).strip() == c:
                r["account_primary_name"] = new_name
            if str(r.get("account_secondary_code", "")).strip() == c:
                r["account_secondary_name"] = new_name


def category_code_used_any_year(db: dict, code: str) -> bool:
    cc = str(code).strip()
    for yb in db.get("years", []) or []:
        for r in yb.get("records", []) or []:
            if str(r.get("category_code", "")).strip() == cc:
                return True
    return False


def account_code_used_any_year(db: dict, code: str) -> bool:
    c = str(code).strip()
    for yb in db.get("years", []) or []:
        for r in yb.get("records", []) or []:
            if str(r.get("account_primary_code", "")).strip() == c:
                return True
            if str(r.get("account_secondary_code", "")).strip() == c:
                return True
    return False


def account_balance_for_code_latest_chart(db: dict, account_code: str) -> Decimal | None:
    """Saldo footer: priorità a *sld.aco dell’anno di riferimento (2026) se importato; altrimenti calcolo da movimenti."""
    if not db.get("years"):
        return Decimal("0")
    y_ref = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    if y_ref:
        ls = y_ref.get("legacy_saldi")
        accs = y_ref.get("accounts") or []
        amts = (ls or {}).get("amounts") if isinstance(ls, dict) else None
        if isinstance(amts, list) and amts:
            idx = next(
                (i for i, a in enumerate(accs) if str(a.get("code", "")).strip() == str(account_code).strip()),
                None,
            )
            if idx is not None and idx < len(amts):
                try:
                    legacy_val = Decimal(str(amts[idx]))
                except InvalidOperation:
                    legacy_val = None
                if legacy_val is not None:
                    new_fx = compute_new_records_effect(db)
                    return legacy_val + (new_fx[idx] if idx < len(new_fx) else Decimal("0"))
    _ly, _names, bals = compute_balances_from_2022(db)
    yb = latest_year_bucket(db)
    if not yb:
        return None
    accs = yb.get("accounts", []) or []
    idx = next(
        (i for i, a in enumerate(accs) if str(a.get("code", "")).strip() == str(account_code).strip()),
        None,
    )
    if idx is None or idx >= len(bals):
        return None
    return bals[idx]


def legacy_absolute_account_amounts(db: dict, n_accounts: int) -> list[Decimal] | None:
    """Saldi assoluti da *sld.aco (import 2026), allineati per indice al piano conti corrente; None se assenti."""
    y_ref = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    if not y_ref:
        return None
    ls = y_ref.get("legacy_saldi")
    if not isinstance(ls, dict):
        return None
    raw = ls.get("amounts")
    if not isinstance(raw, list) or not raw:
        return None
    out: list[Decimal] = []
    for i in range(n_accounts):
        if i < len(raw):
            try:
                out.append(Decimal(str(raw[i])))
            except InvalidOperation:
                out.append(Decimal("0"))
        else:
            out.append(Decimal("0"))
    return out


def remove_category_from_all_years(db: dict, code: str) -> None:
    cc = str(code).strip()
    for yb in db.get("years", []) or []:
        yb["categories"] = [c for c in (yb.get("categories") or []) if str(c.get("code", "")) != cc]


def remove_account_from_all_years(db: dict, code: str) -> None:
    c = str(code).strip()
    for yb in db.get("years", []) or []:
        yb["accounts"] = [a for a in (yb.get("accounts") or []) if str(a.get("code", "")) != c]


def sync_record_category_from_plan(rec: dict, year_categories: list[dict[str, str]], code_str: str) -> None:
    rec["category_code"] = code_str
    cs = str(code_str).strip()
    for c in year_categories:
        if str(c.get("code", "")).strip() == cs:
            rec["category_name"] = str(c.get("name", "") or "").strip() or str(rec.get("category_name") or "")
            return
    if cs.isdigit():
        idx = int(cs)
        if 0 <= idx < len(year_categories):
            rec["category_name"] = (
                str(year_categories[idx].get("name", "") or "").strip() or str(rec.get("category_name") or "")
            )


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
    return {y["year"]: y["accounts"] for y in db.get("years", [])}


def year_categories_map(db: dict) -> dict[int, list[dict[str, str]]]:
    return {y["year"]: y["categories"] for y in db.get("years", [])}


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
        name_key = "account_primary_name" if which == "primary" else "account_secondary_name"
        return str(rec.get(name_key, "") or "").strip()
    idx = int(code) - 1
    if 0 <= idx < len(accounts_for_year):
        return accounts_for_year[idx]["name"]
    return ""


def category_name_for_record(rec: dict, categories_for_year: list[dict[str, str]]) -> str:
    code = str(rec.get("category_code", "")).strip()

    def _allow_dotazione_visible() -> bool:
        try:
            return int(rec.get("year", 0)) == 1990 and code == "0"
        except (TypeError, ValueError):
            return False

    if not code.isdigit():
        out = (rec.get("category_name") or "").strip()
        if is_hidden_dotazione_category_name(out) and not _allow_dotazione_visible():
            return ""
        return out
    base = ""
    for c in categories_for_year:
        if str(c.get("code", "")).strip() == code:
            base = str(c.get("name", "") or "")
            break
    else:
        try:
            idx = int(code)
        except ValueError:
            out = (rec.get("category_name") or "").strip()
            if is_hidden_dotazione_category_name(out) and not _allow_dotazione_visible():
                return ""
            return out
        if 0 <= idx < len(categories_for_year):
            base = str(categories_for_year[idx].get("name", "") or "")
        else:
            base = str(rec.get("category_name") or "")
    # Output-only: hide leading control sign (+, -, =)
    out = base[1:].strip() if base[:1] in {"+", "-", "="} else base.strip()
    if is_hidden_dotazione_category_name(out) and not _allow_dotazione_visible():
        return ""
    return out


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
    """Solo dati legacy/import: categoria codice 0. In app non è prevista: valorizzare un conto con una girata conto/conto."""
    return _category_code_int(rec) == 0


def compute_balances_from_2022(db: dict) -> tuple[int, list[str], list[Decimal]]:
    """
    Saldi da tutte le annate presenti fino all’ultimo anno; dotazione (cat. 0) solo nel 1990.
    Piano conti = ultimo anno. + sul conto 1; giroconto: − sul conto 2.
    """
    if not db.get("years"):
        return (date.today().year, [], [])
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    n_accounts = len(accounts)

    pool: list[dict] = []
    for yd in db["years"]:
        y = int(yd["year"])
        if y > latest_year:
            continue
        pool.extend(yd["records"])
    pool.sort(key=record_merge_sort_key)

    balances = [Decimal("0") for _ in accounts]
    for rec in pool:
        if rec.get("is_cancelled"):
            continue
        y = int(rec["year"])
        if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
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
    Come `compute_balances_from_2022`, ma considera solo registrazioni con `date_iso <= cutoff_date_iso`
    (saldo cumulato alla data indicata, inclusiva). Es.: saldo cassa in nuova registrazione.
    """
    if not db.get("years"):
        return (date.today().year, [], [])
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    n_accounts = len(accounts)

    pool: list[dict] = []
    for yd in db["years"]:
        y = int(yd["year"])
        if y > latest_year:
            continue
        pool.extend(yd["records"])
    pool.sort(key=record_merge_sort_key)

    balances = [Decimal("0") for _ in accounts]
    for rec in pool:
        if rec.get("is_cancelled"):
            continue
        y = int(rec["year"])
        if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
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


def compute_new_records_effect(db: dict) -> list[Decimal]:
    """Effetto netto sui conti delle sole registrazioni create nell'app (raw_record vuoto).
    Le registrazioni di scarico Virtuale (is_virtuale_discharge) sono escluse perché non
    toccano i saldi reali dei conti."""
    if not db.get("years"):
        return []
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    n_accounts = len(accounts)

    balances = [Decimal("0") for _ in accounts]
    for yd in db["years"]:
        for rec in yd.get("records", []):
            if rec.get("is_cancelled"):
                continue
            if (rec.get("raw_record") or "").strip():
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            y = int(rec["year"])
            if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
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
    return balances


def compute_balances_future_dated_only(db: dict, *, today_iso: str) -> tuple[int, list[str], list[Decimal]]:
    """
    Effetto netto sui conti delle sole registrazioni con `date_iso` > `today_iso`.
    «Saldi alla data di oggi» = saldi assoluti − questi effetti (registrazioni future).
    """
    if not db.get("years"):
        return (date.today().year, [], [])
    latest_year = max(y["year"] for y in db["years"])
    year_data = next(y for y in db["years"] if y["year"] == latest_year)
    accounts = year_data["accounts"]
    n_accounts = len(accounts)

    pool: list[dict] = []
    for yd in db["years"]:
        y = int(yd["year"])
        if y > latest_year:
            continue
        pool.extend(yd["records"])
    pool.sort(key=record_merge_sort_key)

    balances = [Decimal("0") for _ in accounts]
    for rec in pool:
        if rec.get("is_cancelled"):
            continue
        if rec.get("is_virtuale_discharge"):
            continue
        y = int(rec["year"])
        if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
            continue
        r_date = str(rec.get("date_iso", ""))
        if not r_date or r_date <= today_iso:
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
        uh = _pdf_safe_text(str(snap.get("user_header") or "Conti di casa"))
        pdf.cell(0, 6, uh, align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
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
        pdf.cell(w_amt, line_h * 1.3, "Saldi assol.", border=1, align="C")
        pdf.set_font("Helvetica", "B", fs_head)
        pdf.cell(w_amt, line_h * 1.3, "Saldi oggi", border=1, align="C")
        pdf.set_font("Helvetica", "", fs_head)
        pdf.cell(w_amt, line_h * 1.3, "Differenze", border=1, align="C")
        pdf.ln(line_h * 1.3)

        for i, nm in enumerate(names):
            pdf.set_x(x_table)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "B", fs_body)
            show_nm = _pdf_safe_text((nm or "").strip()[:10])
            pdf.cell(w_conti, line_h, show_nm, border=1, align="L")
            amt_cell(snap["amts_abs"][i], w_amt, bold=True)
            amt_cell(snap["amts_today"][i], w_amt, bold=True)
            amt_cell(snap["diffs"][i], w_amt, bold=False)
            pdf.ln(line_h)

        pdf.set_fill_color(240, 240, 240)
        pdf.set_x(x_table)
        pdf.set_font("Helvetica", "B", fs_body)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(w_conti, line_h, "TOTALE", border=1, align="L", fill=True)
        for amt, bold in (
            (snap["total_abs"], True),
            (snap["total_today"], True),
            (snap["total_diff"], False),
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
    user_header: str,
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
            _pdf_safe_text(user_header or "Conti di casa"),
            align="C",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
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
    """Categoria 0 (Dotazione) nascosta tranne le registrazioni importate per il 1990 (Conti90)."""
    if rec.get("is_cancelled"):
        return False
    cat = str(rec.get("category_code", "")).strip()
    if cat == "0":
        try:
            return int(rec.get("year", 0)) == 1990
        except (TypeError, ValueError):
            return False
    return True


def merged_categories_for_plan_editor(db: dict) -> list[dict]:
    """
    Solo il piano categorie dell’anno di riferimento (2026): immissione e «Categorie e conti».
    I filtri Movimenti restano basati sui piani per anno del record (altre funzioni).
    """
    yb = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR) or chart_clone_source_bucket(db)
    if not yb:
        return []
    out: list[dict] = []
    for c in yb.get("categories") or []:
        code = str(c.get("code", "")).strip()
        if not code or code == "0":
            continue
        if is_hidden_dotazione_category_name(str(c.get("name", ""))):
            continue
        out.append(copy.deepcopy(c))

    def _ck(c: dict) -> tuple[int, str]:
        raw = str(c.get("code", "")).strip()
        return (int(raw), raw) if raw.isdigit() else (999999, raw)

    return sorted(out, key=_ck)


def merge_account_charts_across_years(db: dict) -> list[dict]:
    """Solo i conti dell’anno di riferimento (2026), come per le categorie."""
    yb = year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR) or chart_clone_source_bucket(db)
    if not yb:
        return []
    merged = [copy.deepcopy(a) for a in (yb.get("accounts") or [])]

    def _ak(a: dict) -> tuple[int, str]:
        raw = str(a.get("code", "")).strip()
        return (int(raw), raw) if raw.isdigit() else (999999, raw)

    return sorted(merged, key=_ak)


def category_row_merged_note(c: dict) -> str:
    return str(c.get("note") or c.get("category_note") or "").strip()


def migrate_dotazione_remove_from_plan_charts(db: dict) -> bool:
    """
    Rimuove dal piano la riga categoria codice 0 (Dotazione), non usata come categoria operativa.

    Eccezione: **anno 1990** — le dotazioni importate usano codice 0; va mantenuta la riga nel piano
    di quell’anno così nomi/note e `category_name_for_record` restano coerenti.

    Nessuno shift delle note sulle altre righe.
    """
    changed = False
    for yb in db.get("years") or []:
        if int(yb.get("year", 0)) == 1990:
            continue
        cats = yb.get("categories") or []
        if not cats:
            continue
        if not any(str(c.get("code", "")).strip() == "0" for c in cats):
            continue
        yb["categories"] = [
            copy.deepcopy(c) for c in cats if str(c.get("code", "")).strip() != "0"
        ]
        changed = True
    return changed


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


def record_merge_sort_key(rec: dict) -> tuple[int, int, str, str, int]:
    """
    Ordine di merge unificato (griglia, numerazione globale, ricerca per reg.):
    anno → rank (legacy 0, APP 1) → [legacy: cartella → file → indice]
                                     [APP: solo indice (ordine di immissione)].
    I record legacy vengono sempre prima dei record APP nello stesso anno.
    I record APP seguono rigorosamente l'ordine di immissione (source_index),
    indipendentemente dalla data o dal tipo (manual/periodic).
    """
    y = int(rec.get("year", 0))
    folder = str(rec.get("source_folder", "") or "")
    rank = 1 if folder == "APP" else 0
    return (
        y,
        rank,
        folder if rank == 0 else "",
        str(rec.get("source_file", "") or "") if rank == 0 else "",
        int(rec.get("source_index", 0) or 0),
    )


def unified_registration_sequence_map(records_sorted: list[dict]) -> dict[str, int]:
    """
    Progressivo globale 1..N coerente con `record_merge_sort_key` (ordine di merge, non il campo JSON
    `registration_number`). `legacy_registration_number` nel .dat è solo l'indice dentro l'anno.
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


def _user_library_conti_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "ContiDiCasa"


def user_local_backup_enc_path(primary_enc: Path) -> Path:
    """Copia di sicurezza nella Library **dell’utente** che esegue l’app (es. macOS: ``~/Library/...``).

    Percorso: ``Application Support/ContiDiCasa/<stem>_backup.enc`` dove ``stem`` è il nome del file
    principale senza estensione (stesso criterio del DB operativo, es. ``conti_utente_<hash>_backup.enc``).
    """
    return _user_library_conti_support_dir() / f"{primary_enc.stem}_backup.enc"


def user_local_backup_key_path(primary_enc: Path) -> Path:
    """Backup chiave nella Library: ``<stem del .enc>_backup.key``."""
    return _user_library_conti_support_dir() / f"{primary_enc.stem}_backup.key"


def user_local_backup_light_path(primary_enc: Path) -> Path:
    """Backup sidecar light nella Library: ``<stem del file *_light.enc>_backup.enc``."""
    import light_enc_sidecar

    lp = light_enc_sidecar.light_enc_path_for_primary(primary_enc)
    return _user_library_conti_support_dir() / f"{lp.stem}_backup.enc"


def _discover_library_backup_enc_files() -> list[Path]:
    """File ``*_backup.enc`` in Library, più recente per primo."""
    d = _user_library_conti_support_dir()
    if not d.is_dir():
        return []
    out = [p for p in d.glob("*_backup.enc") if p.is_file()]
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def primary_enc_path_from_library_backup_filename(backup_path: Path) -> Path | None:
    """Da ``conti_utente_XXX_backup.enc`` → cartella dati ``conti_utente_XXX.enc``."""
    stem = backup_path.stem
    suf = "_backup"
    if not stem.endswith(suf):
        return None
    primary_stem = stem[: -len(suf)]
    if not primary_stem:
        return None
    return data_workspace.data_dir() / f"{primary_stem}.enc"


def restore_enc_from_library_backup_file(
    *,
    backup_path: Path,
    primary_target: Path,
    key_path: Path,
) -> dict:
    """Copia il backup nel percorso operativo (anche .key e sidecar light se presenti in Library) e carica il DB."""
    primary_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, primary_target)
    bk_key = user_local_backup_key_path(primary_target)
    if bk_key.is_file():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bk_key, key_path)
    import light_enc_sidecar as _lec

    lp = _lec.light_enc_path_for_primary(primary_target)
    lb = user_local_backup_light_path(primary_target)
    if lb.is_file():
        lp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lb, lp)
    db = load_encrypted_db(primary_target, key_path)
    if db is None:
        try:
            primary_target.unlink()
        except OSError:
            pass
        raise ValueError(
            "Decrittazione del backup non riuscita (chiave errata o file corrotto). "
            "Verifica che il file .key corrisponda a questo database."
        )
    return db


def _try_restore_database_from_library_at_startup(
    *,
    sync_ui_parent: tk.Misc | None,
) -> tuple[dict, Path] | None:
    """Se nella cartella dati non c’è un ``conti_utente_*.enc`` ma esiste un backup in Library, propone il ripristino."""
    if Fernet is None:
        return None
    if not data_workspace.default_key_file().is_file():
        return None
    if _discover_existing_user_db_candidates():
        return None
    backups = _discover_library_backup_enc_files()
    if not backups:
        return None
    chosen = backups[0]
    primary_target = primary_enc_path_from_library_backup_filename(chosen)
    if primary_target is None:
        return None
    parent = sync_ui_parent
    extra = ""
    if len(backups) > 1:
        extra = (
            f"\n\nAltri backup nella Library: {len(backups) - 1}. "
            "Verrà usato il più recente; da Opzioni puoi ripristinare un file specifico."
        )
    msg = (
        "Il database operativo non è stato trovato nella cartella dati "
        "(ad esempio Dropbox non ancora sincronizzato o file assente).\n\n"
        f"È disponibile un backup nella Library di questo utente:\n{chosen.resolve()}"
        f"{extra}\n\n"
        f"Ripristinare in:\n{primary_target.resolve()}\n\n"
        "Verrà rigenerato anche il file light accanto al database.\n\n"
        "Procedere?"
    )
    if not messagebox.askyesno("Ripristino da backup locale", msg, parent=parent):
        return None
    try:
        db = restore_enc_from_library_backup_file(
            backup_path=chosen,
            primary_target=primary_target,
            key_path=data_workspace.default_key_file(),
        )
    except ValueError as exc:
        messagebox.showerror("Ripristino non riuscito", str(exc), parent=parent)
        return None
    except OSError as exc:
        messagebox.showerror("Ripristino non riuscito", str(exc), parent=parent)
        return None
    periodiche.ensure_periodic_registrations(db)
    email_client.ensure_email_settings(db)
    security_auth.ensure_security(db)
    _finalize_startup_db_with_light_sidecar(db, primary_target)
    return db, primary_target


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
    backup_output_path: Path | None = None,
) -> None:
    """Salva il DB cifrato su percorso principale + backup.

    - `primary_output_path`: percorso scelto in UI (file principale operativo).
    - `backup_output_path`: se ``None``, copia nella Library dell’utente corrente tramite
      `user_local_backup_enc_path(primary_output_path)`.
    """
    resolved_backup = (
        backup_output_path
        if backup_output_path is not None
        else user_local_backup_enc_path(primary_output_path)
    )

    key = get_or_create_key(key_path)
    token = Fernet(key).encrypt(json.dumps(db, ensure_ascii=True, indent=2).encode("utf-8"))

    targets: list[Path] = [primary_output_path]
    try:
        if resolved_backup.resolve() != primary_output_path.resolve():
            targets.append(resolved_backup)
    except OSError:
        targets.append(resolved_backup)

    errors: list[str] = []
    for t in targets:
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(token)
        except Exception as exc:
            errors.append(f"{t}: {exc}")

    if errors:
        raise RuntimeError(
            "Salvataggio cifrato non completato su tutti i target:\n" + "\n".join(errors)
        )

    try:
        import light_enc_sidecar

        light_enc_sidecar.write_light_enc_sidecar(db, primary_output_path, key_path)
    except Exception:
        pass

    try:
        sup = _user_library_conti_support_dir()
        sup.mkdir(parents=True, exist_ok=True)
        if key_path.is_file():
            shutil.copy2(key_path, user_local_backup_key_path(primary_output_path))
        import light_enc_sidecar as _lec

        _lp = _lec.light_enc_path_for_primary(primary_output_path)
        if _lp.is_file():
            shutil.copy2(_lp, user_local_backup_light_path(primary_output_path))
    except Exception:
        pass


def _finalize_startup_db_with_light_sidecar(db: dict, primary_path: Path) -> None:
    """Fonde ``*_light.enc`` nel DB, salva se servito, rigenera il sidecar per l'app iOS."""
    try:
        import light_enc_sidecar

        n = light_enc_sidecar.merge_light_sidecar_at_startup(
            db, primary_path, data_workspace.default_key_file()
        )
        if n > 0:
            save_encrypted_db_dual(
                db,
                primary_path,
                data_workspace.default_key_file(),
            )
        light_enc_sidecar.write_light_enc_sidecar(db, primary_path, data_workspace.default_key_file())
    except Exception:
        pass


def reset_contabili_for_nuova_utenza(db: dict) -> None:
    """Azzera anni/registrazioni e metadati import; i dati tornano solo con Import legacy da Opzioni."""
    db["years"] = []
    for k in (
        "generated_at",
        "source",
        "schema_version",
        "exchange_rate_lira_eur",
        "years_imported",
        "years_skipped",
        "records_total",
        "records_active",
        "records_cancelled",
        "girata_checks",
        "light_saldi",
        "light_sidecar_generated_at",
        "light_sidecar_window_start",
    ):
        db.pop(k, None)
    security_auth.ensure_security(db)
    db["user_profile"]["plan_conti_wizard_pending"] = True


def _merge_preserved_app_sections_from_previous_db(imported_db: dict, previous_db: dict | None) -> None:
    """
    Il JSON prodotto da ImportLegacy contiene solo anni/registrazioni e metadati import.
    Ripristina dal DB precedente: profilo utente, posta, sicurezza, registrazioni periodiche.
    """
    if not previous_db:
        return
    for key in ("user_profile", "security_config", "email_settings"):
        if key not in previous_db:
            continue
        val = previous_db[key]
        if isinstance(val, dict):
            imported_db[key] = copy.deepcopy(val)
    imported_db["periodic_registrations"] = []


def load_encrypted_db(output_path: Path, key_path: Path) -> dict | None:
    if Fernet is None:
        return None
    if not output_path.exists() or not key_path.exists():
        return None
    key = key_path.read_bytes()
    token = output_path.read_bytes()
    raw = Fernet(key).decrypt(token)
    return json.loads(raw.decode("utf-8"))


def per_user_encrypted_db_path(email: str) -> Path:
    """File dati cifrato dedicato all'account registrato (email normalizzata)."""
    h = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:20]
    return data_workspace.data_dir() / f"conti_utente_{h}.enc"


def _discover_existing_user_db_candidates() -> list[Path]:
    """Candidati `conti_utente_*.enc` ordinati per mtime (più recente prima)."""
    data_dir = data_workspace.data_dir()
    if not data_dir.is_dir():
        return []
    out: list[Path] = []
    for p in data_dir.glob("conti_utente_*.enc"):
        if not p.is_file():
            continue
        out.append(p)
    out.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return out


def _try_load_first_valid_user_db(
    *,
    key_path: Path,
    sync_ui_parent: tk.Misc | None = None,
) -> tuple[dict, Path] | None:
    """Prova i ``conti_utente_*.enc`` nella cartella dati (più recente per primo)."""
    if not key_path.exists():
        return None
    cands = _discover_existing_user_db_candidates()
    if not cands:
        return None
    # L'attesa Dropbox su questi file è già stata fatta in ``load_database_at_startup``
    # (``_startup_paths_for_cloud_wait`` include gli stessi ``conti_utente_*.enc``).
    for p in cands:
        try:
            db = load_encrypted_db(p, key_path)
        except (InvalidToken, OSError, json.JSONDecodeError, ValueError):
            db = None
        if not db:
            continue
        periodiche.ensure_periodic_registrations(db)
        email_client.ensure_email_settings(db)
        security_auth.ensure_security(db)
        _finalize_startup_db_with_light_sidecar(db, p)
        return db, p
    return None


def _startup_paths_for_cloud_wait() -> list[Path]:
    """File da considerare per l’attesa «stabile» in Dropbox all’avvio."""
    out: list[Path] = [data_workspace.default_key_file()]
    out.extend(_discover_existing_user_db_candidates())
    boot = data_workspace.session_bootstrap_enc_path()
    if boot.exists():
        out.append(boot)
    return out


def _remove_bootstrap_light_artifacts() -> None:
    """Dopo lo spostamento del bootstrap, elimina il sidecar light residuo accanto al vecchio bootstrap."""
    try:
        import light_enc_sidecar
    except ImportError:
        return
    p = light_enc_sidecar.light_enc_path_for_primary(data_workspace.session_bootstrap_enc_path())
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass


def load_database_at_startup(*, sync_ui_parent: tk.Misc | None = None) -> tuple[dict, Path]:
    cloud_sync_wait.wait_for_paths_stable_if_cloud(
        _startup_paths_for_cloud_wait(),
        ui_parent=sync_ui_parent,
    )

    fallback = _try_load_first_valid_user_db(
        key_path=data_workspace.default_key_file(),
        sync_ui_parent=sync_ui_parent,
    )
    if fallback is not None:
        return fallback

    restored = _try_restore_database_from_library_at_startup(sync_ui_parent=sync_ui_parent)
    if restored is not None:
        return restored

    boot_enc = data_workspace.session_bootstrap_enc_path()
    key_f = data_workspace.default_key_file()
    if boot_enc.exists() and key_f.is_file():
        try:
            db = load_encrypted_db(boot_enc, key_f)
        except (InvalidToken, OSError, json.JSONDecodeError, ValueError):
            db = None
        if db:
            periodiche.ensure_periodic_registrations(db)
            email_client.ensure_email_settings(db)
            security_auth.ensure_security(db)
            _finalize_startup_db_with_light_sidecar(db, boot_enc)
            return db, boot_enc

    data_workspace.legacy_import_dir().mkdir(parents=True, exist_ok=True)
    out_json = data_workspace.default_legacy_json_output()
    print(
        "Primo avvio: import dell'archivio legacy in corso (può richiedere tempo; attendere).",
        file=sys.stderr,
    )
    run_import_legacy(DEFAULT_CDC_ROOT, out_json)
    db = json.loads(out_json.read_text(encoding="utf-8"))
    periodiche.ensure_periodic_registrations(db)
    email_client.ensure_email_settings(db)
    security_auth.ensure_security(db)
    # Nessun .enc per-utente finché non salvi (post wizard: percorso aggiornato al login).
    _finalize_startup_db_with_light_sidecar(db, boot_enc)
    return db, boot_enc


def migrate_data_path_after_login(
    db: dict,
    session: security_auth.AppSession,
    current_path: Path,
) -> Path:
    """Dopo login con account registrato, usa un file .enc dedicato per quell'email.

    L'accesso backdoor (Ctrl+Z, Ctrl+X) ha comunque l'email dal profilo: va applicata la stessa
    ricarica dal file per-utente corretto (come login normale), altrimenti restano in RAM dati
    caricati da un altro ``conti_utente_*.enc`` se più file sono nella cartella dati.
    """
    em = (session.user_email or "").strip().lower()
    if not em:
        return current_path
    target = per_user_encrypted_db_path(em)
    key_path = data_workspace.default_key_file()

    def _replace_db_from_enc(primary: Path) -> bool:
        """Sostituisce il contenuto di ``db`` con il JSON decrittato da ``primary`` (stesso riferimento dict)."""
        loaded = load_encrypted_db(primary, key_path)
        if not loaded:
            return False
        db.clear()
        db.update(loaded)
        periodiche.ensure_periodic_registrations(db)
        email_client.ensure_email_settings(db)
        security_auth.ensure_security(db)
        try:
            _finalize_startup_db_with_light_sidecar(db, primary)
        except Exception:
            pass
        return True

    if target.resolve() == current_path.resolve():
        return current_path
    # Se esiste già il file per questa email, non sovrascriverlo (es. caricamento da nome deprecato).
    # Importante: all'avvio può essere stato caricato un *altro* conti_utente_*.enc (mtime più recente);
    # qui si deve usare il DB dell'account con cui si è effettuato l'accesso, non solo il path.
    boot_path = data_workspace.session_bootstrap_enc_path()
    if target.exists() and current_path.resolve() != boot_path.resolve():
        if _replace_db_from_enc(target):
            return target
        return current_path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if current_path.resolve() == boot_path.resolve():
            if target.exists():
                if _replace_db_from_enc(target):
                    try:
                        current_path.unlink()
                    except OSError:
                        pass
                    _remove_bootstrap_light_artifacts()
                    return target
                return current_path
            shutil.move(str(current_path), str(target))
            _remove_bootstrap_light_artifacts()
            return target
        if not target.exists():
            try:
                shutil.copy2(current_path, target)
            except Exception:
                shutil.copyfile(current_path, target)
    except Exception:
        if not target.exists():
            shutil.copyfile(current_path, target)
    return target


def build_ui(
    db: dict,
    root: tk.Tk,
    session: security_auth.AppSession,
    path_holder: list[Path],
    key_path_holder: list[Path],
) -> None:
    # Riferimento mutabile: dopo import legacy da Opzioni, griglia e saldi devono usare il nuovo DB.
    db_holder: list[dict] = [db]
    session_holder: list[security_auth.AppSession] = [session]
    periodiche.ensure_periodic_registrations(db_holder[0])
    email_client.ensure_email_settings(db_holder[0])
    security_auth.ensure_security(db_holder[0])
    try:
        if migrate_dotazione_remove_from_plan_charts(db_holder[0]):
            save_encrypted_db_dual(db_holder[0], path_holder[0], key_path_holder[0])
    except Exception:
        pass

    try:
        root.configure(bg=MOVIMENTI_PAGE_BG)
    except Exception:
        pass

    def cur_db() -> dict:
        return db_holder[0]

    def refresh_window_title() -> None:
        root.title(window_title_for_session(cur_db(), session_holder[0]))

    def _page_banner_title() -> str:
        return window_title_for_session(cur_db(), session_holder[0])

    data_file_var = tk.StringVar(value=str(path_holder[0].resolve()))
    key_file_var = tk.StringVar(value=str(key_path_holder[0].resolve()))

    def _sync_path_holders_from_vars(*_args: object) -> None:
        try:
            path_holder[0] = Path(data_file_var.get()).expanduser().resolve()
            key_path_holder[0] = Path(key_file_var.get()).expanduser().resolve()
        except (OSError, ValueError, TypeError, RuntimeError):
            pass

    data_file_var.trace_add("write", _sync_path_holders_from_vars)
    key_file_var.trace_add("write", _sync_path_holders_from_vars)
    # La root resta nascosta durante tutta la costruzione dell'interfaccia: così non si vede
    # una finestra vuota in fullscreen (su macOS il -fullscreen nativo dà spesso un flash nero in alto).
    try:
        root.withdraw()
    except Exception:
        pass
    root.title(window_title_for_session(db_holder[0], session_holder[0]))

    main_nb_shell = tk.Frame(root, bg=MOVIMENTI_PAGE_BG)
    main_nb_shell.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
    cdc_tab_bar = tk.Frame(main_nb_shell, bg=MOVIMENTI_PAGE_BG)
    cdc_tab_bar.pack(fill=tk.X, pady=(0, 6))
    cdc_tab_bar.columnconfigure(0, weight=1)
    cdc_tab_bar.columnconfigure(2, weight=1)
    cdc_tab_btn_row = tk.Frame(cdc_tab_bar, bg=MOVIMENTI_PAGE_BG)
    cdc_tab_btn_row.grid(row=0, column=1, sticky="")
    cdc_content = tk.Frame(main_nb_shell, bg=MOVIMENTI_PAGE_BG)
    cdc_content.pack(fill=tk.BOTH, expand=True)
    cdc_content.rowconfigure(0, weight=1)
    cdc_content.columnconfigure(0, weight=1)

    _tipo_bg = security_auth.CDC_TIPO_TASTI_BTN_BG
    _tipo_act = security_auth.CDC_TIPO_TASTI_BTN_ACTIVE_BG
    _tipo_fg = security_auth.CDC_TIPO_TASTI_BTN_FG
    _TAB_BAR_FONT = ("TkDefaultFont", 13, "bold")
    _nb_style = ttk.Style(root)
    _nb_style.configure("MovCdc.TFrame", background=MOVIMENTI_PAGE_BG, fieldbackground=MOVIMENTI_PAGE_BG)
    _nb_style.configure(
        "MovCdc.TLabel",
        font=("TkDefaultFont", 12, "bold"),
        background=MOVIMENTI_PAGE_BG,
        foreground="#1a1a1a",
    )
    _nb_style.configure(
        "MovCdc.TEntry",
        font=("TkDefaultFont", 12, "bold"),
        fieldbackground=CDC_ENTRY_FIELD_BG,
        foreground="#111111",
    )
    _nb_style.configure(
        "MovCdc.TCombobox",
        font=("TkDefaultFont", 12, "bold"),
        fieldbackground=CDC_ENTRY_FIELD_BG,
    )

    movimenti_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    movimenti_frame.columnconfigure(0, weight=1)
    movimenti_frame.rowconfigure(0, weight=1)
    movimenti_body = ttk.Frame(movimenti_frame, style="MovCdc.TFrame")
    movimenti_body.grid(row=0, column=0, sticky="nsew")
    nuovi_dati_frame = tk.Frame(cdc_content, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    verifica_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    statistiche_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    budget_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    opzioni_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    plan_conti_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")
    aiuto_frame = ttk.Frame(cdc_content, padding=8, style="MovCdc.TFrame")

    _pages_all: list[tk.Widget] = [
        movimenti_frame,
        nuovi_dati_frame,
        verifica_frame,
        statistiche_frame,
        budget_frame,
        opzioni_frame,
        plan_conti_frame,
        aiuto_frame,
    ]
    for _pf in _pages_all:
        if _pf is nuovi_dati_frame:
            _pf.grid(row=0, column=0, sticky="nsew", in_=cdc_content, padx=8, pady=8)
        else:
            _pf.grid(row=0, column=0, sticky="nsew", in_=cdc_content)
        _pf.grid_remove()

    _cdc_current: list[tk.Widget | None] = [None]
    _plan_conti_visible: list[bool] = [False]
    _frame_to_tab_label: dict[tk.Widget, tk.Label] = {}

    def _cdc_ordered_tabs() -> list[tk.Widget]:
        o: list[tk.Widget] = [
            movimenti_frame,
            nuovi_dati_frame,
            verifica_frame,
            statistiche_frame,
            budget_frame,
            opzioni_frame,
        ]
        if _plan_conti_visible[0]:
            o.append(plan_conti_frame)
        o.append(aiuto_frame)
        return o

    def _cdc_sync_tab_style() -> None:
        cur = _cdc_current[0]
        for fr, lbl in _frame_to_tab_label.items():
            if fr is cur:
                lbl.configure(bg=_tipo_act, relief=tk.SUNKEN, bd=2, highlightthickness=0)
            else:
                lbl.configure(bg=_tipo_bg, relief=tk.RAISED, bd=1, highlightthickness=0)

    def _cdc_forget_plan_conti_bar() -> None:
        if not _plan_conti_visible[0]:
            return
        _plan_conti_visible[0] = False
        try:
            lbl_plan_conti.pack_forget()
        except tk.TclError:
            pass

    def _cdc_on_tab_side_effects(_new: tk.Widget) -> None:
        if _new is movimenti_frame:
            try:
                refresh_movement_filter_button_styles()
                refresh_date_controls_visibility()
            except NameError:
                pass
            if _movements_dirty[0]:
                _movements_dirty[0] = False
                try:
                    populate_movements_trees()
                    refresh_balance_footer()
                except NameError:
                    pass

    def _cdc_select(f: tk.Widget) -> None:
        for pf in _pages_all:
            try:
                pf.grid_remove()
            except tk.TclError:
                pass
        if f is nuovi_dati_frame:
            f.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        else:
            f.grid(row=0, column=0, sticky="nsew")
        _cdc_current[0] = f
        _cdc_sync_tab_style()
        if f is not plan_conti_frame and _plan_conti_visible[0]:
            _cdc_forget_plan_conti_bar()
        _cdc_on_tab_side_effects(f)
        try:
            _notebook_virtuale_tab_guard()
        except NameError:
            pass

    def _mk_cdc_tab(title: str, frame: tk.Widget) -> tk.Label:
        lbl = tk.Label(
            cdc_tab_btn_row,
            text=title,
            font=_TAB_BAR_FONT,
            bg=_tipo_bg,
            fg=_tipo_fg,
            padx=10,
            pady=5,
            cursor="hand2",
            relief=tk.RAISED,
            bd=1,
            highlightthickness=0,
        )

        def _pick(_e: tk.Event) -> None:
            _cdc_select(frame)

        def _ent(_e: tk.Event) -> None:
            if _cdc_current[0] is not frame:
                lbl.configure(bg=_tipo_act)

        def _lev(_e: tk.Event) -> None:
            _cdc_sync_tab_style()

        lbl.bind("<Button-1>", _pick)
        lbl.bind("<Enter>", _ent)
        lbl.bind("<Leave>", _lev)
        _frame_to_tab_label[frame] = lbl
        return lbl

    _mk_cdc_tab("Movimenti e correzioni", movimenti_frame).pack(side=tk.LEFT, padx=(0, 6))
    _mk_cdc_tab("Nuove registrazioni", nuovi_dati_frame).pack(side=tk.LEFT, padx=(0, 6))
    _mk_cdc_tab("Verifica", verifica_frame).pack(side=tk.LEFT, padx=(0, 6))
    _mk_cdc_tab("Statistiche", statistiche_frame).pack(side=tk.LEFT, padx=(0, 6))
    _mk_cdc_tab("Budget", budget_frame).pack(side=tk.LEFT, padx=(0, 6))
    _mk_cdc_tab("Opzioni", opzioni_frame).pack(side=tk.LEFT, padx=(0, 6))
    lbl_plan_conti = _mk_cdc_tab("Categorie e conti", plan_conti_frame)
    lbl_aiuto = _mk_cdc_tab("Aiuto", aiuto_frame)
    lbl_aiuto.pack(side=tk.LEFT, padx=(0, 6))

    class _CdcNotebookShim:
        def select(self, item: int | tk.Widget | None = None) -> tk.Widget | None:
            if item is None:
                return _cdc_current[0]
            if isinstance(item, int):
                item = _cdc_ordered_tabs()[item]
            _cdc_select(item)
            return _cdc_current[0]

        def index(self, widget: tk.Widget) -> int:
            try:
                return _cdc_ordered_tabs().index(widget)
            except ValueError:
                raise tk.TclError("tab id not found")

        def forget(self, widget: tk.Widget) -> None:
            if widget is not plan_conti_frame:
                raise tk.TclError("forget only supported for Categorie e conti")
            _cdc_forget_plan_conti_bar()
            try:
                plan_conti_frame.grid_remove()
            except tk.TclError:
                pass

        def insert(self, _pos: int, widget: tk.Widget, text: str | None = None) -> None:
            if widget is not plan_conti_frame:
                raise tk.TclError("insert only supported for Categorie e conti")
            _ensure_plan_conti_tab()

        def add(self, widget: tk.Widget, text: str | None = None) -> None:
            if widget is not plan_conti_frame:
                raise tk.TclError("add only supported for Categorie e conti")
            _ensure_plan_conti_tab()

    def _ensure_plan_conti_tab() -> None:
        """Mostra il tasto «Categorie e conti» (come il vecchio reinserimento nel Notebook)."""
        if _plan_conti_visible[0]:
            return
        _plan_conti_visible[0] = True
        lbl_plan_conti.pack(side=tk.LEFT, padx=(0, 6), before=lbl_aiuto)
        _cdc_sync_tab_style()

    notebook = _CdcNotebookShim()

    movimenti_frame.grid(row=0, column=0, sticky="nsew")
    _cdc_current[0] = movimenti_frame
    _cdc_sync_tab_style()

    pack_centered_page_title(
        movimenti_body,
        title=_page_banner_title(),
        banner_style="MovCdc.TFrame",
        title_bg=MOVIMENTI_PAGE_BG,
    )

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
    amount_filter_sign_var = tk.StringVar(value="-")
    text_amount_preview_var = tk.StringVar(value="-")
    text_note_preview_var = tk.StringVar(value="")
    text_category_applied_var = tk.StringVar(value="")
    text_account_applied_var = tk.StringVar(value="")
    text_cheque_applied_var = tk.StringVar(value="")
    text_amount_applied_var = tk.StringVar(value="")
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

    filters_row = ttk.Frame(movimenti_body, style="MovCdc.TFrame")
    filters_row.pack(fill=tk.X, pady=(0, 2))

    filters_search_row = ttk.Frame(movimenti_body, style="MovCdc.TFrame")
    filters_search_row.pack(fill=tk.X, pady=(0, 4))

    # Riga controlli per Ricerca per registrazione (visibile solo in quella modalità)
    reg_controls_row = ttk.Frame(filters_search_row, style="MovCdc.TFrame")
    reg_controls_row.pack(side=tk.LEFT, anchor=tk.W)
    reg_controls_row.pack_forget()

    filters_text_row = ttk.Frame(movimenti_body, style="MovCdc.TFrame")
    filters_text_row.pack(fill=tk.X, pady=(0, 6))

    # Riga filtri testuali (visibile solo in Ricerca per data)
    filters_text_inner = ttk.Frame(filters_text_row, style="MovCdc.TFrame")
    filters_text_inner.pack(fill=tk.X, anchor=tk.W)

    # Zona filtri: testo in bold (etichette, entry, combobox, pulsanti).
    filter_ui_font = ("TkDefaultFont", 12, "bold")
    ttk.Style(root).configure("Filters.TLabel", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TEntry", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TCombobox", font=filter_ui_font)
    ttk.Style(root).configure("Filters.TButton", font=filter_ui_font)
    _mov_style = ttk.Style(root)
    _mov_style.configure("MovCdc.TLabel", font=filter_ui_font, background=MOVIMENTI_PAGE_BG, foreground="#1a1a1a")
    _mov_style.configure(
        "MovCdc.TEntry", font=filter_ui_font, fieldbackground=CDC_ENTRY_FIELD_BG, foreground="#111111"
    )
    _mov_style.configure("MovCdc.TCombobox", font=filter_ui_font, fieldbackground=CDC_ENTRY_FIELD_BG)

    _ALL_CATEGORIES_LABEL = "Tutte"
    _ALL_ACCOUNTS_LABEL = "Tutti"

    ttk.Label(filters_text_inner, text="Categoria", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    category_entry = ttk.Combobox(
        filters_text_inner,
        textvariable=text_category_preview_var,
        state="readonly",
        width=20,
        values=("",),
        style="MovCdc.TCombobox",
    )
    category_entry.pack(side=tk.LEFT, padx=(0, 8))

    ttk.Label(filters_text_inner, text="Conto", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    account_entry = ttk.Combobox(
        filters_text_inner,
        textvariable=text_account_preview_var,
        state="readonly",
        width=16,
        values=("",),
        style="MovCdc.TCombobox",
    )
    account_entry.pack(side=tk.LEFT, padx=(0, 8))

    ttk.Label(filters_text_inner, text="Importo", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    amount_filter_row = ttk.Frame(filters_text_inner)
    amount_filter_entry = ttk.Entry(
        amount_filter_row,
        textvariable=text_amount_preview_var,
        width=14,
        style="MovCdc.TEntry",
    )
    amount_filter_entry.pack(side=tk.LEFT)
    btn_amt_f_plus = tk.Label(
        amount_filter_row,
        text="+",
        cursor="hand2",
        font=filter_ui_font,
        padx=6,
        pady=2,
        bg="#e0f2f1",
        relief=tk.RAISED,
        bd=1,
    )
    btn_amt_f_minus = tk.Label(
        amount_filter_row,
        text="-",
        cursor="hand2",
        font=filter_ui_font,
        padx=6,
        pady=2,
        bg="#ffebee",
        relief=tk.RAISED,
        bd=1,
    )
    btn_amt_f_plus.pack(side=tk.LEFT, padx=(6, 2))
    btn_amt_f_minus.pack(side=tk.LEFT, padx=(2, 0))
    amount_filter_row.pack(side=tk.LEFT, padx=(0, 8))

    def _apply_amount_filter_sign(sign: str) -> None:
        amount_filter_sign_var.set(sign)
        raw = (text_amount_preview_var.get() or "").strip().replace(" ", "")
        if not raw or raw in ("+", "-"):
            text_amount_preview_var.set("-" if sign == "-" else "+")
            return
        if raw.startswith(("+", "-")):
            raw = raw[1:]
        text_amount_preview_var.set(("-" if sign == "-" else "+") + raw)

    def _format_movement_amount_filter_entry(_e: tk.Event | None = None) -> None:
        raw = (text_amount_preview_var.get() or "").strip()
        if not raw or raw in ("+", "-"):
            text_amount_preview_var.set("-" if amount_filter_sign_var.get() == "-" else "+")
            return
        try:
            amt = normalize_euro_input(raw)
            if amount_filter_sign_var.get() == "-":
                amt = -abs(amt)
            else:
                amt = abs(amt)
            txt = format_euro_it(abs(amt))
            text_amount_preview_var.set(("-" if amt < 0 else "+") + txt)
        except Exception:
            pass

    btn_amt_f_plus.bind("<Button-1>", lambda _e: _apply_amount_filter_sign("+"))
    btn_amt_f_minus.bind("<Button-1>", lambda _e: _apply_amount_filter_sign("-"))
    amount_filter_entry.bind("<FocusOut>", _format_movement_amount_filter_entry)
    bind_euro_amount_entry_validation(amount_filter_entry, text_amount_preview_var)

    ttk.Label(filters_text_inner, text="Assegno", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    cheque_entry = ttk.Entry(
        filters_text_inner,
        textvariable=text_cheque_preview_var,
        width=10,
        style="MovCdc.TEntry",
    )
    cheque_entry.pack(side=tk.LEFT, padx=(0, 8))

    ttk.Label(filters_text_inner, text="Nota", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    note_entry = ttk.Entry(
        filters_text_inner,
        textvariable=text_note_preview_var,
        width=28,
        style="MovCdc.TEntry",
    )
    bind_entry_first_char_uppercase(text_note_preview_var, note_entry)

    # Nota, Cerca e Pulisci filtri: pack differito dopo definizione di apply_movement_search / clear.

    # ---- UI Ricerca per registrazione (preset + range reg + conto) ----
    reg_controls_inner = ttk.Frame(reg_controls_row, style="MovCdc.TFrame")
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

    ttk.Label(reg_controls_inner, text="Dalla reg. #", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_from_entry = ttk.Entry(reg_controls_inner, textvariable=reg_from_preview_var, width=8, style="MovCdc.TEntry")
    reg_from_entry.pack(side=tk.LEFT, padx=(0, 14))

    ttk.Label(reg_controls_inner, text="Alla reg. #", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_to_entry = ttk.Entry(reg_controls_inner, textvariable=reg_to_preview_var, width=8, style="MovCdc.TEntry")
    reg_to_entry.pack(side=tk.LEFT, padx=(0, 18))

    ttk.Label(reg_controls_inner, text="Conto", style="MovCdc.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    reg_account_entry = ttk.Combobox(
        reg_controls_inner,
        textvariable=text_account_preview_var,
        state="readonly",
        width=16,
        values=(_ALL_ACCOUNTS_LABEL,),
        style="MovCdc.TCombobox",
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
        records = [r for y in d.get("years", []) for r in y.get("records", [])]

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

    records_frame = ttk.Frame(movimenti_body, padding=8, style="MovCdc.TFrame")
    records_frame.pack(fill=tk.BOTH, expand=True)

    search_title_var = tk.StringVar(value="")
    _PRINT_RICERCA_RED = "#c62828"
    _PRINT_RICERCA_RED_ACTIVE = "#8e0000"
    search_title_row = tk.Frame(records_frame, bg=MOVIMENTI_PAGE_BG)
    search_title_label = tk.Label(
        search_title_row,
        textvariable=search_title_var,
        font=("TkDefaultFont", 12, "bold"),
        fg="#1a1a1a",
        bg=MOVIMENTI_PAGE_BG,
        anchor="w",
        justify="left",
    )
    search_title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

    no_results_label = tk.Label(
        records_frame,
        text="Nessuna registrazione con questi filtri",
        font=("TkDefaultFont", 16, "bold"),
        fg="#444444",
        bg=MOVIMENTI_PAGE_BG,
    )

    mov_style = ttk.Style(root)
    mov_style.configure(
        "MovGrid.Treeview",
        borderwidth=1,
        relief="solid",
        rowheight=22,
        background=CDC_GRID_STRIPE1_BG,
        fieldbackground=CDC_GRID_STRIPE1_BG,
        font=("TkDefaultFont", 11, "bold"),
    )
    mov_style.configure(
        "MovGridAmount.Treeview",
        borderwidth=1,
        relief="solid",
        rowheight=22,
        background=CDC_GRID_STRIPE1_BG,
        fieldbackground=CDC_GRID_STRIPE1_BG,
        font=("TkDefaultFont", 12, "bold"),
    )
    mov_style.configure(
        "MovGrid.Treeview.Heading",
        borderwidth=1,
        relief="flat",
        background=CDC_GRID_HEADING_BG,
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

    mov_tree.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    mov_tree.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

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
        amt = (text_amount_applied_var.get() or "").strip()
        if mode == "date" and amt:
            parts.append(f"per l'importo {amt} EUR")
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
    amt_tree.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    amt_tree.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

    note_tree = ttk.Treeview(
        records_frame,
        columns=("note",),
        show="tree",
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    note_tree.heading("note", text="Nota", anchor="w")
    note_tree.column("note", width=280, anchor="w", stretch=True, minwidth=120)
    note_tree.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    note_tree.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

    mov_tree.column("#0", width=0, minwidth=0, stretch=False)
    amt_tree.column("#0", width=0, minwidth=0, stretch=False)
    note_tree.column("#0", width=0, minwidth=0, stretch=False)

    # Intestazioni custom (su macOS ttk può ignorare l'allineamento delle headings).
    header_bg = CDC_GRID_HEADING_BG
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
    correzione_row = tk.Frame(records_frame, bg=MOVIMENTI_PAGE_BG)
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
        bg=MOVIMENTI_PAGE_BG,
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
        cutoff_year = date.today().year - 1
        msg_text = f"Registrazione non modificabile: data precedente al 01/01/{cutoff_year}."

        if sel:
            sk = sel[0]
            pair = find_record_year_and_ref(cur_db(), sk)
            if pair:
                _yd, rec = pair
                if record_has_account_verification_flags(rec):
                    has_verifica_flags = True
                forza_ok_recency = record_is_within_forza_verifica_recency(rec)
                if not record_is_within_recent_mod_delete_window(rec):
                    want_msg = True
                else:
                    want_modifica = True
                    if record_contains_any_asterisk(rec):
                        want_msg = True
                        msg_text = "Registrazione verificata non cancellabile."

        want_forza = (
            has_verifica_flags
            and want_modifica
            and forza_ok_recency
            and correzione_forza_revealed[0]
        )
        want_elimina = want_modifica and (not want_forza)
        if sel:
            pair = find_record_year_and_ref(cur_db(), sel[0])
            if pair:
                _yd, rec = pair
                if record_contains_any_asterisk(rec):
                    want_elimina = False

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
            code = str(c.get("code", str(i)))
            if code == "0":
                continue
            if is_hidden_dotazione_category_name(str(c.get("name", ""))):
                continue
            disp = category_display_name(c.get("name", ""))
            choices.append((disp, code))
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
        ent_edit_amt = ttk.Entry(frm, textvariable=v, width=18)
        ent_edit_amt.grid(row=0, column=1, sticky="w", padx=(8, 0))
        if not use_lire:
            bind_euro_amount_entry_validation(ent_edit_amt, v)

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
        if not record_is_within_recent_mod_delete_window(rec):
            return None
        return (sel[0], rec)

    def _record_has_virtuale(rec: dict) -> bool:
        p = str(rec.get("account_primary_name") or rec.get("account_primary_code") or "")
        s = str(rec.get("account_secondary_name") or rec.get("account_secondary_code") or "")
        return _is_virtuale_account(p) or _is_virtuale_account(s)

    def on_modifica_reg_click(event: tk.Event) -> None:
        cur = _correzione_current_key_and_rec()
        if not cur:
            return
        _key0, rec0 = cur
        is_virtuale_rec = _record_has_virtuale(rec0)
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

        if is_virtuale_rec:
            m.add_command(label="Assegno", command=lambda: run_edit(open_edit_cheque))
            m.add_command(label="Nota", command=lambda: run_edit(open_edit_note))
        else:
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
        all_records.sort(key=record_merge_sort_key)
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
            uh_e = html_module.escape(print_user_header_text(d, session_holder[0]))
            html_doc = f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8"/><title>Promemoria verifica</title>
<style>
body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color:#1a1a1a; padding:8mm; }}
p {{ margin:0 0 3mm 0; }}
.user-hdr {{ text-align:center; font-weight:700; font-size:12pt; margin:0 0 4mm 0; }}
table {{ width:100%; border-collapse:collapse; font-size:10pt; }}
th, td {{ border:1px solid #999; padding:4px 6px; vertical-align:top; }}
th {{ background:#efefef; text-align:left; }}
</style></head><body>
<p class="user-hdr">{uh_e}</p>
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
        if _record_has_virtuale(rec):
            messagebox.showwarning(
                "Eliminazione non ammessa",
                "Le registrazioni che coinvolgono il conto VIRTUALE non sono eliminabili.",
            )
            return
        if not record_is_within_recent_mod_delete_window(rec):
            messagebox.showwarning(
                "Elimina registrazione",
                "Operazione non consentita: puoi eliminare solo registrazioni dall'anno precedente in poi.",
            )
            return
        if record_contains_any_asterisk(rec):
            messagebox.showwarning(
                "Elimina registrazione",
                "Operazione non consentita: la registrazione contiene almeno un asterisco.",
            )
            return
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
    _movements_dirty: list[bool] = [False]

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
        q_note = text_note_applied_var.get().strip().casefold()
        q_amt_raw = (text_amount_applied_var.get() or "").strip()
        q_amt: Decimal | None = None
        if q_amt_raw:
            try:
                q_amt = normalize_euro_input(q_amt_raw)
            except Exception:
                q_amt = None
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
            if filter_order_applied_var.get() == "date":
                if q_cat and q_cat != (category_name or "").lower():
                    continue
                if q_acc and q_acc not in (account_1_name or "").lower() and q_acc not in (account_2_name or "").lower():
                    continue
                if q_amt is not None:
                    try:
                        if to_decimal(r.get("amount_eur", "0")) != q_amt:
                            continue
                    except Exception:
                        continue
                if q_chq and q_chq not in str(r.get("cheque") or "").lower():
                    continue
                if q_note and q_note not in str(r.get("note") or "").casefold():
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
                if q_note and q_note not in str(r.get("note") or "").casefold():
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
        records.sort(key=record_merge_sort_key)
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

    # Toggle filtri: stessa palette «tipo tasti» dei tab (esclusi Pulisci filtri / Cerca).
    _FILTER_BG_OFF = security_auth.CDC_TIPO_TASTI_BTN_BG
    _FILTER_BG_ON = security_auth.CDC_TIPO_TASTI_BTN_ACTIVE_BG
    _FILTER_FG = security_auth.CDC_TIPO_TASTI_BTN_FG

    def _set_filter_toggle_style(w: tk.Label, selected: bool) -> None:
        if selected:
            w.configure(
                bg=_FILTER_BG_ON,
                fg=_FILTER_FG,
                relief=tk.SUNKEN,
                bd=2,
                highlightthickness=0,
            )
        else:
            w.configure(
                bg=_FILTER_BG_OFF,
                fg=_FILTER_FG,
                relief=tk.RAISED,
                bd=1,
                highlightthickness=0,
            )

    g1 = ttk.Frame(filters_row, style="MovCdc.TFrame")
    g1.pack(side=tk.LEFT, anchor=tk.W)
    btn_order_date = tk.Label(
        g1,
        text="Ricerca per data",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
    )
    btn_order_reg = tk.Label(
        g1,
        text="Ricerca per registrazione",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
    )
    btn_order_date.bind("<Button-1>", lambda _e: pick_order("date"))
    btn_order_reg.bind("<Button-1>", lambda _e: pick_order("registration"))
    btn_order_date.pack(side=tk.LEFT, padx=(0, 8))
    btn_order_reg.pack(side=tk.LEFT)

    g2 = ttk.Frame(filters_row, style="MovCdc.TFrame")
    g2.pack(side=tk.LEFT, padx=(14, 0), anchor=tk.W)
    btn_future_include = tk.Label(
        g2,
        text="Date future comprese",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
    )
    btn_future_exclude = tk.Label(
        g2,
        text="Date future escluse",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
    )
    btn_future_include.bind("<Button-1>", lambda _e: pick_future("include"))
    btn_future_exclude.bind("<Button-1>", lambda _e: pick_future("exclude"))
    btn_future_include.pack(side=tk.LEFT, padx=(0, 8))
    btn_future_exclude.pack(side=tk.LEFT)

    g3 = ttk.Frame(filters_row, style="MovCdc.TFrame")
    g3.pack(side=tk.LEFT, padx=(14, 0), anchor=tk.W)
    btn_dir_backward = tk.Label(
        g3,
        text="All'indietro, dalla più recente",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
    )
    btn_dir_forward = tk.Label(
        g3,
        text="In avanti, dalla più lontana",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=6,
        pady=4,
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
        amt_preview_raw = (text_amount_preview_var.get() or "").strip()
        amt_preview = ""
        if amt_preview_raw and amt_preview_raw not in ("+", "-"):
            try:
                amt_chk = normalize_euro_input(amt_preview_raw)
                if amount_filter_sign_var.get() == "-":
                    amt_chk = -abs(amt_chk)
                else:
                    amt_chk = abs(amt_chk)
                amt_preview = format_euro_it(amt_chk)
                text_amount_preview_var.set(amt_preview)
            except Exception:
                messagebox.showerror(
                    "Importo non valido",
                    "Inserisci un importo in euro valido (es. 1.234,56).",
                )
                return
        elif amt_preview_raw in ("+", "-"):
            text_amount_preview_var.set("-" if amount_filter_sign_var.get() == "-" else "+")
        rp_preview = reg_preset_preview_var.get()
        rf_preview = reg_from_preview_var.get()
        rt_preview = reg_to_preview_var.get()

        if o == "registration":
            # Validazione limiti registrazione coerenti con scope (preset + include/exclude).
            scope_from, scope_to = _scope_dates_for_registration(rp_preview)
            ddb = cur_db()
            recs = [r for y in ddb["years"] for r in y["records"]]
            recs.sort(key=record_merge_sort_key)
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
            and amt_preview == (text_amount_applied_var.get() or "").strip()
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
        text_amount_applied_var.set(amt_preview)
        text_note_applied_var.set(note_preview)
        populate_movements_trees()

    # Enter nei filtri testuali = esegui Cerca
    for _w in (category_entry, account_entry, amount_filter_entry, cheque_entry, note_entry):
        bind_return_and_kp_enter(_w, apply_movement_search)

    def clear_movement_text_filters() -> None:
        # Ripristino completo dei filtri alla condizione di default.
        nonlocal date_custom_manual_override
        filter_order_preview_var.set("date")
        filter_future_preview_var.set("include")
        filter_direction_preview_var.set("backward")
        date_preset_preview_var.set("last_12")
        reg_preset_preview_var.set("last_12")
        date_custom_manual_override = False
        try:
            refresh_movement_filter_button_styles()
            refresh_date_preview_from_modes()
            refresh_date_controls_visibility()
            refresh_reg_preset_button_styles()
            refresh_registration_scope_and_controls()
        except Exception:
            pass
        try:
            refresh_date_preset_button_styles()
        except Exception:
            pass
        text_category_preview_var.set(_ALL_CATEGORIES_LABEL)
        text_account_preview_var.set(_ALL_ACCOUNTS_LABEL)
        amount_filter_sign_var.set("-")
        text_amount_preview_var.set("-")
        text_cheque_preview_var.set("")
        text_note_preview_var.set("")
        apply_movement_search()
        try:
            category_entry.focus_set()
        except Exception:
            pass

    _CERCA_GREEN = "#2e7d32"
    _CERCA_GREEN_ACTIVE = "#1b5e20"
    _PULISCI_BLUE = "#1565c0"
    _PULISCI_BLUE_ACTIVE = "#0d47a1"
    lbl_pulisci_filtri = tk.Label(
        filters_row,
        text="Pulisci filtri",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        width=12,
        padx=10,
        pady=5,
        bg=_PULISCI_BLUE,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    lbl_pulisci_filtri.pack(side=tk.RIGHT, padx=(8, 0))

    def _pulisci_enter(_e: tk.Event) -> None:
        lbl_pulisci_filtri.configure(bg=_PULISCI_BLUE_ACTIVE)

    def _pulisci_leave(_e: tk.Event) -> None:
        lbl_pulisci_filtri.configure(bg=_PULISCI_BLUE)

    lbl_pulisci_filtri.bind("<Enter>", _pulisci_enter)
    lbl_pulisci_filtri.bind("<Leave>", _pulisci_leave)
    lbl_pulisci_filtri.bind("<Button-1>", lambda _e: clear_movement_text_filters())

    filters_search_actions = ttk.Frame(filters_search_row, style="MovCdc.TFrame")
    filters_search_spacer = tk.Frame(
        filters_search_row, highlightthickness=0, borderwidth=0, bg=MOVIMENTI_PAGE_BG
    )
    cerca_wrap = tk.Frame(filters_search_actions, highlightthickness=0, bg=MOVIMENTI_PAGE_BG)
    lbl_cerca = tk.Label(
        cerca_wrap,
        text="Cerca",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        width=12,
        padx=10,
        pady=5,
        bg=_CERCA_GREEN,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    lbl_cerca.bind("<Button-1>", apply_movement_search)
    def _cerca_enter(_e: tk.Event) -> None:
        lbl_cerca.configure(bg=_CERCA_GREEN_ACTIVE)

    def _cerca_leave(_e: tk.Event) -> None:
        lbl_cerca.configure(bg=_CERCA_GREEN)

    lbl_cerca.bind("<Enter>", _cerca_enter)
    lbl_cerca.bind("<Leave>", _cerca_leave)

    note_entry.pack(side=tk.LEFT, padx=(0, 8))
    cerca_wrap.pack(side=tk.RIGHT, padx=(0, 0))
    lbl_cerca.pack(side=tk.TOP, fill=tk.X)

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

    def _preset_rolling_start_date(months: int, *, allowed_min: date, allowed_max: date) -> date:
        """Inizio intervallo «Ultimi N mesi»: con future escluse ancorato a oggi (= allowed_max); con future comprese ancorato a oggi ma il massimo resta allowed_max (es. ultima data futura nel dataset)."""
        anchor = allowed_max if filter_future_preview_var.get() == "exclude" else date.today()
        start = _add_months(anchor, -months)
        start = max(allowed_min, start)
        if start > allowed_max:
            start = allowed_max
        return start

    def _compute_preset_range(preset_id: str) -> tuple[date, date]:
        mn, mx = _dataset_minmax_safe()
        allowed_min = mn
        allowed_max = date.today() if filter_future_preview_var.get() == "exclude" else mx

        if preset_id == "all_time":
            return allowed_min, allowed_max

        # Tutti gli intervalli «Ultimi N mesi» (1…12) usano la stessa regola: con future
        # comprese l’inizio è oggi − N mesi; con future escluse è allowed_max (= oggi) − N mesi.
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
        start = _preset_rolling_start_date(months, allowed_min=allowed_min, allowed_max=allowed_max)
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
                start_12 = _preset_rolling_start_date(12, allowed_min=min_allowed, allowed_max=max_allowed)
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
        # last_12 (stessa ancora «ultimi 12 mesi» dei preset data: oggi se future comprese)
        start_12 = _preset_rolling_start_date(12, allowed_min=min_allowed, allowed_max=max_allowed)
        return start_12.isoformat(), max_allowed.isoformat()

    def refresh_registration_scope_and_controls() -> None:
        """Preimposta reg_from/reg_to e aggiorna dropdown conto in base a preset + include/exclude + direzione."""
        if filter_order_preview_var.get() != "registration":
            return
        scope_from, scope_to = _scope_dates_for_registration(reg_preset_preview_var.get())
        d = cur_db()
        records = [r for y in d["years"] for r in y["records"]]
        records.sort(key=record_merge_sort_key)
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
        # Nascosto finché non è calcolata la geometry sotto i campi data (evita flash in posizione sbagliata).
        try:
            top.withdraw()
        except Exception:
            pass
        # Non rendiamo modale (grab): serve poter cliccare di nuovo sulla casella data
        # per chiudere il popup e passare alla digitazione manuale.
        try:
            top.grab_release()
        except Exception:
            pass
        top.protocol("WM_DELETE_WINDOW", lambda: top.destroy())

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
                    bg=CDC_CAL_CELL_BG,
                    relief=tk.RAISED,
                    bd=1,
                    highlightthickness=0,
                )
                if in_bounds:
                    cell.configure(cursor="hand2")
                    cell.bind("<Button-1>", lambda _e, dd=dsel: on_pick(dd))
                else:
                    cell.configure(fg="#999999", bg=CDC_CAL_DISABLED_BG)

                if dsel == selected_date:
                    cell.configure(
                        bg=CDC_CAL_SELECTED_BG,
                        relief=tk.SUNKEN,
                        bd=2,
                        highlightthickness=1,
                        highlightbackground="#5fa8c4",
                        highlightcolor="#5fa8c4",
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

        def _place_calendar_below_anchor() -> None:
            """Apre il popup subito sotto il campo data (o sopra se non c’è spazio in basso)."""
            try:
                anchor = date_from_entry if which == "from" else date_to_entry
                top.update_idletasks()
                root.update_idletasks()
                ex = int(anchor.winfo_rootx())
                ey_top = int(anchor.winfo_rooty())
                ey_bottom = int(ey_top + anchor.winfo_height())
                w = max(1, int(top.winfo_reqwidth()))
                h = max(1, int(top.winfo_reqheight()))
                scr_w = int(top.winfo_screenwidth())
                scr_h = int(top.winfo_screenheight())
                gap = 4
                x = ex
                y = ey_bottom + gap
                if x + w > scr_w - 10:
                    x = max(10, scr_w - w - 10)
                if y + h > scr_h - 10:
                    y = ey_top - h - gap
                if y < 10:
                    y = 10
                top.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass

        _place_calendar_below_anchor()
        try:
            top.deiconify()
            top.lift()
        except Exception:
            pass
        try:
            top.focus_force()
        except Exception:
            pass
        return top

    def refresh_date_controls_visibility() -> None:
        mode = filter_order_preview_var.get()
        if mode == "date":
            reg_controls_row.pack_forget()
            date_controls_left.pack(side=tk.LEFT, anchor=tk.W)
            # Re-pack before grid area so it doesn't end up after it.
            filters_text_row.pack(fill=tk.X, pady=(0, 6), before=records_frame)
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
        try:
            _sync_filters_search_spacer_width()
        except Exception:
            pass

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
    bind_return_and_kp_enter(reg_from_entry, apply_movement_search)
    bind_return_and_kp_enter(reg_to_entry, apply_movement_search)

    # Seconda riga: controlli data/reg. a sinistra, tasto Cerca allineato a destra.
    date_controls_left = ttk.Frame(filters_search_row, style="MovCdc.TFrame")

    def _sync_filters_search_spacer_width(_event: object | None = None) -> None:
        try:
            movimenti_frame.update_idletasks()
            row = filters_search_row
            pad = 8
            target_x = (btn_dir_forward.winfo_rootx() + btn_dir_forward.winfo_width()) - row.winfo_rootx() + pad
            mode = filter_order_preview_var.get()
            main = date_controls_left if mode == "date" else reg_controls_row
            if not main.winfo_ismapped():
                filters_search_spacer.configure(width=1, height=1)
                filters_search_spacer.pack_propagate(False)
                return
            main_end = main.winfo_x() + main.winfo_width()
            w = max(0, int(target_x - main_end))
            h = max(28, int(filters_search_actions.winfo_reqheight() or 28))
            filters_search_spacer.configure(width=w, height=h)
            filters_search_spacer.pack_propagate(False)
        except Exception:
            pass

    date_controls_left.pack(side=tk.LEFT, anchor=tk.W)
    filters_search_actions.pack(side=tk.RIGHT, anchor=tk.NE)

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
    presets_row = ttk.Frame(date_controls_left, style="MovCdc.TFrame")
    presets_row.pack(side=tk.LEFT)

    def refresh_date_preset_button_styles() -> None:
        for pid, btn in date_preset_buttons.items():
            _set_filter_toggle_style(btn, date_preset_preview_var.get() == pid)

    def pick_date_preset(preset_id: str) -> None:
        if date_preset_preview_var.get() == preset_id and preset_id != "custom":
            # Anche sullo stesso preset, riallinea comunque campi/range (utile dopo reset o cambi modalità).
            refresh_date_fields_from_current_preset()
            refresh_date_entry_states()
            refresh_date_preset_button_styles()
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
            start_12 = _preset_rolling_start_date(12, allowed_min=global_min, allowed_max=global_max)
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

    fields_row = ttk.Frame(date_controls_left, style="MovCdc.TFrame")
    fields_row.pack(side=tk.LEFT, padx=(16, 0))

    ttk.Label(fields_row, text="dalla data", style="MovCdc.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
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
        fieldbackground=CDC_ENTRY_FIELD_BG,
        font=filter_ui_font,
    )
    date_from_entry = ttk.Entry(
        fields_row,
        textvariable=date_from_disp_var,
        width=10,
        style="DateEntry.TEntry",
    )
    date_from_entry.grid(row=0, column=1, sticky="w")
    ttk.Label(fields_row, text="alla data", style="MovCdc.TLabel").grid(row=0, column=2, sticky="w", padx=(16, 6))
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

        # Un solo popup alla volta: passando all’altro campo si chiude il calendario precedente
        # (il bind globale non chiude se il clic è su uno dei due campi data).
        if which == "from" and calendar_popup_to is not None:
            _close_calendar("to")
        elif which == "to" and calendar_popup_from is not None:
            _close_calendar("from")

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

        if keysym in ("Return", "KP_Enter"):
            return None

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

    bind_return_and_kp_enter(date_from_entry, _on_from_enter)
    bind_return_and_kp_enter(date_to_entry, _on_to_enter)
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

    refresh_movement_filter_button_styles()

    populate_movements_trees()

    balance_footer = ttk.Frame(movimenti_frame, padding=(0, 2, 0, 0), style="MovCdc.TFrame")
    balance_footer.grid(row=1, column=0, sticky="ew")
    balance_footer_row = tk.Frame(balance_footer, bg=MOVIMENTI_PAGE_BG)
    balance_footer_row.pack(fill=tk.X, anchor=tk.W)
    balance_left = tk.Frame(balance_footer_row, bg=MOVIMENTI_PAGE_BG)
    balance_left.pack(side=tk.LEFT, anchor="n")
    _saldo_hdr_font = ("TkDefaultFont", 12, "bold")
    _SALDO_ROW_LONGEST = "Saldi alla data di oggi"
    # Stesso corpo/grassetto degli importi nella tabella accanto (12 bold) per allineamento verticale riga per riga.
    _saldo_title_col_font = tkfont.Font(root, font=_saldo_hdr_font)
    # Larghezza fissa (px) dal testo più lungo, misurata all’avvio con quel font.
    _saldo_lbl_col_px = max(1, int(_saldo_title_col_font.measure(_SALDO_ROW_LONGEST)) + 6)
    # Altezza riga comune (tabella nel canvas + colonna titoli): stesso minsize su entrambe le griglie.
    _saldo_grid_row_h = int(_saldo_title_col_font.metrics("linespace")) + 2
    # Altezza iniziale; dopo refresh viene impostata su winfo_reqheight della tabella (evita taglio ultima riga).
    _saldo_canvas_body_h = 4 * (_saldo_grid_row_h + 2) + 8
    balance_lbl_col = tk.Frame(
        balance_footer_row, width=_saldo_lbl_col_px, highlightthickness=0, bg=MOVIMENTI_PAGE_BG
    )
    balance_lbl_col.pack_propagate(False)
    # anchor=n: allinea il top della colonna titoli al top della tabella (canvas create_window nw), non al centro del canvas alto 92.
    balance_lbl_col.pack(side=tk.LEFT, anchor="n", padx=(2, 1))
    balance_lbl_col.grid_columnconfigure(0, weight=1)
    for _sr in range(4):
        balance_lbl_col.grid_rowconfigure(_sr, minsize=_saldo_grid_row_h)
    tk.Label(
        balance_lbl_col,
        text="",
        font=_saldo_title_col_font,
        anchor="e",
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
    ).grid(row=0, column=0, sticky="e", pady=(0, 1))
    tk.Label(
        balance_lbl_col,
        text="Saldi assoluti",
        font=_saldo_title_col_font,
        anchor="e",
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
    ).grid(row=1, column=0, sticky="e", pady=(0, 1))
    balance_lbl_saldi_oggi = tk.Label(
        balance_lbl_col,
        text=_SALDO_ROW_LONGEST,
        font=_saldo_title_col_font,
        anchor="e",
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
    )
    balance_lbl_saldi_oggi.grid(row=2, column=0, sticky="e", pady=(0, 1))
    tk.Label(
        balance_lbl_col,
        text="Differenze",
        font=_saldo_title_col_font,
        anchor="e",
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
    ).grid(row=3, column=0, sticky="e", pady=(0, 1))
    balance_scroll_block = tk.Frame(balance_footer_row, bg=MOVIMENTI_PAGE_BG)
    balance_scroll_block.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, anchor="n")
    balance_center = tk.Frame(balance_scroll_block, bg=MOVIMENTI_PAGE_BG)
    balance_center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    balance_center_canvas = tk.Canvas(
        balance_center, highlightthickness=0, height=_saldo_canvas_body_h, bg=MOVIMENTI_PAGE_BG
    )
    balance_center_hscroll = ttk.Scrollbar(balance_center, orient="horizontal", command=balance_center_canvas.xview)
    balance_center_canvas.configure(xscrollcommand=balance_center_hscroll.set)
    balance_center_canvas.pack(fill=tk.X, expand=True)
    balance_center_hscroll.pack(fill=tk.X, pady=(6, 0))

    def _saldi_snapshot_for_print() -> dict:
        today_iso = date.today().isoformat()
        _, names, amts_future = compute_balances_future_dated_only(cur_db(), today_iso=today_iso)
        la = legacy_absolute_account_amounts(cur_db(), len(names))
        if la is not None:
            new_fx = compute_new_records_effect(cur_db())
            saldo_assoluti = [la[i] + (new_fx[i] if i < len(new_fx) else Decimal("0")) for i in range(len(names))]
        else:
            _, _, saldo_assoluti = compute_balances_from_2022_asof(cur_db(), cutoff_date_iso=today_iso)
        saldo_oggi = [saldo_assoluti[i] - amts_future[i] for i in range(len(names))]
        total_assoluti = sum(saldo_assoluti, Decimal("0"))
        total_oggi = sum(saldo_oggi, Decimal("0"))
        diffs = [a - b for a, b in zip(saldo_assoluti, saldo_oggi)]
        total_diff = total_assoluti - total_oggi
        return {
            "valuta": "E",
            "names": [n.strip() for n in names],
            "amts_abs": saldo_assoluti,
            "amts_today": saldo_oggi,
            "diffs": diffs,
            "total_abs": total_assoluti,
            "total_today": total_oggi,
            "total_diff": total_diff,
            "date_it": to_italian_date(date.today().isoformat()),
            "user_header": print_user_header_text(cur_db(), session_holder[0]),
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
            '<th class="col-hdr col-hdr-b"><strong>Saldi assoluti</strong></th>'
            '<th class="col-hdr col-hdr-b"><strong>Saldi alla data<br/>di oggi</strong></th>'
            '<th class="col-hdr col-hdr-n">Differenze</th>'
        )

        body_lines: list[str] = []
        for i, nm in enumerate(names):
            body_lines.append(
                "<tr>"
                + conti_cell(nm)
                + td_num(snap["amts_abs"][i], bold=True)
                + td_num(snap["amts_today"][i], bold=True)
                + td_num(snap["diffs"][i], bold=False)
                + "</tr>"
            )
        body_lines.append(
            '<tr class="totale">'
            + conti_cell("TOTALE")
            + td_num(snap["total_abs"], bold=True)
            + td_num(snap["total_today"], bold=True)
            + td_num(snap["total_diff"], bold=False)
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
<div class="user-hdr" style="margin:0;padding:0 0 1mm 0;text-align:center;width:100%;font-size:{h1_pt}pt;font-weight:700;line-height:1.1;">{html_module.escape(str(snap.get("user_header") or "Conti di casa"))}</div>
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
        user_header: str,
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
<div class="user-hdr" style="margin:0;padding:0 0 1mm 0;text-align:center;width:100%;font-size:{h1_pt}pt;font-weight:700;line-height:1.1;">{html_module.escape(user_header or "Conti di casa")}</div>
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
        records.sort(key=record_merge_sort_key)
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
        uh = print_user_header_text(d, session_holder[0])
        fpdf_ok = _print_ricerca_fpdf(rows, desc, uh)
        # #region agent log
        _debug_log(run_id, "H2", "main_app.py:_print_ricerca_direct", "ricerca_fpdf_result", {"fpdf_ok": fpdf_ok, "rows": n})
        # #endregion
        if fpdf_ok:
            return
        sysname = platform.system()
        if sysname == "Darwin":

            def _mk_r(iw: float) -> str:
                return _build_ricerca_print_html(
                    rows, desc, user_header=uh, for_native=True, native_text_width_pt=iw
                )

            if _print_balances_native_macos(_mk_r):
                # #region agent log
                _debug_log(run_id, "H3", "main_app.py:_print_ricerca_direct", "fallback_native_macos_used", {})
                # #endregion
                return
        elif sysname == "Windows":
            html_native = _build_ricerca_print_html(rows, desc, user_header=uh, for_native=True)
            if _print_balances_native_windows(html_native):
                return
            if _print_balances_windows_pywebview(html_native):
                return
        _print_ricerca_via_browser(_build_ricerca_print_html(rows, desc, user_header=uh, for_native=False))
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
        text="Stampa\nsaldi",
        cursor="hand2",
        highlightthickness=0,
        font=filter_ui_font,
        padx=8,
        pady=2,
        bg=_PRINT_RED,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_stampa_saldi.pack(anchor="nw")
    btn_stampa_saldi.bind("<Button-1>", lambda _e: _print_saldi_direct())
    btn_stampa_saldi.bind("<Enter>", lambda _e: btn_stampa_saldi.configure(bg=_PRINT_RED_ACTIVE))
    btn_stampa_saldi.bind("<Leave>", lambda _e: btn_stampa_saldi.configure(bg=_PRINT_RED))

    def _align_stampa_saldi_to_middle_row() -> None:
        """Centro verticale del tasto = centro dell’etichetta «Saldi alla data di oggi» (non solo minsize teorico)."""
        try:
            root.update_idletasks()
            bh = btn_stampa_saldi.winfo_height()
            if bh <= 1:
                bh = btn_stampa_saldi.winfo_reqheight()
            lh = balance_lbl_saldi_oggi.winfo_height()
            if lh <= 1:
                lh = balance_lbl_saldi_oggi.winfo_reqheight()
            if lh <= 0 or bh <= 0:
                mid = (2 + 0.5) * _saldo_grid_row_h
                ptop = max(0, int(mid - bh / 2))
            else:
                ly = balance_lbl_saldi_oggi.winfo_rooty() + lh / 2
                by0 = balance_left.winfo_rooty()
                ptop = int(round(ly - by0 - bh / 2))
                ptop = max(0, ptop)
            btn_stampa_saldi.pack_configure(pady=(ptop, 0), anchor="nw")
        except tk.TclError:
            pass

    root.after_idle(_align_stampa_saldi_to_middle_row)

    def refresh_balance_footer() -> None:
        balance_center_canvas.delete("all")
        today_iso = date.today().isoformat()
        _, names, amts_future = compute_balances_future_dated_only(cur_db(), today_iso=today_iso)
        la = legacy_absolute_account_amounts(cur_db(), len(names))
        if la is not None:
            new_fx = compute_new_records_effect(cur_db())
            saldo_assoluti = [la[i] + (new_fx[i] if i < len(new_fx) else Decimal("0")) for i in range(len(names))]
        else:
            _, _, saldo_assoluti = compute_balances_from_2022_asof(cur_db(), cutoff_date_iso=today_iso)
        saldo_oggi = [saldo_assoluti[i] - amts_future[i] for i in range(len(names))]
        total_assoluti = sum(saldo_assoluti, Decimal("0"))
        total_oggi = sum(saldo_oggi, Decimal("0"))
        diffs = [a - b for a, b in zip(saldo_assoluti, saldo_oggi)]
        total_diff = total_assoluti - total_oggi

        # Riga 1 = legacy *sld* (o fallback); riga 2 = assoluti − effetto registrazioni con data > oggi.
        table = tk.Frame(balance_center_canvas, highlightthickness=0, bd=0)
        balance_center_canvas.create_window((0, 0), window=table, anchor="nw")

        header_font = ("TkDefaultFont", 12, "bold")
        amount_font = ("TkDefaultFont", 12, "bold")
        AMT_CELL_WIDTH = 18

        def header_cell(col: int, text: str) -> None:
            pl, pr = (0, 2) if col == 0 else (0, 6)
            tk.Label(
                table,
                text=text,
                font=header_font,
                width=AMT_CELL_WIDTH,
                anchor="e",
            ).grid(row=0, column=col, sticky="e", padx=(pl, pr), pady=(0, 1))

        def amount_cell(row: int, col: int, amt: Decimal) -> None:
            pl, pr = (0, 2) if col == 0 else (0, 6)
            tk.Label(
                table,
                text=format_saldo_cell("E", amt),
                font=amount_font,
                fg=balance_amount_fg(amt),
                width=AMT_CELL_WIDTH,
                anchor=tk.E,
            ).grid(row=row, column=col, sticky="e", padx=(pl, pr), pady=(0, 1))

        # Solo TOTALE + conti nello scroll orizzontale; etichette righe fisse in balance_lbl_col.
        header_cell(0, "TOTALE")
        for i, name in enumerate(names):
            header_cell(i + 1, name.strip())

        amount_cell(1, 0, total_assoluti)
        for i, amt in enumerate(saldo_assoluti):
            amount_cell(1, i + 1, amt)

        amount_cell(2, 0, total_oggi)
        for i, amt in enumerate(saldo_oggi):
            amount_cell(2, i + 1, amt)

        amount_cell(3, 0, total_diff)
        for i, amt in enumerate(diffs):
            amount_cell(3, i + 1, amt)
        for _sr in range(4):
            table.grid_rowconfigure(_sr, minsize=_saldo_grid_row_h)
        table.update_idletasks()
        # Altezza viewport canvas = tabella reale (pady delle celle + minsize possono superare 4*row_h).
        try:
            _tbl_h = max(1, table.winfo_reqheight())
            balance_center_canvas.configure(height=_tbl_h + 4)
        except tk.TclError:
            pass
        balance_lbl_col.update_idletasks()
        balance_scroll_block.update_idletasks()
        balance_center.update_idletasks()
        balance_center_canvas.update_idletasks()
        bbox = balance_center_canvas.bbox("all")
        if bbox is not None:
            balance_center_canvas.configure(scrollregion=bbox)
        balance_center_canvas.update_idletasks()
        root.after_idle(_align_stampa_saldi_to_middle_row)

    refresh_balance_footer()

    # Pagina Nuove registrazioni
    pack_centered_page_title(
        nuovi_dati_frame,
        title=_page_banner_title(),
        banner_tk_bg=MOVIMENTI_PAGE_BG,
        title_bg=MOVIMENTI_PAGE_BG,
    )
    nuovi_top = tk.Frame(nuovi_dati_frame, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuovi_top.pack(fill=tk.X, pady=(0, 10))
    nuovi_top_inner = tk.Frame(nuovi_top, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuovi_top_inner.pack(anchor=tk.CENTER)
    btn_nuova_reg = tk.Label(
        nuovi_top_inner,
        text="Nuova registrazione",
        cursor="hand2",
        highlightthickness=0,
        font=_TAB_BAR_FONT,
        padx=10,
        pady=5,
        bg=_tipo_bg,
        fg=_tipo_fg,
        relief=tk.RAISED,
        bd=1,
    )
    btn_reg_periodiche = tk.Label(
        nuovi_top_inner,
        text="Registrazioni periodiche",
        cursor="hand2",
        highlightthickness=0,
        font=_TAB_BAR_FONT,
        padx=10,
        pady=5,
        bg=_tipo_bg,
        fg=_tipo_fg,
        relief=tk.RAISED,
        bd=1,
    )
    btn_nuova_reg.pack(side=tk.LEFT, padx=(0, 8))
    btn_reg_periodiche.pack(side=tk.LEFT)

    nuovi_submode: list[str] = ["new"]

    def _nuovi_sync_subtab_style() -> None:
        if nuovi_submode[0] == "new":
            btn_nuova_reg.configure(bg=_tipo_act, fg=_tipo_fg, relief=tk.SUNKEN, bd=2, highlightthickness=0)
            btn_reg_periodiche.configure(bg=_tipo_bg, fg=_tipo_fg, relief=tk.RAISED, bd=1, highlightthickness=0)
        else:
            btn_nuova_reg.configure(bg=_tipo_bg, fg=_tipo_fg, relief=tk.RAISED, bd=1, highlightthickness=0)
            btn_reg_periodiche.configure(bg=_tipo_act, fg=_tipo_fg, relief=tk.SUNKEN, bd=2, highlightthickness=0)

    def _nuovi_subtab_enter(which: str):
        def _on_ent(_e: tk.Event) -> None:
            if nuovi_submode[0] != which:
                (btn_nuova_reg if which == "new" else btn_reg_periodiche).configure(bg=_tipo_act)

        return _on_ent

    def _nuovi_subtab_leave(_e: tk.Event) -> None:
        _nuovi_sync_subtab_style()

    btn_nuova_reg.bind("<Enter>", _nuovi_subtab_enter("new"))
    btn_nuova_reg.bind("<Leave>", _nuovi_subtab_leave)
    btn_reg_periodiche.bind("<Enter>", _nuovi_subtab_enter("periodiche"))
    btn_reg_periodiche.bind("<Leave>", _nuovi_subtab_leave)
    _nuovi_sync_subtab_style()

    nuovi_status_var = tk.StringVar(value="")
    tk.Label(
        nuovi_dati_frame,
        textvariable=nuovi_status_var,
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
        font=("TkDefaultFont", 12, "bold"),
        highlightthickness=0,
    ).pack(anchor=tk.W, pady=(0, 8))

    nuovi_immissione_title_var = tk.StringVar(value="")

    # Come periodiche: modulo in alto (stessa quota verticale), spazio espandibile sotto (non centra il form in mezzo alla pagina).
    nuova_page_outer = tk.Frame(nuovi_dati_frame, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuova_form_strip = tk.Frame(nuova_page_outer, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuova_form_strip.pack(fill=tk.X)
    nuova_form_host = tk.Frame(nuova_form_strip, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuova_form_host.pack(anchor=tk.CENTER)
    nuova_form = tk.Frame(nuova_form_host, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuova_page_rest = tk.Frame(nuova_page_outer, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuova_page_rest.pack(fill=tk.BOTH, expand=True)
    nuova_page_outer.pack(fill=tk.BOTH, expand=True)
    # Mantiene stabile il layout verticale: mostra/nasconde controlli saldo senza spostare le righe.
    nuova_form.rowconfigure(3, minsize=36)  # riga "Conto"
    nuova_form.rowconfigure(6, minsize=36)  # riga "Importo"
    periodiche_panel = tk.Frame(nuovi_dati_frame, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    periodiche_panel.pack_forget()

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
    saldo_aggiorna_active: list[bool] = [False]
    saldo_aggiorna_locked: list[bool] = [False]
    # --- Saldo Virtuale (sostituisce la vecchia Memoria di cassa) ---
    virtuale_saldo: list[Decimal] = [read_virtuale_saldo()]
    virtuale_discharge_active: list[bool] = [read_virtuale_saldo() > Decimal("0")]
    virtuale_display_var = tk.StringVar(value="")
    newreg_calendar_popup: list[tk.Toplevel | None] = [None]
    newreg_date_manual_mode: list[bool] = [False]
    newreg_date_restore_iso: list[str | None] = [None]
    per_start_calendar_popup: list[tk.Toplevel | None] = [None]
    per_start_date_manual_mode: list[bool] = [False]
    per_start_date_restore_iso: list[str | None] = [None]
    _NEWREG_DATE_MASK = "__/__/____"
    _NEWREG_DATE_POS = (0, 1, 3, 4, 6, 7, 8, 9)

    last_date_iso = date.today().isoformat()
    last_cat_code = ""
    last_acc1_code = ""
    last_acc2_code = ""
    newreg_baseline_snapshot: list[tuple[object, ...] | None] = [None]
    newreg_last_account_touched: list[str] = ["acc1"]

    def _all_records_sorted() -> list[dict]:
        rs = [r for y in cur_db().get("years", []) for r in y.get("records", [])]
        rs.sort(key=record_merge_sort_key)
        return rs

    def _next_registration_number() -> int:
        rs = _all_records_sorted()
        return len(rs) + 1

    def _ensure_year_bucket(target_year: int) -> dict:
        d = cur_db()
        for y in d.get("years", []):
            if int(y.get("year", 0)) == int(target_year):
                return y
        if not d.get("years"):
            y0 = int(target_year)
            new_y = {
                "year": y0,
                "folder": "",
                "source_files": {},
                "legacy_saldi": None,
                "categories": [{"code": "1", "name": "+Nuova", "note": None}],
                "accounts": [{"code": "1", "name": ""}],
                "records": [],
            }
            d.setdefault("years", []).append(new_y)
            d["years"].sort(key=lambda yy: int(yy["year"]))
            return new_y
        template = chart_clone_source_bucket(d)
        if not template:
            template = max(d["years"], key=lambda yy: int(yy["year"]))
        new_y = {
            "year": int(target_year),
            "accounts": json.loads(json.dumps(template.get("accounts", []))),
            "categories": json.loads(json.dumps(template.get("categories", []))),
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
        if not d.get("years"):
            return ([], [], {}, {}, {})
        cats = merged_categories_for_plan_editor(d)
        accs = merge_account_charts_across_years(d)
        rs: list[dict] = []
        for yb in d.get("years") or []:
            rs.extend(yb.get("records") or [])
        cat_freq: dict[str, int] = {}
        acc_freq: dict[str, int] = {}
        cat_note_by_code: dict[str, str] = {}
        cat_sign_by_code: dict[str, str] = {}
        cat_raw_name_by_code: dict[str, str] = {}
        for i, c in enumerate(cats):
            code = str(c.get("code", str(i))).strip()
            if code == "0":
                continue
            if is_hidden_dotazione_category_name(str(c.get("name", ""))):
                continue
            raw_name = str(c.get("name", "")).strip()
            cat_raw_name_by_code[code] = raw_name
            sign = raw_name[:1] if raw_name[:1] in {"+", "-", "="} else ""
            cat_sign_by_code[code] = sign
            n0 = category_row_merged_note(c)
            if n0:
                cat_note_by_code[code] = n0
        for r in rs:
            c = str(r.get("category_code", "")).strip()
            if c:
                cat_freq[c] = cat_freq.get(c, 0) + 1
            for side in ("primary", "secondary"):
                k = "account_primary_code" if side == "primary" else "account_secondary_code"
                a = str(r.get(k, "")).strip()
                if a:
                    acc_freq[a] = acc_freq.get(a, 0) + 1
        cat_opts: list[tuple[str, str]] = []
        for i, c in enumerate(cats):
            code = str(c.get("code", str(i))).strip()
            if code == "0":
                continue
            if is_hidden_dotazione_category_name(str(c.get("name", ""))):
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
            cat_opts = [
                (category_display_name(c.get("name", "")), str(c.get("code", i)))
                for i, c in enumerate(cats)
                if str(c.get("code", str(i))) != "0"
                and not is_hidden_dotazione_category_name(str(c.get("name", "")))
            ]

        acc_opts: list[tuple[str, str]] = []
        for i, a in enumerate(accs):
            code = str(a.get("code", str(i + 1))).strip()
            name = str(a.get("name", "")).strip()
            acc_opts.append((name, code))
        def _acc_rank(item: tuple[str, str]) -> tuple[int, int, str]:
            n, c = item
            if n.strip().lower() == "cassa":
                return (0, 0, n)
            return (1, -acc_freq.get(c, 0), n.lower())
        acc_opts.sort(key=_acc_rank)
        if not acc_opts:
            acc_opts = [
                (str(a.get("name", "")).strip(), str(a.get("code", str(i + 1))).strip())
                for i, a in enumerate(accs)
            ]
        return cat_opts, acc_opts, cat_note_by_code, cat_sign_by_code, cat_raw_name_by_code

    newreg_ui_font = ("TkDefaultFont", 17, "bold")
    newreg_cat_note_font = ("TkDefaultFont", 15, "normal")
    ttk.Style(root).configure(
        "NewReg.TLabel",
        font=newreg_ui_font,
        background=MOVIMENTI_PAGE_BG,
        foreground="#1a1a1a",
    )
    ttk.Style(root).configure(
        "NewRegNote.TLabel",
        font=newreg_cat_note_font,
        background=MOVIMENTI_PAGE_BG,
        foreground="#000000",
    )
    ttk.Style(root).configure(
        "NewReg.TEntry", font=newreg_ui_font, fieldbackground=MOVIMENTI_PAGE_BG, foreground="#111111"
    )
    ttk.Style(root).configure("NewReg.TCombobox", font=newreg_ui_font, fieldbackground=MOVIMENTI_PAGE_BG)
    ttk.Style(root).configure("NewReg.TButton", font=newreg_ui_font)

    _NUOVI_TITLE_LBL_CH = 40
    nuovi_title_center = tk.Frame(nuova_form_host, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    nuovi_title_center.pack(anchor=tk.CENTER, pady=(0, 2))
    tk.Label(
        nuovi_title_center,
        textvariable=nuovi_immissione_title_var,
        font=newreg_ui_font,
        anchor="w",
        justify="left",
        width=_NUOVI_TITLE_LBL_CH,
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
        highlightthickness=0,
    ).pack(anchor=tk.CENTER)
    nuova_form.pack(anchor=tk.W, padx=(0, 8), pady=(0, 8))

    # Larghezze uniformi per tipo campo (Nuova registrazione + creazione periodica).
    _NR_W_DATE = 12
    _NR_W_CAT = MAX_CATEGORY_NAME_LEN
    _NR_W_ACC = MAX_ACCOUNT_NAME_LEN
    _NR_W_AMT = 14
    _NR_W_CHQ = 16
    _NR_W_NOTE = 44

    _newreg_py = 2
    _newreg_px = 6
    ttk.Label(nuova_form, text="Data (gg/mm/aaaa)", style="NewReg.TLabel").grid(row=0, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_date = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ent_date = ttk.Entry(row_date, textvariable=newreg_date_var, width=_NR_W_DATE, style="NewReg.TEntry")
    ent_date.pack(side=tk.LEFT)
    btn_oggi = ttk.Button(row_date, text="Oggi", style="NewReg.TButton")
    btn_oggi.pack(side=tk.LEFT, padx=(6, 0))
    row_date.grid(row=0, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Categoria", style="NewReg.TLabel").grid(row=1, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    cb_cat = ttk.Combobox(nuova_form, textvariable=newreg_cat_var, state="readonly", width=_NR_W_CAT, style="NewReg.TCombobox")
    cb_cat.grid(row=1, column=1, sticky="w", pady=_newreg_py)
    lbl_cat_note = ttk.Label(nuova_form, textvariable=newreg_cat_note_var, style="NewRegNote.TLabel")
    lbl_cat_note.grid(row=2, column=1, columnspan=2, sticky="w", pady=(0, 4))
    ttk.Label(nuova_form, text="Conto", style="NewReg.TLabel").grid(row=3, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_conto_outer = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    cb_acc1 = ttk.Combobox(row_conto_outer, textvariable=newreg_acc1_var, state="readonly", width=_NR_W_ACC, style="NewReg.TCombobox")
    cb_acc1.pack(side=tk.LEFT)
    btn_aggiorna_saldo = ttk.Button(row_conto_outer, text="Aggiorna saldo di cassa", style="NewReg.TButton")
    row_conto_outer.grid(row=3, column=1, columnspan=2, sticky="w", pady=_newreg_py)
    nuova_form.columnconfigure(1, weight=0)

    frm_saldo_below_btn = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    lbl_acc2 = ttk.Label(nuova_form, text="Secondo conto", style="NewReg.TLabel")
    row_acc2_outer = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    cb_acc2 = ttk.Combobox(row_acc2_outer, textvariable=newreg_acc2_var, state="readonly", width=_NR_W_ACC, style="NewReg.TCombobox")
    cb_acc2.pack(side=tk.LEFT)
    lbl_acc2.grid(row=4, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_acc2_outer.grid(row=4, column=1, columnspan=2, sticky="w", pady=_newreg_py)

    # Riga 5: area saldo virtuale (saldo readonly + Scarica) — inizialmente nascosta.
    frm_virtuale_info = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    lbl_virtuale_nota = tk.Label(frm_virtuale_info,
                                 text="Scarica il saldo virtuale sulle categorie appropriate.",
                                 bg=MOVIMENTI_PAGE_BG, fg="#1a1a1a",
                                 font=("TkDefaultFont", 11), anchor="w", justify="left")
    lbl_virtuale_nota.pack(anchor=tk.W)
    frm_virtuale_detail = tk.Frame(frm_virtuale_info, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ttk.Label(frm_virtuale_detail, text="Saldo virtuale (€)", style="NewReg.TLabel").pack(side=tk.LEFT, padx=(0, 6))
    ent_virtuale_saldo = ttk.Entry(frm_virtuale_detail, textvariable=virtuale_display_var, width=_NR_W_AMT, style="NewReg.TEntry")
    ent_virtuale_saldo.pack(side=tk.LEFT, padx=(0, 8))
    btn_scarica_virtuale = ttk.Button(frm_virtuale_detail, text="Scarica saldo virtuale", style="NewReg.TButton")
    btn_scarica_virtuale.pack(side=tk.LEFT)
    frm_virtuale_detail.pack(anchor=tk.W, pady=(2, 0))
    try:
        ent_virtuale_saldo.configure(state="readonly")
    except Exception:
        pass

    # Riga 6: Importo (€) + Nuovo saldo di cassa inline (stesso grid row).
    lbl_importo = ttk.Label(nuova_form, text="Importo (€)", style="NewReg.TLabel")
    lbl_importo.grid(row=6, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    row_amt = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ent_amt = ttk.Entry(row_amt, textvariable=newreg_amount_var, width=_NR_W_AMT, style="NewReg.TEntry")
    ent_amt.pack(side=tk.LEFT)
    btn_plus = tk.Label(row_amt, text="+", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#e0f2f1", relief=tk.RAISED, bd=1)
    btn_minus = tk.Label(row_amt, text="-", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#ffebee", relief=tk.RAISED, bd=1)
    btn_plus.pack(side=tk.LEFT, padx=(6, 2))
    btn_minus.pack(side=tk.LEFT, padx=(2, 0))
    newreg_saldo_cassa_var = tk.StringVar(value="")
    ent_saldo = ttk.Entry(row_amt, textvariable=newreg_saldo_cassa_var, width=_NR_W_AMT, style="NewReg.TEntry")
    lbl_saldo_inline = ttk.Label(row_amt, text="Nuovo saldo di cassa (€)", style="NewReg.TLabel")
    row_amt.grid(row=6, column=1, sticky="w", pady=_newreg_py)

    lbl_assegno = ttk.Label(nuova_form, text="Assegno", style="NewReg.TLabel")
    lbl_assegno.grid(row=7, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    ent_chq = ttk.Entry(nuova_form, textvariable=newreg_cheque_var, width=_NR_W_CHQ, style="NewReg.TEntry")
    ent_chq.grid(row=7, column=1, sticky="w", pady=_newreg_py)
    ttk.Label(nuova_form, text="Nota", style="NewReg.TLabel").grid(row=8, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
    ent_note = ttk.Entry(nuova_form, textvariable=newreg_note_var, width=_NR_W_NOTE, style="NewReg.TEntry")
    ent_note.grid(row=8, column=1, sticky="w", pady=_newreg_py)
    bind_entry_first_char_uppercase(newreg_note_var, ent_note)

    row_btns = tk.Frame(nuova_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    row_btns.grid(row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
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

    def _cassa_balance_euro_asof(d_iso: str) -> Decimal | None:
        try:
            _, names, balances = compute_balances_from_2022_asof(cur_db(), cutoff_date_iso=d_iso)
        except Exception:
            return None
        la = legacy_absolute_account_amounts(cur_db(), len(names))
        if la is not None:
            new_fx = compute_new_records_effect(cur_db())
            combined = [la[i] + (new_fx[i] if i < len(new_fx) else Decimal("0")) for i in range(len(names))]
            for i, n in enumerate(names):
                if n.strip().lower() == "cassa":
                    return combined[i]
        else:
            for i, n in enumerate(names):
                if n.strip().lower() == "cassa":
                    return balances[i]
        return None

    def _is_consumi_ordinari_e_cassa_selection() -> bool:
        code = _selected_category_code() or newreg_cat_code_var.get().strip()
        cat_lbl = (newreg_cat_var.get() or "").strip()
        if _is_giro_label(cat_lbl):
            return False
        if code:
            cat_from_code = next((n for n, c in cat_opts_cache if c == code), cat_lbl)
            if "consumi ordinari" not in category_display_name(cat_from_code).lower():
                return False
        else:
            if "consumi ordinari" not in category_display_name(cat_lbl).lower():
                return False

        a1_name = (newreg_acc1_var.get() or "").strip()
        a1_code = next((c for n, c in acc_opts_cache if n == a1_name), "")
        cassa_code = next((c for n, c in acc_opts_cache if n.strip().lower() == "cassa"), "")
        if a1_code and cassa_code:
            return a1_code == cassa_code
        return a1_name.lower() == "cassa"

    def _round_down_first_digit(val: Decimal) -> Decimal:
        if val <= 0:
            return Decimal("0")
        iv = int(val)
        if iv == 0:
            return Decimal("0")
        s = str(iv)
        if len(s) <= 1:
            return Decimal(s)
        first = int(s[0])
        n_zeros = len(s) - 1
        is_round = all(c == "0" for c in s[1:]) and val == Decimal(s)
        if is_round:
            if first > 1:
                return Decimal(str(first - 1) + "0" * n_zeros)
            else:
                return Decimal("9" + "0" * (n_zeros - 1)) if n_zeros >= 1 else Decimal("0")
        return Decimal(s[0] + "0" * n_zeros)

    def _format_ent_saldo_cassa() -> None:
        raw = (newreg_saldo_cassa_var.get() or "").strip()
        if not raw:
            return
        try:
            val = normalize_euro_input(raw)
        except Exception:
            return
        if val < 0:
            return
        newreg_saldo_cassa_var.set("+" + format_euro_it(val))

    def _cancel_saldo_procedure(*, silent: bool = False) -> None:
        was_active = saldo_aggiorna_active[0] or saldo_aggiorna_locked[0]
        saldo_aggiorna_active[0] = False
        saldo_aggiorna_locked[0] = False
        newreg_saldo_cassa_var.set("")
        if was_active:
            newreg_amount_var.set("")
            newreg_note_var.set("")
        lbl_importo.configure(text="Importo (€)")
        lbl_importo.grid(row=6, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
        try:
            ent_saldo.pack_forget()
            lbl_saldo_inline.pack_forget()
            ent_amt.pack_forget()
            btn_plus.pack_forget()
            btn_minus.pack_forget()
        except Exception:
            pass
        ent_amt.pack(side=tk.LEFT)
        btn_plus.pack(side=tk.LEFT, padx=(6, 2))
        btn_minus.pack(side=tk.LEFT, padx=(2, 0))
        try:
            ent_amt.configure(state="normal")
            ent_saldo.configure(state="normal")
            ent_note.configure(state="normal")
        except Exception:
            pass

    def _hide_aggiorna_saldo_btn() -> None:
        try:
            btn_aggiorna_saldo.pack_forget()
        except Exception:
            pass

    def _show_aggiorna_saldo_btn_if_needed() -> None:
        if saldo_aggiorna_active[0] or saldo_aggiorna_locked[0]:
            return
        if _is_consumi_ordinari_e_cassa_selection() and not virtuale_discharge_active[0]:
            try:
                btn_aggiorna_saldo.pack_forget()
            except Exception:
                pass
            btn_aggiorna_saldo.pack(side=tk.LEFT, padx=(8, 0))
        else:
            _hide_aggiorna_saldo_btn()

    def _on_aggiorna_saldo_cassa_click() -> None:
        if not _is_consumi_ordinari_e_cassa_selection():
            return
        d_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
        if not d_iso:
            messagebox.showerror("Aggiorna saldo di cassa", "Data non valida (gg/mm/aaaa).")
            return
        bal = _cassa_balance_euro_asof(d_iso)
        if bal is None:
            messagebox.showerror("Aggiorna saldo di cassa", "Il conto Cassa non è stato trovato nel piano conti.")
            return
        if bal <= 0:
            messagebox.showerror(
                "Aggiorna saldo di cassa",
                "Il saldo di cassa non è superiore a zero: impossibile aggiornare.",
            )
            return
        saldo_aggiorna_active[0] = True
        saldo_aggiorna_locked[0] = False
        _hide_aggiorna_saldo_btn()
        lbl_importo.grid_remove()
        newreg_amount_var.set("")
        try:
            btn_plus.pack_forget()
            btn_minus.pack_forget()
            ent_saldo.pack_forget()
            lbl_saldo_inline.pack_forget()
        except Exception:
            pass
        try:
            ent_amt.configure(state="readonly")
        except Exception:
            pass
        lbl_saldo_inline.pack(side=tk.LEFT, padx=(12, 0))
        ent_saldo.pack(side=tk.LEFT)
        prefill = _round_down_first_digit(bal) if bal > 0 else Decimal("0")
        newreg_saldo_cassa_var.set("+" + format_euro_it(prefill))
        try:
            ent_saldo.configure(state="normal")
            ent_saldo.focus_set()
            ent_saldo.selection_range(0, tk.END)
        except Exception:
            pass

    def _validate_saldo_cassa() -> None:
        if not saldo_aggiorna_active[0] or saldo_aggiorna_locked[0]:
            return
        if not _is_consumi_ordinari_e_cassa_selection():
            _cancel_saldo_procedure()
            return
        d_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
        if not d_iso:
            messagebox.showerror("Aggiorna saldo di cassa", "Data non valida (gg/mm/aaaa).")
            return
        bal = _cassa_balance_euro_asof(d_iso)
        if bal is None:
            messagebox.showerror("Aggiorna saldo di cassa", "Conto Cassa non trovato.")
            return
        raw = (newreg_saldo_cassa_var.get() or "").strip()
        if not raw:
            messagebox.showerror("Aggiorna saldo di cassa", "Inserisci il nuovo saldo di cassa.")
            return
        try:
            val = normalize_euro_input(raw)
        except Exception as exc:
            messagebox.showerror("Aggiorna saldo di cassa", str(exc))
            return
        if val < 0:
            messagebox.showerror("Aggiorna saldo di cassa", "Sono ammessi solo valori positivi o zero.")
            return
        if val > bal:
            messagebox.showerror(
                "Aggiorna saldo di cassa",
                f"Il valore non può superare il saldo attuale ({format_euro_it(bal)} €).",
            )
            newreg_saldo_cassa_var.set("+" + format_euro_it(bal))
            return
        movement = val - bal
        newreg_saldo_cassa_var.set("+" + format_euro_it(val))
        txt = format_euro_it(abs(movement))
        newreg_sign_var.set("-" if movement < 0 else "+")
        newreg_amount_var.set(("-" if movement < 0 else "+") + txt)
        newreg_note_var.set("Importo dedotto")
        saldo_aggiorna_locked[0] = True
        lbl_importo.grid(row=6, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
        try:
            ent_amt.configure(state="readonly")
            ent_saldo.configure(state="readonly")
            ent_note.configure(state="readonly")
        except Exception:
            pass
        try:
            btn_confirm.focus_set()
        except Exception:
            pass

    def _on_saldo_cassa_enter(_e: tk.Event | None = None) -> str | None:
        _validate_saldo_cassa()
        return "break"

    def _on_saldo_cassa_focusout(_e: tk.Event | None = None) -> None:
        if saldo_aggiorna_active[0] and not saldo_aggiorna_locked[0]:
            raw = (newreg_saldo_cassa_var.get() or "").strip()
            if raw:
                _validate_saldo_cassa()
            else:
                _format_ent_saldo_cassa()

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
        dmin, dmax = immissione_date_bounds()
        dsel = date.fromisoformat(iso)
        if dsel < dmin:
            dsel = dmin
        if dsel > dmax:
            dsel = dmax
        newreg_date_var.set(to_italian_date(dsel.isoformat()))
        _apply_giro_default_note()

    def _immissione_date_masked_keypress(
        event: tk.Event, *, entry: tk.Misc, var: tk.StringVar, on_complete: Callable[[], None]
    ) -> str | None:
        s = var.get() or ""
        if len(s) != len(_NEWREG_DATE_MASK) or s[2] != "/" or s[5] != "/":
            if parse_italian_ddmmyyyy_to_iso(s):
                return None
            s = _NEWREG_DATE_MASK
            var.set(s)
        keysym = getattr(event, "keysym", "")
        ch = getattr(event, "char", "")
        if keysym in ("Left", "Right", "Home", "End", "Tab", "ISO_Left_Tab", "Return", "KP_Enter"):
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
                y_min, y_max = immissione_date_bounds()
                y_min, y_max = y_min.year, y_max.year
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
                dmin, dmax = immissione_date_bounds()
                if dsel < dmin or dsel > dmax:
                    return "break"
            var.set(s2)
            if all(s2[i].isdigit() for i in _NEWREG_DATE_POS):
                on_complete()
            after = next_i + 1
            if after in (2, 5):
                after += 1
            entry.icursor(after)
            return "break"
        if ch:
            return "break"
        return None

    def _newreg_date_keypress(event: tk.Event) -> str | None:
        return _immissione_date_masked_keypress(
            event, entry=ent_date, var=newreg_date_var, on_complete=_apply_giro_default_note
        )

    def _is_cassa_first_account() -> bool:
        return (newreg_acc1_var.get() or "").strip().lower() == "cassa"

    def _is_second_account_cassa() -> bool:
        return (newreg_acc2_var.get() or "").strip().lower() == "cassa"

    def _is_virtuale_account(name: str) -> bool:
        return name.strip().lower() == VIRTUALE_ACCOUNT_NAME.lower()

    def _has_virtuale_in_girata() -> bool:
        return _is_virtuale_account(newreg_acc1_var.get()) or _is_virtuale_account(newreg_acc2_var.get())

    _AUT_NOTE_RE = re.compile(r"^Aut \d{2}/\d{2}$")

    def _note_is_aut_replaceable(cur: str) -> bool:
        t = (cur or "").strip()
        if not t or t == "-":
            return True
        if t == "Giroconto":
            return True
        return bool(_AUT_NOTE_RE.fullmatch(t))

    def _build_aut_note_girata_seconda_cassa() -> str | None:
        """«Aut » + gg/mm + spazio (cursore dopo la data per testo aggiuntivo)."""
        if not _is_giro_label(newreg_cat_var.get()):
            return None
        if not _is_second_account_cassa():
            return None
        iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
        if not iso:
            return None
        d = date.fromisoformat(iso)
        return f"Aut {d.day:02d}/{d.month:02d} "

    def _position_newreg_note_cursor_after_aut() -> None:
        """Se la nota è «Aut gg/mm», garantisce uno spazio finale e cursore subito dopo."""
        s = newreg_note_var.get() or ""
        core = s.rstrip()
        if not _AUT_NOTE_RE.fullmatch(core):
            return
        want = core + " "
        if s != want:
            newreg_note_var.set(want)

        def _place() -> None:
            try:
                ent_note.icursor(len(newreg_note_var.get() or ""))
            except Exception:
                pass

        try:
            root.after_idle(_place)
        except Exception:
            _place()

    def _on_newreg_note_focus_in(_e: tk.Event | None = None) -> None:
        _position_newreg_note_cursor_after_aut()

    ent_note.bind("<FocusIn>", _on_newreg_note_focus_in, add="+")

    def _apply_giro_default_note() -> None:
        if not _is_giro_label(newreg_cat_var.get()):
            return
        if _has_virtuale_in_girata():
            cur = (newreg_note_var.get() or "").strip()
            if cur == "Giroconto":
                newreg_note_var.set("")
            return
        cur = (newreg_note_var.get() or "").strip()
        aut = _build_aut_note_girata_seconda_cassa()
        if aut is not None:
            if _note_is_aut_replaceable(cur):
                newreg_note_var.set(aut)
                try:
                    root.after_idle(_position_newreg_note_cursor_after_aut)
                except Exception:
                    _position_newreg_note_cursor_after_aut()
            return
        if not cur or cur == "-" or cur == "Giroconto":
            newreg_note_var.set("Giroconto")
        elif _AUT_NOTE_RE.fullmatch(cur):
            newreg_note_var.set("Giroconto")

    def _virtuale_must_discharge() -> bool:
        return virtuale_saldo[0] > Decimal("0")

    def _refresh_virtuale_ui() -> None:
        m = virtuale_saldo[0].quantize(Decimal("0.01"))
        virtuale_display_var.set(format_euro_it(m) if m > 0 else "")
        if virtuale_discharge_active[0] and m > 0:
            lbl_virtuale_nota.configure(
                text=f"Saldo virtuale: {format_euro_it(m)} €. Registra per ridurre o scarica."
            )
            frm_virtuale_info.grid(row=5, column=0, columnspan=3, sticky="w", pady=_newreg_py)
        else:
            frm_virtuale_info.grid_remove()

    def _enter_virtuale_discharge_mode(amount: Decimal) -> None:
        virtuale_saldo[0] = abs(amount).quantize(Decimal("0.01"))
        virtuale_discharge_active[0] = True
        write_virtuale_saldo(virtuale_saldo[0])
        _refresh_virtuale_ui()
        _sync_cat_note_and_second_account()

    def _exit_virtuale_discharge_mode() -> None:
        virtuale_saldo[0] = Decimal("0")
        virtuale_discharge_active[0] = False
        write_virtuale_saldo(Decimal("0"))
        _refresh_virtuale_ui()
        _sync_cat_note_and_second_account()
        try:
            root.after_idle(_sync_cat_note_and_second_account)
        except Exception:
            pass

    def _on_scarica_virtuale_click() -> None:
        m = virtuale_saldo[0]
        if m <= 0:
            return
        code = newreg_cat_code_var.get().strip()
        if not code:
            code = next((c for n, c in cat_opts_cache if n == newreg_cat_var.get()), "")
        sign = cat_sign_by_code_cache.get(code, "-")
        if sign not in ("+", "-"):
            sign = "-"
        newreg_sign_var.set(sign)
        newreg_amount_var.set(("-" if sign == "-" else "+") + format_euro_it(m))

    def _sync_cat_note_and_second_account() -> None:
        if virtuale_discharge_active[0]:
            vals = [n for n, _c in cat_opts_cache if not _is_giro_label(n)]
            cb_cat.configure(values=vals)
            if _is_giro_label(newreg_cat_var.get()):
                first_code = next((c for n, c in cat_opts_cache if not _is_giro_label(n)), "")
                if first_code:
                    _set_category_by_code(first_code)
            cb_acc1.configure(values=[VIRTUALE_ACCOUNT_NAME])
            newreg_acc1_var.set(VIRTUALE_ACCOUNT_NAME)
        else:
            cb_cat.configure(values=[n for n, _c in cat_opts_cache])
            cb_acc1.configure(values=[n for n, _c in acc_opts_cache])
        try:
            _cat_vals = list(cb_cat.cget("values"))
            _cat_nm = (newreg_cat_var.get() or "").strip()
            if _cat_vals and _cat_nm and _cat_nm in _cat_vals:
                cb_cat.set(_cat_nm)
        except Exception:
            pass
        code = newreg_cat_code_var.get().strip()
        if not code:
            code = next((c for n, c in cat_opts_cache if n == newreg_cat_var.get()), "")
            newreg_cat_code_var.set(code)
        newreg_cat_note_var.set(cat_note_by_code_cache.get(code, "-") or "-")
        is_giro = _is_giro_label(newreg_cat_var.get())
        if is_giro:
            _apply_sign("-")
        else:
            sign = cat_sign_by_code_cache.get(code, "")
            if sign == "+":
                _apply_sign("+")
            elif sign in ("-", "="):
                _apply_sign("-")
        if is_giro and not virtuale_discharge_active[0]:
            lbl_acc2.grid(row=4, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
            row_acc2_outer.grid(row=4, column=1, columnspan=2, sticky="w", pady=_newreg_py)
            try:
                cb_acc2.pack_forget()
            except Exception:
                pass
            cb_acc2.pack(side=tk.LEFT)
            acc_names_giro = [n for n, _c in acc_opts_cache]
            if VIRTUALE_ACCOUNT_NAME not in acc_names_giro:
                acc_names_giro.append(VIRTUALE_ACCOUNT_NAME)
            cb_acc1.configure(values=acc_names_giro)
            cb_acc2.configure(values=acc_names_giro)
            if not newreg_acc2_var.get() and acc_opts_cache:
                names = [n for n, _c in acc_opts_cache]
                pick = names[1] if len(names) > 1 else names[0]
                if pick == newreg_acc1_var.get() and len(names) > 1:
                    pick = names[0]
                newreg_acc2_var.set(pick)
                newreg_last_account_touched[0] = "acc2"
            if _is_virtuale_account(newreg_acc1_var.get()) and _is_virtuale_account(newreg_acc2_var.get()):
                if newreg_last_account_touched[0] == "acc1":
                    newreg_acc2_var.set("Cassa")
                else:
                    newreg_acc1_var.set("Cassa")
            if newreg_acc1_var.get().strip() and newreg_acc1_var.get().strip() == newreg_acc2_var.get().strip():
                if acc_opts_cache:
                    for n, _c in acc_opts_cache:
                        if n != newreg_acc1_var.get().strip():
                            if newreg_last_account_touched[0] == "acc2":
                                newreg_acc1_var.set(n)
                            else:
                                newreg_acc2_var.set(n)
                            break
                if newreg_acc1_var.get().strip() == newreg_acc2_var.get().strip():
                    nuovi_status_var.set("Attenzione: i due conti del giroconto devono essere diversi.")
            _apply_giro_default_note()
        else:
            lbl_acc2.grid_remove()
            row_acc2_outer.grid_remove()
            newreg_acc2_var.set("")

        # Annulla procedura saldo se si cambia categoria/conto.
        if saldo_aggiorna_active[0] or saldo_aggiorna_locked[0]:
            if not messagebox.askyesno(
                "Aggiorna saldo di cassa",
                "La procedura di aggiornamento del saldo di cassa è in corso.\n"
                "Cambiando categoria o conto verrà annullata.\n\nConfermi?",
            ):
                co_code = next((c for n, c in cat_opts_cache if n.lower() == "consumi ordinari"), "")
                if co_code:
                    _set_category_by_code(co_code)
                newreg_acc1_var.set("Cassa")
                return
            _cancel_saldo_procedure()
        _show_aggiorna_saldo_btn_if_needed()

        # Cassa o Virtuale: nessun assegno; ripristina la riga se si cambia conto.
        if _is_cassa_first_account() or _is_virtuale_account(newreg_acc1_var.get()):
            lbl_assegno.grid_remove()
            ent_chq.grid_remove()
            newreg_cheque_var.set("")
            try:
                ent_chq.configure(takefocus=False)
            except Exception:
                pass
        else:
            lbl_assegno.grid(row=7, column=0, sticky="w", pady=_newreg_py, padx=(0, _newreg_px))
            ent_chq.grid(row=7, column=1, sticky="w", pady=_newreg_py)
            try:
                ent_chq.configure(takefocus=True)
            except Exception:
                pass

        _refresh_virtuale_ui()

    def _selected_category_code() -> str:
        cat_name = (newreg_cat_var.get() or "").strip()
        if cat_name:
            code = next((c for n, c in cat_opts_cache if n == cat_name), "")
            if code:
                return code
        return newreg_cat_code_var.get().strip()

    def _set_category_by_code(code: str) -> None:
        target = next(((n, c) for n, c in cat_opts_cache if c == code), None)
        if target:
            newreg_cat_var.set(target[0])
            newreg_cat_code_var.set(target[1])
            try:
                combo_vals = list(cb_cat.cget("values"))
                if target[0] in combo_vals:
                    cb_cat.current(combo_vals.index(target[0]))
            except Exception:
                pass
        elif cat_opts_cache:
            combo_vals = list(cb_cat.cget("values"))
            first_name = combo_vals[0] if combo_vals else cat_opts_cache[0][0]
            first_code = next((c for n, c in cat_opts_cache if n == first_name), cat_opts_cache[0][1])
            newreg_cat_var.set(first_name)
            newreg_cat_code_var.set(first_code)
            try:
                cb_cat.current(0)
            except Exception:
                pass

    def _apply_sign(sign: str) -> None:
        if _is_giro_label(newreg_cat_var.get()) and sign == "+":
            sign = "-"
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
            if _is_giro_label(newreg_cat_var.get()):
                amt = -abs(amt)
            elif newreg_sign_var.get() == "-":
                amt = -abs(amt)
            else:
                amt = abs(amt)
            txt = format_euro_it(abs(amt))
            newreg_amount_var.set(("-" if amt < 0 else "+") + txt)
            if _is_giro_label(newreg_cat_var.get()):
                newreg_sign_var.set("-")
        except Exception:
            pass

    def _open_newreg_calendar_popup() -> None:
        dmin, dmax = immissione_date_bounds()
        today = date.today()
        cur_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get()) or today.isoformat()
        try:
            cur = date.fromisoformat(cur_iso)
        except Exception:
            cur = today
        cur = max(dmin, min(cur, dmax))

        def _on_date_chosen(dsel: date) -> None:
            newreg_date_var.set(to_italian_date(dsel.isoformat()))
            _apply_giro_default_note()
            newreg_date_manual_mode[0] = False

        top = build_immissione_calendar_toplevel(
            root,
            title="Seleziona data",
            anchor=ent_date,
            field_min=dmin,
            field_max=dmax,
            current=cur,
            on_date_chosen=_on_date_chosen,
            ui_font=filter_ui_font,
        )
        newreg_calendar_popup[0] = top

        def _on_nr_cal_destroy(_e: tk.Event | None = None) -> None:
            newreg_calendar_popup[0] = None

        top.bind("<Destroy>", _on_nr_cal_destroy)

    def _toggle_newreg_date_calendar() -> None:
        """Come filtri Movimenti: 1° click calendario; 2° click chiude e maschera per digitazione manuale."""
        if newreg_date_manual_mode[0]:
            newreg_date_manual_mode[0] = False
            if newreg_date_restore_iso[0]:
                try:
                    newreg_date_var.set(to_italian_date(newreg_date_restore_iso[0]))
                except Exception:
                    pass
                newreg_date_restore_iso[0] = None
            else:
                _normalize_newreg_date_display()
            _open_newreg_calendar_popup()
            return
        if newreg_calendar_popup[0] is not None:
            try:
                newreg_calendar_popup[0].destroy()
            except Exception:
                pass
            newreg_calendar_popup[0] = None
            newreg_date_manual_mode[0] = True
            iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
            newreg_date_restore_iso[0] = iso if iso else date.today().isoformat()
            newreg_date_var.set(_NEWREG_DATE_MASK)
            try:
                ent_date.focus_set()
                ent_date.icursor(0)
            except Exception:
                pass
            return
        _open_newreg_calendar_popup()

    def _newreg_form_snapshot() -> tuple[object, ...]:
        return (
            (newreg_date_var.get() or "").strip(),
            (newreg_cat_var.get() or "").strip(),
            (newreg_cat_code_var.get() or "").strip(),
            (newreg_cat_note_var.get() or "").strip(),
            (newreg_acc1_var.get() or "").strip(),
            (newreg_acc2_var.get() or "").strip(),
            (newreg_amount_var.get() or "").strip(),
            newreg_sign_var.get(),
            (newreg_cheque_var.get() or "").strip(),
            (newreg_note_var.get() or "").strip(),
            (newreg_saldo_cassa_var.get() or "").strip(),
        )

    def _newreg_form_unchanged() -> bool:
        b = newreg_baseline_snapshot[0]
        if b is None:
            return False
        return b == _newreg_form_snapshot()

    def _populate_form_defaults(*, keep_last: bool) -> None:
        nonlocal cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache
        cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache = _cat_and_acc_options()
        cb_cat.configure(values=[n for n, _c in cat_opts_cache])
        cb_acc1.configure(values=[n for n, _c in acc_opts_cache])
        cb_acc2.configure(values=[n for n, _c in acc_opts_cache])
        newreg_no_var.set(f"Nuova registrazione n. {_next_registration_number()}")
        if nuovi_submode[0] == "new":
            nuovi_immissione_title_var.set(newreg_no_var.get())
        if virtuale_discharge_active[0]:
            newreg_date_var.set(to_italian_date(date.today().isoformat()))
            _set_category_by_code(
                next(
                    (c for n, c in cat_opts_cache if "consumi ordinari" in n.strip().lower()), ""
                )
            )
            newreg_acc1_var.set(VIRTUALE_ACCOUNT_NAME)
            newreg_acc2_var.set("")
        elif keep_last:
            newreg_date_var.set(to_italian_date(last_date_iso))
            _set_category_by_code(last_cat_code if last_cat_code else next((c for n, c in cat_opts_cache if n.lower() == "consumi ordinari"), ""))
            if _is_virtuale_account(last_acc1_code):
                a1_name = next((n for n, _c in acc_opts_cache if n.strip().lower() == "cassa"), acc_opts_cache[0][0] if acc_opts_cache else "")
            else:
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
        _cancel_saldo_procedure()
        _sync_cat_note_and_second_account()
        newreg_baseline_snapshot[0] = _newreg_form_snapshot()
        newreg_last_account_touched[0] = "acc1"

    def _collect_new_record_payload() -> tuple[dict, str] | None:
        d_iso = parse_italian_ddmmyyyy_to_iso(newreg_date_var.get())
        if not d_iso:
            messagebox.showerror("Nuova registrazione", "Data non valida (gg/mm/aaaa).")
            return None
        dsel = date.fromisoformat(d_iso)
        dmin, dmax = immissione_date_bounds()
        if dsel < dmin or dsel > dmax:
            messagebox.showerror("Nuova registrazione", "Data fuori intervallo consentito (da -1 anno a +1 anno).")
            return None
        cat_name = newreg_cat_var.get().strip()
        cat_code = _selected_category_code() or newreg_cat_code_var.get().strip()
        if not cat_code:
            messagebox.showerror("Nuova registrazione", "Categoria obbligatoria.")
            return None
        if virtuale_discharge_active[0] and _is_giro_label(cat_name):
            messagebox.showerror(
                "Nuova registrazione",
                "Durante lo scarico del saldo virtuale non è possibile registrare una Girata conto/conto.",
            )
            return None
        acc1_name = newreg_acc1_var.get().strip()
        is_acc1_virtuale = _is_virtuale_account(acc1_name)
        acc1_code = (VIRTUALE_ACCOUNT_NAME if is_acc1_virtuale
                     else next((c for n, c in acc_opts_cache if n == acc1_name), ""))
        if not acc1_code:
            messagebox.showerror("Nuova registrazione", "Conto obbligatorio.")
            return None
        giro = _is_giro_label(cat_name)
        acc2_name = newreg_acc2_var.get().strip() if giro else ""
        is_acc2_virtuale = _is_virtuale_account(acc2_name) if giro else False
        acc2_code = (VIRTUALE_ACCOUNT_NAME if is_acc2_virtuale
                     else (next((c for n, c in acc_opts_cache if n == acc2_name), "") if giro else ""))
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
        if giro:
            amt = -abs(amt)
        elif newreg_sign_var.get() == "-":
            amt = -abs(amt)
        else:
            amt = abs(amt)
        if amt == Decimal("0.00"):
            messagebox.showerror("Nuova registrazione", "Importo a zero non ammesso.")
            return None
        if _is_cassa_first_account():
            chq = "-"
        else:
            chq = sanitize_single_line_text(newreg_cheque_var.get() or "", max_len=MAX_CHEQUE_LEN)
            if not chq:
                chq = "-"
        note = sanitize_single_line_text(newreg_note_var.get() or "", max_len=MAX_RECORD_NOTE_LEN)
        if not note:
            note = "-"

        target_year = int(dsel.year)
        y_bucket = _ensure_year_bucket(target_year)
        y_records = y_bucket.get("records", [])
        source_index = max((int(r.get("source_index", 0) or 0) for r in y_records), default=0) + 1
        registration_number = _next_registration_number()
        legacy_key = f"APP:manual:{target_year}:{source_index}"
        rec = {
            "year": target_year,
            "source_folder": "APP",
            "source_file": "manual",
            "source_index": source_index,
            "legacy_registration_number": source_index,
            "legacy_registration_key": legacy_key,
            "registration_number": registration_number,
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
            "is_virtuale_discharge": virtuale_discharge_active[0] and not giro,
        }
        amt_preview = ("+" if amt >= 0 else "") + format_euro_it(amt)
        preview = f"Data {to_italian_date(d_iso)}, {cat_name}, {acc1_name}" + (f", {acc2_name}" if giro else "") + f", {amt_preview} EUR"
        return rec, preview

    def _commit_new_record(*, finish: bool) -> None:
        nonlocal last_date_iso, last_cat_code, last_acc1_code, last_acc2_code
        if finish and virtuale_discharge_active[0]:
            messagebox.showwarning(
                "Saldo virtuale",
                f"Il saldo virtuale è di {format_euro_it(virtuale_saldo[0])} €.\n"
                "Occorre azzerarlo prima di uscire dall'immissione dati.",
            )
            return
        if finish and _newreg_form_unchanged():
            if messagebox.askyesno("Concludi immissione", "Confermi di passare alla pagina Movimenti?"):
                notebook.select(movimenti_frame)
            else:
                try:
                    ent_date.focus_set()
                except Exception:
                    pass
            return
        payload = _collect_new_record_payload()
        if payload is None:
            if finish and messagebox.askyesno("Concludi immissione", "Dati incompleti/non validi. Chiudere comunque e tornare a Movimenti?"):
                notebook.select(movimenti_frame)
            return
        rec, preview = payload
        title = "Concludi immissione" if finish else "Conferma immissione"
        if not messagebox.askyesno(title, f"Confermi l'inserimento della registrazione?\n\n{preview}"):
            return
        has_virtuale_rec = (_is_virtuale_account(str(rec.get("account_primary_name", "")))
                           or _is_virtuale_account(str(rec.get("account_secondary_name", ""))))
        if has_virtuale_rec:
            if not messagebox.askyesno(
                "Registrazione non modificabile",
                "Hai controllato bene questa registrazione, che non sarà modificabile?"
            ):
                try:
                    cb_cat.focus_set()
                except Exception:
                    pass
                return
        y_bucket = _ensure_year_bucket(int(rec["year"]))
        y_bucket["records"].append(rec)
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Nuova registrazione", str(exc))
            return
        amt_dec = to_decimal(rec["amount_eur"])
        has_virtuale = (_is_virtuale_account(str(rec.get("account_primary_name", "")))
                        or _is_virtuale_account(str(rec.get("account_secondary_name", ""))))
        if has_virtuale and is_giroconto_record(rec) and not virtuale_discharge_active[0]:
            _enter_virtuale_discharge_mode(amt_dec)
        elif virtuale_discharge_active[0]:
            new_bal = (virtuale_saldo[0] - abs(amt_dec)).quantize(Decimal("0.01"))
            virtuale_saldo[0] = max(Decimal("0"), new_bal)
            write_virtuale_saldo(virtuale_saldo[0])
            if virtuale_saldo[0] <= Decimal("0"):
                _exit_virtuale_discharge_mode()
            else:
                _refresh_virtuale_ui()
        _movements_dirty[0] = True
        refresh_balance_footer()
        last_date_iso = str(rec["date_iso"])
        last_cat_code = str(rec["category_code"])
        last_acc1_code = str(rec["account_primary_code"])
        last_acc2_code = str(rec.get("account_secondary_code", ""))
        nuovi_status_var.set("")
        # Sempre ripulire il modulo (inclusa la Nota) per la registrazione successiva,
        # anche se si passa subito a Movimenti con «Concludi immissione».
        _populate_form_defaults(keep_last=True)
        if finish:
            notebook.select(movimenti_frame)
        else:
            try:
                ent_date.focus_set()
            except Exception:
                pass

    def _clear_values() -> None:
        if not messagebox.askyesno("Cancella valori", "Confermi cancellazione valori immessi?"):
            return
        _populate_form_defaults(keep_last=False)

    per_edit_rule_id: list[str | None] = [None]
    # Dopo «Modifica (per le registrazioni future)»: cambiando riga nel grid il modulo segue la selezione.
    per_follow_grid_selection: list[bool] = [False]
    per_tree_rows_sched: list[str | None] = [None]
    per_start_date_var = tk.StringVar(value=to_italian_date(date.today().isoformat()))
    per_date_field_lbl_var = tk.StringVar(value="Prima scadenza")
    per_cadence_var = tk.StringVar(value="monthly")
    per_cat_var = tk.StringVar()
    per_cat_code_var = tk.StringVar()
    per_cat_note_var = tk.StringVar(value="-")
    per_acc1_var = tk.StringVar()
    per_acc2_var = tk.StringVar()
    per_sign_var = tk.StringVar(value="+")
    per_amount_var = tk.StringVar()
    per_note_var = tk.StringVar()
    per_status_var = tk.StringVar(value="")

    # Contenuto diretto nel tab: in alto creazione/modifica, sotto elenco+griglia (stessa colonna sinistra).
    per_main = tk.Frame(periodiche_panel, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_main.pack(fill=tk.BOTH, expand=True)
    per_form_center_strip = tk.Frame(per_main, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_form_center_strip.pack(fill=tk.X)
    per_top_center = tk.Frame(per_form_center_strip, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_top_center.pack(anchor=tk.CENTER)
    per_top_block = tk.Frame(per_top_center, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_top_block.pack(anchor=tk.W)
    per_list_block = tk.Frame(per_main, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_list_block.pack(fill=tk.BOTH, expand=True)

    per_title_row = tk.Frame(per_list_block, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ttk.Label(per_title_row, text="Elenco registrazioni periodiche", style="NewReg.TLabel").pack(
        side=tk.LEFT, anchor=tk.W
    )
    btn_per_edit_future = tk.Label(
        per_title_row,
        text="Modifica (per le registrazioni future)",
        cursor="hand2",
        highlightthickness=0,
        font=("TkDefaultFont", 10, "bold"),
        padx=8,
        pady=3,
        bg=_CORREZIONE_BLUE,
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_per_delete = tk.Label(
        per_title_row,
        text="Elimina (per le registrazioni future)",
        cursor="hand2",
        highlightthickness=0,
        font=("TkDefaultFont", 10, "bold"),
        padx=8,
        pady=3,
        bg="#b71c1c",
        fg="#ffffff",
        relief=tk.RAISED,
        bd=1,
    )
    btn_per_edit_future.pack(side=tk.LEFT, padx=(0, 8))
    btn_per_delete.pack(side=tk.LEFT)
    btn_per_edit_future.pack_forget()
    btn_per_delete.pack_forget()
    # Stesso schema della griglia Movimenti: tree principale | sep | importo (colori) | sep | nota | scrollbar.
    # Stili MovGrid.* già definiti sopra per Movimenti.
    per_tree_frame = tk.Frame(per_list_block, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    tree_per_scroll_y = ttk.Scrollbar(per_tree_frame, orient="vertical")
    tree_per_scroll_x = ttk.Scrollbar(per_tree_frame, orient="horizontal")
    _SEP_CH_W = 6
    header_bg = CDC_GRID_HEADING_BG
    header_fg = "#1a1a1a"
    header_font = ("TkDefaultFont", 10, "bold")
    header_row = tk.Frame(per_tree_frame, bg=header_bg)
    per_mov_hdr = tk.Frame(header_row, bg=header_bg)
    hdr_sep_1 = tk.Frame(header_row, bg=header_bg, width=_SEP_CH_W)
    amt_hdr = tk.Frame(header_row, bg=header_bg)
    hdr_sep_2 = tk.Frame(header_row, bg=header_bg, width=_SEP_CH_W)
    note_hdr = tk.Frame(header_row, bg=header_bg)
    hdr_sep_1_line = tk.Frame(hdr_sep_1, bg="#c0c0c0", width=1)
    hdr_sep_2_line = tk.Frame(hdr_sep_2, bg="#c0c0c0", width=1)
    header_row.grid_columnconfigure(0, weight=1, minsize=120)
    header_row.grid_columnconfigure(1, weight=0, minsize=_SEP_CH_W)
    header_row.grid_columnconfigure(2, weight=0, minsize=104)
    header_row.grid_columnconfigure(3, weight=0, minsize=_SEP_CH_W)
    header_row.grid_columnconfigure(4, weight=1, minsize=100)
    per_mov_hdr.grid_columnconfigure(0, minsize=1)
    per_mov_hdr.grid_columnconfigure(1, minsize=100)
    per_mov_hdr.grid_columnconfigure(2, minsize=100)
    per_mov_hdr.grid_columnconfigure(3, minsize=100)
    per_mov_hdr.grid_columnconfigure(4, weight=1, minsize=160)
    per_mov_hdr.grid_columnconfigure(5, weight=1, minsize=100)
    per_mov_hdr.grid_columnconfigure(6, weight=1, minsize=100)
    per_mov_hdr.grid_columnconfigure(7, minsize=70)
    tk.Label(per_mov_hdr, text="", bg=header_bg, fg=header_fg, font=header_font).grid(row=0, column=0, sticky="ew")
    tk.Label(per_mov_hdr, text="Cadenza", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=1, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Ultima creaz.", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=2, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Prossima creaz.", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=3, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Categoria", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=4, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Conto", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=5, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Secondo conto", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=6, sticky="ew"
    )
    tk.Label(per_mov_hdr, text="Assegno", bg=header_bg, fg=header_fg, font=header_font, anchor="center").grid(
        row=0, column=7, sticky="ew"
    )
    amt_hdr.grid_columnconfigure(0, weight=1, minsize=128)
    tk.Label(amt_hdr, text="Importo", bg=header_bg, fg=header_fg, font=header_font, anchor="e").grid(
        row=0, column=0, sticky="ew"
    )
    note_hdr.grid_columnconfigure(0, weight=1, minsize=280)
    tk.Label(note_hdr, text="Nota", bg=header_bg, fg=header_fg, font=header_font, anchor="w").grid(
        row=0, column=0, sticky="ew"
    )
    per_mov_hdr.grid(row=0, column=0, sticky="ew")
    hdr_sep_1.grid(row=0, column=1, sticky="nsw")
    amt_hdr.grid(row=0, column=2, sticky="ew")
    hdr_sep_2.grid(row=0, column=3, sticky="nsw")
    note_hdr.grid(row=0, column=4, sticky="ew")
    hdr_sep_1_line.place(x=0, y=0, relheight=1.0)
    hdr_sep_2_line.place(x=0, y=0, relheight=1.0)

    _per_cols = ("per_pad", "cad", "last", "next", "cat", "acc1", "acc2", "chq")
    tree_per = ttk.Treeview(
        per_tree_frame,
        columns=_per_cols,
        show="tree",
        height=8,
        selectmode="browse",
        style="MovGrid.Treeview",
        xscrollcommand=tree_per_scroll_x.set,
    )
    tree_per.heading("per_pad", text="")
    tree_per.column("per_pad", width=1, minwidth=1, stretch=False, anchor=tk.CENTER)
    tree_per.heading("cad", text="Cadenza", anchor="w")
    tree_per.heading("last", text="Ultima creaz.", anchor="w")
    tree_per.heading("next", text="Prossima creaz.", anchor="w")
    tree_per.heading("cat", text="Categoria", anchor="w")
    tree_per.heading("acc1", text="Conto", anchor="w")
    tree_per.heading("acc2", text="Secondo conto", anchor="w")
    tree_per.heading("chq", text="Assegno", anchor="w")
    tree_per.column("cad", width=100, minwidth=70)
    tree_per.column("last", width=100, minwidth=80)
    tree_per.column("next", width=100, minwidth=80)
    tree_per.column("cat", width=160, minwidth=100)
    tree_per.column("acc1", width=100, minwidth=70)
    tree_per.column("acc2", width=100, minwidth=70)
    tree_per.column("chq", width=70, minwidth=50)
    tree_per.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    tree_per.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

    tree_per_amt = ttk.Treeview(
        per_tree_frame,
        columns=("amount_eur",),
        show="tree",
        height=8,
        selectmode="browse",
        style="MovGridAmount.Treeview",
    )
    tree_per_amt.heading("amount_eur", text="Importo", anchor="e")
    tree_per_amt.column("amount_eur", width=128, anchor="e", stretch=False, minwidth=96)
    tree_per_amt.tag_configure("neg", foreground=COLOR_AMOUNT_NEG)
    tree_per_amt.tag_configure("pos", foreground=COLOR_AMOUNT_POS)
    tree_per_amt.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    tree_per_amt.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

    tree_per_note = ttk.Treeview(
        per_tree_frame,
        columns=("note",),
        show="tree",
        height=8,
        selectmode="browse",
        style="MovGrid.Treeview",
    )
    tree_per_note.heading("note", text="Nota", anchor="w")
    tree_per_note.column("note", width=280, anchor="w", stretch=True, minwidth=120)
    tree_per_note.tag_configure("stripe0", background=CDC_GRID_STRIPE0_BG)
    tree_per_note.tag_configure("stripe1", background=CDC_GRID_STRIPE1_BG)

    tree_per.column("#0", width=0, minwidth=0, stretch=False)
    tree_per_amt.column("#0", width=0, minwidth=0, stretch=False)
    tree_per_note.column("#0", width=0, minwidth=0, stretch=False)

    per_mov_hdr_vlines: list[tk.Frame] = []

    def _ensure_per_mov_hdr_vlines() -> None:
        nonlocal per_mov_hdr_vlines
        if per_mov_hdr_vlines:
            return
        for _ in range(7):
            per_mov_hdr_vlines.append(
                tk.Frame(per_mov_hdr, bg="#c0c0c0", width=1, highlightthickness=0)
            )

    def _position_per_mov_hdr_vlines(_e: tk.Event | None = None) -> None:
        _ensure_per_mov_hdr_vlines()
        cols = ["per_pad", "cad", "last", "next", "cat", "acc1", "acc2"]
        x = 0
        x_offset = 1
        for i, cid in enumerate(cols):
            try:
                w = int(tree_per.column(cid, "width"))
            except Exception:
                w = 0
            x += w
            per_mov_hdr_vlines[i].place(x=x + x_offset, y=0, relheight=1.0)
            per_mov_hdr_vlines[i].lift()

    per_tree_vlines: list[tk.Frame] = []

    def _ensure_per_tree_vlines() -> None:
        nonlocal per_tree_vlines
        if per_tree_vlines:
            return
        for _ in range(7):
            per_tree_vlines.append(tk.Frame(tree_per, bg="#c0c0c0", width=1, highlightthickness=0))

    def _position_per_tree_vlines(_e: tk.Event | None = None) -> None:
        _ensure_per_tree_vlines()
        cols = ["per_pad", "cad", "last", "next", "cat", "acc1", "acc2"]
        x = 0
        x_offset = 1
        for i, cid in enumerate(cols):
            try:
                w = int(tree_per.column(cid, "width"))
            except Exception:
                w = 0
            x += w
            per_tree_vlines[i].place(x=x + x_offset, y=0, relheight=1.0)
            per_tree_vlines[i].lift()

    def _sync_per_mov_hdr_layout(_e: tk.Event | None = None) -> None:
        cols_full = ["per_pad", "cad", "last", "next", "cat", "acc1", "acc2", "chq"]
        for i, cid in enumerate(cols_full):
            try:
                w = max(0, int(tree_per.column(cid, "width")))
            except Exception:
                w = 0
            per_mov_hdr.grid_columnconfigure(i, minsize=w, weight=0)
        _position_per_mov_hdr_vlines()
        _position_per_tree_vlines()

    per_mov_hdr.bind("<Configure>", _sync_per_mov_hdr_layout, add=True)
    tree_per.bind("<Configure>", _sync_per_mov_hdr_layout, add=True)

    _yscroll_per_lock: list[bool] = [False]

    def _per_yscroll_main(first: str, last: str) -> None:
        if _yscroll_per_lock[0]:
            return
        _yscroll_per_lock[0] = True
        try:
            tree_per_scroll_y.set(first, last)
            f = float(first)
            tree_per_amt.yview_moveto(f)
            tree_per_note.yview_moveto(f)
        finally:
            _yscroll_per_lock[0] = False

    def _per_yscroll_amt(first: str, last: str) -> None:
        if _yscroll_per_lock[0]:
            return
        _yscroll_per_lock[0] = True
        try:
            tree_per_scroll_y.set(first, last)
            f = float(first)
            tree_per.yview_moveto(f)
            tree_per_note.yview_moveto(f)
        finally:
            _yscroll_per_lock[0] = False

    def _per_yscroll_note(first: str, last: str) -> None:
        if _yscroll_per_lock[0]:
            return
        _yscroll_per_lock[0] = True
        try:
            tree_per_scroll_y.set(first, last)
            f = float(first)
            tree_per.yview_moveto(f)
            tree_per_amt.yview_moveto(f)
        finally:
            _yscroll_per_lock[0] = False

    tree_per.configure(yscrollcommand=_per_yscroll_main)
    tree_per_amt.configure(yscrollcommand=_per_yscroll_amt)
    tree_per_note.configure(yscrollcommand=_per_yscroll_note)
    tree_per_scroll_y.config(command=tree_per.yview)
    tree_per_scroll_x.config(command=tree_per.xview)

    sep_1 = tk.Frame(per_tree_frame, bg=header_bg, width=_SEP_CH_W)
    sep_2 = tk.Frame(per_tree_frame, bg=header_bg, width=_SEP_CH_W)
    sep_1_line = tk.Frame(sep_1, bg="#c0c0c0", width=1)
    sep_2_line = tk.Frame(sep_2, bg="#c0c0c0", width=1)

    per_tree_frame.grid_columnconfigure(0, weight=1, minsize=120)
    per_tree_frame.grid_columnconfigure(1, weight=0, minsize=_SEP_CH_W)
    per_tree_frame.grid_columnconfigure(2, weight=0, minsize=104)
    per_tree_frame.grid_columnconfigure(3, weight=0, minsize=_SEP_CH_W)
    per_tree_frame.grid_columnconfigure(4, weight=1, minsize=100)
    per_tree_frame.grid_columnconfigure(5, weight=0, minsize=20)
    per_tree_frame.grid_rowconfigure(1, weight=1)

    header_row.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 2))
    tree_per.grid(row=1, column=0, sticky="nsew")
    sep_1.grid(row=1, column=1, sticky="nsw")
    tree_per_amt.grid(row=1, column=2, sticky="nsew")
    sep_2.grid(row=1, column=3, sticky="nsw")
    tree_per_note.grid(row=1, column=4, sticky="nsew")
    tree_per_scroll_y.grid(row=1, column=5, sticky="ns", padx=(2, 0))
    tree_per_scroll_x.grid(row=2, column=0, columnspan=5, sticky="ew")
    sep_1_line.place(x=-3, y=0, relheight=1.0)
    sep_2_line.place(x=-3, y=0, relheight=1.0)
    root.after(0, _sync_per_mov_hdr_layout)

    _PER_TREE_ROW_PX = 22

    def _per_apply_tree_visible_rows() -> None:
        per_tree_rows_sched[0] = None
        try:
            th = int(per_tree_frame.winfo_height())
            hh = int(header_row.winfo_height())
        except tk.TclError:
            return
        if th < 48:
            return
        try:
            xbh = int(tree_per_scroll_x.winfo_height())
        except tk.TclError:
            xbh = 0
        avail = th - hh - max(xbh, 12) - 2
        rows = max(6, min(80, avail // _PER_TREE_ROW_PX))
        try:
            if int(tree_per.cget("height")) == rows:
                return
        except Exception:
            pass
        for _tv in (tree_per, tree_per_amt, tree_per_note):
            _tv.configure(height=rows)
        root.after_idle(_sync_per_mov_hdr_layout)

    def _per_schedule_tree_visible_rows(_e: tk.Event | None = None) -> None:
        sid = per_tree_rows_sched
        if sid[0] is not None:
            try:
                root.after_cancel(sid[0])
            except Exception:
                pass
        sid[0] = root.after(60, _per_apply_tree_visible_rows)

    per_tree_frame.bind("<Configure>", _per_schedule_tree_visible_rows, add=True)
    root.after_idle(_per_schedule_tree_visible_rows)

    per_title_row.pack(fill=tk.X, anchor=tk.W, pady=(4, 0))
    per_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(2, 2))

    per_title_center = tk.Frame(per_top_block, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_title_center.pack(anchor=tk.CENTER, pady=(0, 0))
    tk.Label(
        per_title_center,
        textvariable=nuovi_immissione_title_var,
        font=newreg_ui_font,
        anchor="w",
        justify="left",
        width=_NUOVI_TITLE_LBL_CH,
        bg=MOVIMENTI_PAGE_BG,
        fg="#1a1a1a",
        highlightthickness=0,
    ).pack(anchor=tk.CENTER)

    per_form = tk.Frame(per_top_block, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    per_form.pack(fill=tk.X, anchor=tk.W, pady=(0, 2))

    _per_py, _per_px = 2, 6
    ttk.Label(per_form, textvariable=per_date_field_lbl_var, style="NewReg.TLabel").grid(
        row=0, column=0, sticky="w", pady=_per_py, padx=(0, _per_px)
    )
    row_per_start = tk.Frame(per_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ent_per_start = ttk.Entry(row_per_start, textvariable=per_start_date_var, width=_NR_W_DATE, style="NewReg.TEntry")
    ent_per_start.pack(side=tk.LEFT)
    btn_per_oggi = ttk.Button(row_per_start, text="Oggi", style="NewReg.TButton")
    btn_per_oggi.pack(side=tk.LEFT, padx=(6, 0))
    row_per_start.grid(row=0, column=1, sticky="w", pady=_per_py)

    def _normalize_per_start_date_display() -> None:
        raw = (per_start_date_var.get() or "").strip()
        if raw == _NEWREG_DATE_MASK:
            return
        iso = parse_italian_ddmmyyyy_to_iso(raw)
        if not iso:
            return
        dmin, dmax = immissione_date_bounds()
        dsel = date.fromisoformat(iso)
        if dsel < dmin:
            dsel = dmin
        if dsel > dmax:
            dsel = dmax
        per_start_date_var.set(to_italian_date(dsel.isoformat()))

    def _per_start_date_keypress(event: tk.Event) -> str | None:
        return _immissione_date_masked_keypress(
            event, entry=ent_per_start, var=per_start_date_var, on_complete=lambda: None
        )

    def _open_per_start_calendar_popup() -> None:
        dmin, dmax = immissione_date_bounds()
        today = date.today()
        cur_iso = parse_italian_ddmmyyyy_to_iso(per_start_date_var.get()) or today.isoformat()
        try:
            cur = date.fromisoformat(cur_iso)
        except Exception:
            cur = today
        cur = max(dmin, min(cur, dmax))

        def _on_pick(dsel: date) -> None:
            per_start_date_var.set(to_italian_date(dsel.isoformat()))
            per_start_date_manual_mode[0] = False

        top = build_immissione_calendar_toplevel(
            root,
            title="Seleziona data",
            anchor=ent_per_start,
            field_min=dmin,
            field_max=dmax,
            current=cur,
            on_date_chosen=_on_pick,
            ui_font=filter_ui_font,
        )
        per_start_calendar_popup[0] = top

        def _on_ps_destroy(_e: tk.Event | None = None) -> None:
            per_start_calendar_popup[0] = None

        top.bind("<Destroy>", _on_ps_destroy)

    def _toggle_per_start_date_calendar() -> None:
        if per_start_date_manual_mode[0]:
            per_start_date_manual_mode[0] = False
            if per_start_date_restore_iso[0]:
                try:
                    per_start_date_var.set(to_italian_date(per_start_date_restore_iso[0]))
                except Exception:
                    pass
                per_start_date_restore_iso[0] = None
            else:
                _normalize_per_start_date_display()
            _open_per_start_calendar_popup()
            return
        if per_start_calendar_popup[0] is not None:
            try:
                per_start_calendar_popup[0].destroy()
            except Exception:
                pass
            per_start_calendar_popup[0] = None
            per_start_date_manual_mode[0] = True
            iso = parse_italian_ddmmyyyy_to_iso(per_start_date_var.get())
            per_start_date_restore_iso[0] = iso if iso else date.today().isoformat()
            per_start_date_var.set(_NEWREG_DATE_MASK)
            try:
                ent_per_start.focus_set()
                ent_per_start.icursor(0)
            except Exception:
                pass
            return
        _open_per_start_calendar_popup()

    def _per_start_date_button1(_e: tk.Event) -> str:
        _toggle_per_start_date_calendar()
        return "break"

    ent_per_start.bind("<KeyPress>", _per_start_date_keypress)
    ent_per_start.bind("<FocusOut>", lambda _e: _normalize_per_start_date_display())
    ent_per_start.bind("<Button-1>", _per_start_date_button1)

    ttk.Label(per_form, text="Cadenza", style="NewReg.TLabel").grid(row=1, column=0, sticky="nw", pady=_per_py, padx=(0, _per_px))
    _per_cadence_labels: dict[str, tk.Label] = {}

    def _per_refresh_cadence_button_styles() -> None:
        cid = (per_cadence_var.get() or "monthly").strip()
        if cid not in periodiche.CADENCE_IDS:
            cid = "monthly"
            per_cadence_var.set(cid)
        on_bg = security_auth.CDC_TIPO_TASTI_BTN_ACTIVE_BG
        off_bg = security_auth.CDC_TIPO_TASTI_BTN_BG
        for k, lbl in _per_cadence_labels.items():
            is_on = k == cid
            lbl.configure(bg=on_bg if is_on else off_bg, fg=security_auth.CDC_TIPO_TASTI_BTN_FG,
                          relief=tk.SUNKEN if is_on else tk.RAISED, bd=2 if is_on else 1)

    def _per_set_cadence_pick(cadence_id: str) -> None:
        per_cadence_var.set(cadence_id)
        _per_refresh_cadence_button_styles()

    col_cad = tk.Frame(per_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    # Larghezza fissa (caratteri) per «Quadrimestrale», la più lunga tra le etichette.
    _per_cad_toggle_w = 12
    _cad_font = ("TkDefaultFont", 10)
    _ncad = len(periodiche.CADENCE_CHOICES)
    _row1_n = (_ncad + 1) // 2
    for i, (cid, lab) in enumerate(periodiche.CADENCE_CHOICES):
        r = 0 if i < _row1_n else 1
        c = i if i < _row1_n else i - _row1_n
        lb = tk.Label(
            col_cad,
            text=lab,
            font=_cad_font,
            width=_per_cad_toggle_w,
            anchor=tk.CENTER,
            padx=2,
            pady=4,
            cursor="hand2",
            highlightthickness=0,
            relief=tk.RAISED,
            bd=1,
            bg=security_auth.CDC_TIPO_TASTI_BTN_BG,
            fg=security_auth.CDC_TIPO_TASTI_BTN_FG,
        )
        lb.grid(row=r, column=c, padx=2, pady=2, sticky="nw")
        lb.bind("<Button-1>", lambda e, c_id=cid: _per_set_cadence_pick(c_id))
        _per_cadence_labels[cid] = lb
    _per_refresh_cadence_button_styles()
    col_cad.grid(row=1, column=1, columnspan=3, sticky="nw", pady=_per_py)
    ttk.Label(per_form, text="Categoria", style="NewReg.TLabel").grid(row=2, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
    cb_per_cat = ttk.Combobox(per_form, textvariable=per_cat_var, state="readonly", width=_NR_W_CAT, style="NewReg.TCombobox")
    cb_per_cat.grid(row=2, column=1, columnspan=2, sticky="w", pady=_per_py)
    ttk.Label(per_form, textvariable=per_cat_note_var, style="NewRegNote.TLabel").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(0, 2)
    )
    ttk.Label(per_form, text="Conto", style="NewReg.TLabel").grid(row=4, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
    cb_per_acc1 = ttk.Combobox(per_form, textvariable=per_acc1_var, state="readonly", width=_NR_W_ACC, style="NewReg.TCombobox")
    cb_per_acc1.grid(row=4, column=1, columnspan=2, sticky="w", pady=_per_py)
    lbl_per_acc2 = ttk.Label(per_form, text="Secondo conto", style="NewReg.TLabel")
    row_per_acc2 = tk.Frame(per_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    cb_per_acc2 = ttk.Combobox(row_per_acc2, textvariable=per_acc2_var, state="readonly", width=_NR_W_ACC, style="NewReg.TCombobox")
    cb_per_acc2.pack(side=tk.LEFT)
    lbl_per_acc2.grid(row=5, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
    row_per_acc2.grid(row=5, column=1, columnspan=2, sticky="w", pady=_per_py)
    ttk.Label(per_form, text="Importo (€)", style="NewReg.TLabel").grid(row=6, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
    row_per_amt = tk.Frame(per_form, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    ent_per_amt = ttk.Entry(row_per_amt, textvariable=per_amount_var, width=_NR_W_AMT, style="NewReg.TEntry")
    ent_per_amt.pack(side=tk.LEFT)
    btn_per_plus = tk.Label(row_per_amt, text="+", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#e0f2f1", relief=tk.RAISED, bd=1)
    btn_per_minus = tk.Label(row_per_amt, text="-", cursor="hand2", font=newreg_ui_font, padx=6, pady=2, bg="#ffebee", relief=tk.RAISED, bd=1)
    btn_per_plus.pack(side=tk.LEFT, padx=(6, 2))
    btn_per_minus.pack(side=tk.LEFT)
    row_per_amt.grid(row=6, column=1, sticky="w", pady=_per_py)
    ttk.Label(per_form, text="Nota", style="NewReg.TLabel").grid(row=7, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
    ent_per_note = ttk.Entry(per_form, textvariable=per_note_var, width=_NR_W_NOTE, style="NewReg.TEntry")
    ent_per_note.grid(row=7, column=1, columnspan=3, sticky="w", pady=_per_py)
    bind_entry_first_char_uppercase(per_note_var, ent_per_note)

    row_per_btns = tk.Frame(per_top_block, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    row_per_btns.pack(fill=tk.X, pady=(2, 0), anchor=tk.W)
    btn_per_confirm = ttk.Button(row_per_btns, text="Conferma creazione", style="NewReg.TButton")
    btn_per_clear = ttk.Button(row_per_btns, text="Cancella valori", style="NewReg.TButton")
    btn_per_confirm.grid(row=0, column=0, padx=(0, 8), sticky="w")
    btn_per_clear.grid(row=0, column=1, padx=(0, 8), sticky="w")
    tk.Label(
        per_top_block,
        textvariable=per_status_var,
        bg=MOVIMENTI_PAGE_BG,
        fg="#555555",
        font=("TkDefaultFont", 10),
        highlightthickness=0,
    ).pack(fill=tk.X, anchor=tk.W, pady=(2, 0))

    def _per_refresh_form_title() -> None:
        if nuovi_submode[0] == "periodiche":
            nuovi_immissione_title_var.set(
                "Modifica registrazione periodica"
                if per_edit_rule_id[0]
                else "Nuova registrazione periodica"
            )
        per_date_field_lbl_var.set(
            "Prossima creazione" if per_edit_rule_id[0] else "Prima scadenza"
        )
        btn_per_confirm.configure(
            text="Conferma modifica" if per_edit_rule_id[0] else "Conferma creazione"
        )

    _per_refresh_form_title()

    per_form.grid_columnconfigure(0, weight=0)
    per_form.grid_columnconfigure(1, weight=0)
    per_form.grid_columnconfigure(2, weight=0)
    per_form.grid_columnconfigure(3, weight=0)

    def _per_selected_category_code() -> str:
        try:
            idx = int(cb_per_cat.current())
        except Exception:
            idx = -1
        if 0 <= idx < len(cat_opts_cache):
            return cat_opts_cache[idx][1]
        return per_cat_code_var.get().strip()

    def _per_set_category_by_code(code: str) -> None:
        target_idx = next((i for i, (_n, c) in enumerate(cat_opts_cache) if c == code), -1)
        if target_idx >= 0:
            try:
                cb_per_cat.current(target_idx)
            except Exception:
                per_cat_var.set(cat_opts_cache[target_idx][0])
            per_cat_code_var.set(cat_opts_cache[target_idx][1])
        elif cat_opts_cache:
            try:
                cb_per_cat.current(0)
            except Exception:
                per_cat_var.set(cat_opts_cache[0][0])
            per_cat_code_var.set(cat_opts_cache[0][1])

    def _per_consumi_ordinari_code() -> str:
        for n, c in cat_opts_cache:
            nn = " ".join((n or "").strip().lower().replace(".", " ").replace("/", " / ").split())
            if "consumi ordinari" in nn:
                return c
        return ""

    def _per_cassa_account_name() -> str:
        for n, _c in acc_opts_cache:
            if (n or "").strip().lower() == "cassa":
                return n
        return ""

    def _per_apply_periodic_creation_defaults() -> None:
        if not cat_opts_cache or not acc_opts_cache:
            return
        co = _per_consumi_ordinari_code()
        if co:
            _per_set_category_by_code(co)
        else:
            _per_set_category_by_code(cat_opts_cache[0][1])
        cn = _per_cassa_account_name()
        per_acc1_var.set(cn if cn else acc_opts_cache[0][0])

    def _per_apply_periodic_defaults_if_unfilled() -> None:
        if not cat_opts_cache or not acc_opts_cache:
            return
        if (per_cat_var.get() or "").strip() and (per_acc1_var.get() or "").strip():
            return
        _per_apply_periodic_creation_defaults()

    def _per_apply_sign(sign: str) -> None:
        if _is_giro_label(per_cat_var.get()) and sign == "+":
            sign = "-"
        per_sign_var.set(sign)
        raw = (per_amount_var.get() or "").strip().replace(" ", "")
        if not raw:
            return
        if raw.startswith(("+", "-")):
            raw = raw[1:]
        per_amount_var.set((("-" if sign == "-" else "+") + raw).strip())

    def _per_format_amount_entry() -> None:
        raw = (per_amount_var.get() or "").strip()
        if not raw:
            return
        try:
            amt = normalize_euro_input(raw)
            if _is_giro_label(per_cat_var.get()):
                amt = -abs(amt)
            elif per_sign_var.get() == "-":
                amt = -abs(amt)
            else:
                amt = abs(amt)
            txt = format_euro_it(abs(amt))
            per_amount_var.set(("-" if amt < 0 else "+") + txt)
            if _is_giro_label(per_cat_var.get()):
                per_sign_var.set("-")
        except Exception:
            pass

    def _per_sync_cat_and_second() -> None:
        cb_per_cat.configure(values=[n for n, _c in cat_opts_cache])
        try:
            _cv = list(cb_per_cat.cget("values"))
            _cn = (per_cat_var.get() or "").strip()
            if _cv and _cn and _cn in _cv:
                cb_per_cat.set(_cn)
        except Exception:
            pass
        nm_cat = (per_cat_var.get() or "").strip()
        if nm_cat:
            match_cd = next((c for n, c in cat_opts_cache if n == nm_cat), "")
            if match_cd:
                per_cat_code_var.set(match_cd)
        code = per_cat_code_var.get().strip()
        if not code:
            code = next((c for n, c in cat_opts_cache if n == per_cat_var.get()), "")
            per_cat_code_var.set(code)
        per_cat_note_var.set(cat_note_by_code_cache.get(code, "-") or "-")
        is_giro = _is_giro_label(per_cat_var.get())
        if is_giro:
            _per_apply_sign("-")
        else:
            sign = cat_sign_by_code_cache.get(code, "")
            if sign == "+":
                _per_apply_sign("+")
            elif sign in ("-", "="):
                _per_apply_sign("-")
        if is_giro:
            lbl_per_acc2.grid(row=5, column=0, sticky="w", pady=_per_py, padx=(0, _per_px))
            row_per_acc2.grid(row=5, column=1, columnspan=2, sticky="w", pady=_per_py)
            if not per_acc2_var.get() and acc_opts_cache:
                names = [n for n, _c in acc_opts_cache]
                pick = names[1] if len(names) > 1 else names[0]
                if pick == per_acc1_var.get() and len(names) > 1:
                    pick = names[0]
                per_acc2_var.set(pick)
            if per_acc1_var.get().strip() and per_acc1_var.get().strip() == per_acc2_var.get().strip():
                if acc_opts_cache:
                    for n, _c in acc_opts_cache:
                        if n != per_acc1_var.get().strip():
                            per_acc2_var.set(n)
                            break
            if not (per_note_var.get() or "").strip() or (per_note_var.get() or "").strip() == "-":
                per_note_var.set("Giroconto")
        else:
            lbl_per_acc2.grid_remove()
            row_per_acc2.grid_remove()
            per_acc2_var.set("")

    def _per_refresh_options() -> None:
        cb_per_acc1.configure(values=[n for n, _c in acc_opts_cache])
        cb_per_acc2.configure(values=[n for n, _c in acc_opts_cache])
        _per_sync_cat_and_second()

    def _per_sync_cadence_combo() -> None:
        cid = (per_cadence_var.get() or "monthly").strip()
        if cid not in periodiche.CADENCE_IDS:
            cid = "monthly"
            per_cadence_var.set(cid)
        _per_refresh_cadence_button_styles()

    def _per_rule_amt_display_and_tag(rule: dict) -> tuple[str, str]:
        tpl = rule.get("template") or {}
        try:
            amt_dec = to_decimal(str(tpl.get("amount_eur") or "0"))
        except Exception:
            return (str(tpl.get("amount_eur") or ""), "pos")
        if amt_dec < 0:
            return (format_euro_it(amt_dec), "neg")
        return ("+" + format_euro_it(abs(amt_dec)), "pos")

    def _per_rule_tree_values(rule: dict) -> tuple[str, ...]:
        tpl = rule.get("template") or {}
        cad = periodiche.cadence_label(str(rule.get("cadence") or ""))
        last_m = rule.get("last_materialized_iso")
        if last_m:
            try:
                last_it = to_italian_date(str(last_m)[:10])
            except Exception:
                last_it = ""
        else:
            last_it = ""
        if not rule.get("active", True):
            next_it = "—"
        else:
            nd = periodiche.next_due_date(rule)
            next_it = to_italian_date(nd.isoformat()) if nd else ""
        cat = category_display_name(str(tpl.get("category_name") or ""))
        apt = str(tpl.get("account_primary_name") or "")
        if tpl.get("is_giroconto"):
            ap2 = str(tpl.get("account_secondary_name") or "")
        else:
            ap2 = "—"
        chq = "Periodica"
        return ("", cad, last_it, next_it, cat, apt, ap2, chq)

    def _per_rule_note_cell(rule: dict) -> str:
        tpl = rule.get("template") or {}
        n = str(tpl.get("note") or "")
        if not n or n == "-":
            return "—"
        return n

    def _per_refresh_tree() -> None:
        tree_per.delete(*tree_per.get_children())
        tree_per_amt.delete(*tree_per_amt.get_children())
        tree_per_note.delete(*tree_per_note.get_children())
        row_i = 0
        for rule in cur_db().get("periodic_registrations", []):
            rid = str(rule.get("id", ""))
            if not rid:
                continue
            stripe = f"stripe{row_i % 2}"
            row_i += 1
            tree_per.insert("", tk.END, iid=rid, values=_per_rule_tree_values(rule), tags=(stripe,))
            amt_txt, amt_tag = _per_rule_amt_display_and_tag(rule)
            tree_per_amt.insert("", tk.END, iid=rid, values=(amt_txt,), tags=(amt_tag, stripe))
            tree_per_note.insert("", tk.END, iid=rid, values=(_per_rule_note_cell(rule),), tags=(stripe,))
        _per_refresh_action_buttons()
        root.after_idle(_sync_per_mov_hdr_layout)

    def _per_clear_form() -> None:
        per_edit_rule_id[0] = None
        try:
            tree_per.selection_remove(*tree_per.selection())
        except Exception:
            pass
        try:
            tree_per_amt.selection_remove(*tree_per_amt.selection())
        except Exception:
            pass
        try:
            tree_per_note.selection_remove(*tree_per_note.selection())
        except Exception:
            pass
        per_cadence_var.set("monthly")
        per_amount_var.set("")
        per_sign_var.set("+")
        per_note_var.set("")
        _per_apply_periodic_creation_defaults()
        per_acc2_var.set("")
        _per_sync_cadence_combo()
        _per_sync_cat_and_second()
        per_status_var.set("")
        per_follow_grid_selection[0] = False
        per_start_date_manual_mode[0] = False
        per_start_date_restore_iso[0] = None
        pop_ps = per_start_calendar_popup[0]
        if pop_ps is not None:
            try:
                if pop_ps.winfo_exists():
                    pop_ps.destroy()
            except Exception:
                pass
            per_start_calendar_popup[0] = None
        dmin, dmax = immissione_date_bounds()
        tdy = max(dmin, min(date.today(), dmax))
        per_start_date_var.set(to_italian_date(tdy.isoformat()))
        _per_refresh_form_title()
        _per_refresh_action_buttons()

    def _per_current_selected_id() -> str | None:
        sel = tree_per.selection()
        if sel:
            return str(sel[0])
        sel_a = tree_per_amt.selection()
        if sel_a:
            return str(sel_a[0])
        sel_n = tree_per_note.selection()
        if sel_n:
            return str(sel_n[0])
        try:
            foc = str(tree_per.focus() or "").strip()
        except Exception:
            foc = ""
        return foc or None

    def _per_refresh_action_buttons() -> None:
        rid = _per_current_selected_id()
        if rid:
            btn_per_edit_future.pack(side=tk.LEFT, padx=(0, 8))
            btn_per_delete.pack(side=tk.LEFT)
        else:
            btn_per_edit_future.pack_forget()
            btn_per_delete.pack_forget()

    def _per_collect_template_and_dates() -> tuple[dict, str] | None:
        d_iso = parse_italian_ddmmyyyy_to_iso(per_start_date_var.get())
        if not d_iso:
            messagebox.showerror("Registrazioni periodiche", "Data prima scadenza non valida (gg/mm/aaaa).")
            return None
        dsel = date.fromisoformat(d_iso)
        dmin, dmax = immissione_date_bounds()
        if dsel < dmin or dsel > dmax:
            messagebox.showerror(
                "Registrazioni periodiche",
                "Data fuori intervallo consentito (da −1 anno a +1 anno rispetto a oggi).",
            )
            return None
        cad = (per_cadence_var.get() or "").strip()
        if cad not in periodiche.CADENCE_IDS:
            messagebox.showerror("Registrazioni periodiche", "Seleziona una cadenza.")
            return None
        cat_name = (per_cat_var.get() or "").strip()
        cat_code = _per_selected_category_code() or per_cat_code_var.get().strip()
        if not cat_code:
            messagebox.showerror("Registrazioni periodiche", "Categoria obbligatoria.")
            return None
        if virtuale_discharge_active[0] and _is_giro_label(cat_name):
            messagebox.showerror(
                "Registrazioni periodiche",
                "Durante lo scarico del saldo virtuale non è possibile usare una Girata conto/conto.",
            )
            return None
        acc1_name = per_acc1_var.get().strip()
        acc1_code = next((c for n, c in acc_opts_cache if n == acc1_name), "")
        if not acc1_code:
            messagebox.showerror("Registrazioni periodiche", "Conto obbligatorio.")
            return None
        giro = _is_giro_label(cat_name)
        acc2_name = per_acc2_var.get().strip() if giro else ""
        acc2_code = next((c for n, c in acc_opts_cache if n == acc2_name), "") if giro else ""
        if giro and (not acc2_code or acc2_code == acc1_code):
            messagebox.showerror(
                "Registrazioni periodiche",
                "Nel giroconto il secondo conto è obbligatorio e diverso dal primo.",
            )
            return None
        raw_amt = (per_amount_var.get() or "").strip()
        if not raw_amt:
            messagebox.showerror("Registrazioni periodiche", "Importo obbligatorio.")
            return None
        try:
            amt = normalize_euro_input(raw_amt)
        except Exception as exc:
            messagebox.showerror("Registrazioni periodiche", str(exc))
            return None
        if giro:
            amt = -abs(amt)
        elif per_sign_var.get() == "-":
            amt = -abs(amt)
        else:
            amt = abs(amt)
        if amt == Decimal("0.00"):
            messagebox.showerror("Registrazioni periodiche", "Importo a zero non ammesso.")
            return None
        chq = sanitize_single_line_text("Periodica", max_len=MAX_CHEQUE_LEN)
        note = sanitize_single_line_text(per_note_var.get() or "", max_len=MAX_RECORD_NOTE_LEN)
        if not note:
            note = "-"
        tpl = {
            "category_code": cat_code,
            "category_name": cat_raw_name_by_code_cache.get(cat_code, cat_name),
            "category_note": cat_note_by_code_cache.get(cat_code, "") or "",
            "account_primary_code": acc1_code,
            "account_primary_flags": "",
            "account_primary_with_flags": acc1_code,
            "account_primary_name": acc1_name,
            "account_secondary_code": acc2_code if giro else "",
            "account_secondary_flags": "",
            "account_secondary_name": acc2_name if giro else "",
            "amount_eur": format_money(amt),
            "note": note,
            "cheque": chq,
            "is_giroconto": giro,
        }
        return tpl, d_iso

    def _per_conferma_immissione() -> None:
        got = _per_collect_template_and_dates()
        if got is None:
            return
        tpl, start_iso = got
        rid_edit = per_edit_rule_id[0]
        if not messagebox.askyesno(
            "Registrazioni periodiche",
            "Confermi la modifica della registrazione periodica nel database?"
            if rid_edit
            else "Confermi la creazione della registrazione periodica nel database?",
        ):
            return
        periodiche.ensure_periodic_registrations(cur_db())
        rules = cur_db()["periodic_registrations"]
        appended = False
        if rid_edit:
            rule = next((r for r in rules if str(r.get("id")) == rid_edit), None)
            if rule is None:
                messagebox.showerror("Registrazioni periodiche", "Voce non trovata nell'elenco.")
                return
            rule["cadence"] = per_cadence_var.get().strip()
            rule["start_anchor_iso"] = start_iso
            lm_old = rule.get("last_materialized_iso")
            if lm_old and str(lm_old).strip() and rule.get("active", True):
                cad_e = str(rule.get("cadence") or "").strip()
                if cad_e in periodiche.CADENCE_IDS:
                    try:
                        d_new = date.fromisoformat(start_iso[:10])
                        rule["last_materialized_iso"] = periodiche.previous_by_cadence(
                            d_new, cad_e
                        ).isoformat()
                    except Exception:
                        pass
            rule["template"] = tpl
            rule["active"] = True
        else:
            rule = {
                "id": periodiche.new_rule_id(),
                "active": True,
                "cadence": per_cadence_var.get().strip(),
                "start_anchor_iso": start_iso,
                "template": tpl,
            }
            rules.append(rule)
            appended = True
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            if appended:
                rules.pop()
            messagebox.showerror("Registrazioni periodiche", str(exc))
            return
        today = date.today()
        n = periodiche.materialize_all_due(cur_db(), today)
        if n > 0:
            try:
                save_encrypted_db_dual(
                    cur_db(),
                    Path(data_file_var.get()),
                    Path(key_file_var.get()),
                )
            except Exception as exc:
                messagebox.showerror("Registrazioni periodiche", str(exc))
                return
            _movements_dirty[0] = True
            refresh_balance_footer()
            messagebox.showinfo(
                "Registrazioni periodiche",
                f"Sono state create {n} registrazioni da questa creazione o da scadenze arretrate.",
            )
        _per_refresh_tree()
        if rid_edit:
            per_status_var.set("Modifiche registrate (valgono solo per le creazioni future).")
        else:
            per_status_var.set("Creazione registrata.")
        _per_clear_form()
        _per_refresh_action_buttons()
        try:
            ent_per_start.focus_set()
        except Exception:
            pass

    def _per_delete_selected() -> None:
        rid = _per_current_selected_id()
        if not rid:
            messagebox.showinfo("Registrazioni periodiche", "Seleziona una riga nell'elenco.")
            return
        if not messagebox.askyesno(
            "Registrazioni periodiche",
            "Le registrazioni già create nel database non verranno modificate né eliminate. "
            "Confermi l'eliminazione di questa registrazione periodica (solo creazioni future)?",
        ):
            return
        regs = list(cur_db().get("periodic_registrations", []))
        new_regs = [r for r in regs if str(r.get("id")) != rid]
        if len(new_regs) == len(regs):
            messagebox.showerror("Registrazioni periodiche", "Voce non trovata.")
            return
        cur_db()["periodic_registrations"] = new_regs
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            cur_db()["periodic_registrations"] = regs
            messagebox.showerror("Registrazioni periodiche", str(exc))
            return
        if per_edit_rule_id[0] == rid:
            _per_clear_form()
        per_status_var.set("Eliminata dalle creazioni future.")
        _per_refresh_tree()
        _per_refresh_action_buttons()

    def _per_load_selected_rule_into_form() -> None:
        rid = _per_current_selected_id()
        if not rid:
            return
        rule = next((r for r in cur_db().get("periodic_registrations", []) if str(r.get("id")) == rid), None)
        if rule is None:
            return
        per_edit_rule_id[0] = rid
        tpl = rule.get("template") or {}
        anc = rule.get("start_anchor_iso")
        active = rule.get("active", True)
        nd = periodiche.next_due_date(rule) if active else None
        if nd is not None:
            per_start_date_var.set(to_italian_date(nd.isoformat()))
        elif anc:
            per_start_date_var.set(to_italian_date(str(anc)[:10]))
        else:
            per_start_date_var.set(to_italian_date(date.today().isoformat()))
        per_cadence_var.set(str(rule.get("cadence") or "monthly"))
        code = str(tpl.get("category_code") or "")
        if code:
            _per_set_category_by_code(code)
        else:
            per_cat_var.set(str(tpl.get("category_name") or ""))
        per_acc1_var.set(str(tpl.get("account_primary_name") or ""))
        if tpl.get("is_giroconto"):
            per_acc2_var.set(str(tpl.get("account_secondary_name") or ""))
        else:
            per_acc2_var.set("")
        try:
            amt_dec = to_decimal(str(tpl.get("amount_eur") or "0"))
        except Exception:
            amt_dec = Decimal("0")
        per_sign_var.set("-" if amt_dec < 0 else "+")
        per_amount_var.set(("-" if amt_dec < 0 else "+") + format_euro_it(abs(amt_dec)))
        per_note_var.set("" if str(tpl.get("note") or "") == "-" else str(tpl.get("note") or ""))
        _per_sync_cadence_combo()
        _per_sync_cat_and_second()
        _per_refresh_form_title()

    def _per_prepare_edit_selected() -> None:
        if not _per_current_selected_id():
            messagebox.showinfo("Registrazioni periodiche", "Seleziona una riga nell'elenco.")
            return
        _per_load_selected_rule_into_form()
        per_follow_grid_selection[0] = True
        per_status_var.set("Modifica la regola e conferma: le registrazioni già create restano invariate.")

    cb_per_cat.bind("<<ComboboxSelected>>", lambda _e: _per_sync_cat_and_second())
    cb_per_acc1.bind("<<ComboboxSelected>>", lambda _e: _per_sync_cat_and_second())
    cb_per_acc2.bind("<<ComboboxSelected>>", lambda _e: _per_sync_cat_and_second())
    ent_per_amt.bind("<FocusOut>", lambda _e: _per_format_amount_entry())
    bind_euro_amount_entry_validation(ent_per_amt, per_amount_var)

    def _per_plus_click(_e: tk.Event) -> str:
        _per_apply_sign("+")
        return "break"

    def _per_minus_click(_e: tk.Event) -> str:
        _per_apply_sign("-")
        return "break"

    btn_per_plus.bind("<Button-1>", _per_plus_click)
    btn_per_minus.bind("<Button-1>", _per_minus_click)
    def _per_oggi_click() -> None:
        dmin, dmax = immissione_date_bounds()
        tdy = max(dmin, min(date.today(), dmax))
        per_start_date_var.set(to_italian_date(tdy.isoformat()))
        per_start_date_manual_mode[0] = False

    btn_per_oggi.configure(command=_per_oggi_click)
    btn_per_confirm.configure(command=_per_conferma_immissione)
    btn_per_clear.configure(command=_per_clear_form)
    btn_per_edit_future.bind("<Button-1>", lambda _e: _per_prepare_edit_selected())
    btn_per_delete.bind("<Button-1>", lambda _e: _per_delete_selected())

    def _per_enter_from_date(_e: tk.Event | None = None) -> str:
        _normalize_per_start_date_display()
        cb_per_cat.focus_set()
        return "break"

    def _per_enter_from_cat(_e: tk.Event | None = None) -> str:
        cb_per_acc1.focus_set()
        return "break"

    def _per_enter_from_acc1(_e: tk.Event | None = None) -> str:
        if _is_giro_label(per_cat_var.get()):
            cb_per_acc2.focus_set()
        else:
            ent_per_amt.focus_set()
        return "break"

    def _per_enter_from_acc2(_e: tk.Event | None = None) -> str:
        ent_per_amt.focus_set()
        return "break"

    def _per_enter_from_amt(_e: tk.Event | None = None) -> str:
        _per_format_amount_entry()
        ent_per_note.focus_set()
        return "break"

    def _per_enter_from_note(_e: tk.Event | None = None) -> str:
        _per_conferma_immissione()
        return "break"

    bind_return_and_kp_enter(ent_per_start, _per_enter_from_date)
    bind_return_and_kp_enter(cb_per_cat, _per_enter_from_cat)
    bind_return_and_kp_enter(cb_per_acc1, _per_enter_from_acc1)
    bind_return_and_kp_enter(cb_per_acc2, _per_enter_from_acc2)
    bind_return_and_kp_enter(ent_per_amt, _per_enter_from_amt)
    bind_return_and_kp_enter(ent_per_note, _per_enter_from_note)

    def _per_tree_select(_e: tk.Event | None = None) -> None:
        def _deferred() -> None:
            rid = _per_current_selected_id()
            if per_follow_grid_selection[0] and rid:
                _per_load_selected_rule_into_form()
                per_status_var.set(
                    "Modifica la regola e conferma: le registrazioni già create restano invariate."
                )
            else:
                # Non azzerare per_edit_rule_id qui: la selezione può essere tolta perché il
                # focus è sul form (es. dopo «Modifica») e la modifica deve restare attiva.
                _per_refresh_form_title()
            _per_refresh_action_buttons()

        root.after_idle(_deferred)

    per_tree_sel_sync: list[bool] = [False]

    def _per_mirror_tree_selection(_e: tk.Event | None = None) -> None:
        if per_tree_sel_sync[0]:
            return
        w = getattr(_e, "widget", None) if _e else tree_per
        if w is tree_per_amt:
            sel = tree_per_amt.selection()
        elif w is tree_per_note:
            sel = tree_per_note.selection()
        else:
            sel = tree_per.selection()
        if (
            tuple(tree_per.selection()) == tuple(sel)
            and tuple(tree_per_amt.selection()) == tuple(sel)
            and tuple(tree_per_note.selection()) == tuple(sel)
        ):
            return
        per_tree_sel_sync[0] = True
        try:
            if sel:
                tree_per.selection_set(*sel)
                tree_per_amt.selection_set(*sel)
                tree_per_note.selection_set(*sel)
            else:
                for t in (tree_per, tree_per_amt, tree_per_note):
                    try:
                        t.selection_remove(*t.selection())
                    except tk.TclError:
                        pass
        finally:
            per_tree_sel_sync[0] = False

    def _per_on_tree_row_select(_e: tk.Event | None = None) -> None:
        _per_mirror_tree_selection(_e)
        _per_tree_select()

    def _per_tree_wheel(event: tk.Event) -> str:
        d = getattr(event, "delta", 0)
        if d:
            u = int(-d / 120)
            tree_per.yview("scroll", u, "units")
            tree_per_amt.yview("scroll", u, "units")
            tree_per_note.yview("scroll", u, "units")
        return "break"

    def _per_tree_wheel_linux(event: tk.Event) -> str:
        if event.num == 4:
            tree_per.yview("scroll", -1, "units")
            tree_per_amt.yview("scroll", -1, "units")
            tree_per_note.yview("scroll", -1, "units")
        elif event.num == 5:
            tree_per.yview("scroll", 1, "units")
            tree_per_amt.yview("scroll", 1, "units")
            tree_per_note.yview("scroll", 1, "units")
        return "break"

    tree_per.bind("<<TreeviewSelect>>", _per_on_tree_row_select)
    tree_per_amt.bind("<<TreeviewSelect>>", _per_on_tree_row_select)
    tree_per_note.bind("<<TreeviewSelect>>", _per_on_tree_row_select)
    tree_per.bind("<MouseWheel>", _per_tree_wheel, add="+")
    tree_per_amt.bind("<MouseWheel>", _per_tree_wheel, add="+")
    tree_per_note.bind("<MouseWheel>", _per_tree_wheel, add="+")
    tree_per.bind("<Button-4>", _per_tree_wheel_linux, add="+")
    tree_per.bind("<Button-5>", _per_tree_wheel_linux, add="+")
    tree_per_amt.bind("<Button-4>", _per_tree_wheel_linux, add="+")
    tree_per_amt.bind("<Button-5>", _per_tree_wheel_linux, add="+")
    tree_per_note.bind("<Button-4>", _per_tree_wheel_linux, add="+")
    tree_per_note.bind("<Button-5>", _per_tree_wheel_linux, add="+")

    def _per_widget_under_list_block(w: tk.Misc | None) -> bool:
        if w is None:
            return False
        cur: tk.Misc | None = w
        while cur is not None:
            if cur is per_list_block:
                return True
            try:
                cur = cur.master
            except tk.TclError:
                break
        return False

    def _per_on_list_area_focus_out(_e: tk.Event) -> None:
        def _check() -> None:
            try:
                foc = root.focus_get()
            except Exception:
                foc = None
            if _per_widget_under_list_block(foc):
                return
            per_tree_sel_sync[0] = True
            try:
                for t in (tree_per, tree_per_amt, tree_per_note):
                    try:
                        t.selection_remove(*t.selection())
                    except tk.TclError:
                        pass
            finally:
                per_tree_sel_sync[0] = False
            _per_refresh_action_buttons()

        root.after(80, _check)

    for _per_foc_w in (tree_per, tree_per_amt, tree_per_note, tree_per_scroll_y, tree_per_scroll_x):
        _per_foc_w.bind("<FocusOut>", _per_on_list_area_focus_out, add="+")

    def _show_mode(mode: str) -> None:
        if mode == "new":
            nuovi_submode[0] = "new"
            nuova_page_outer.pack(fill=tk.BOTH, expand=True)
            periodiche_panel.pack_forget()
            per_follow_grid_selection[0] = False
            _nuovi_sync_subtab_style()
            _populate_form_defaults(keep_last=False)
            nuovi_immissione_title_var.set(newreg_no_var.get())
            try:
                ent_date.focus_set()
            except Exception:
                pass
        else:
            nuovi_submode[0] = "periodiche"
            nuova_page_outer.pack_forget()
            _nuovi_sync_subtab_style()
            _per_refresh_options()
            _per_sync_cadence_combo()
            _per_refresh_tree()
            _per_apply_periodic_defaults_if_unfilled()
            _per_sync_cat_and_second()
            _per_refresh_form_title()
            periodiche_panel.pack(fill=tk.BOTH, expand=True, padx=(0, 8))
            root.after_idle(_per_schedule_tree_visible_rows)

    def _on_cat_selected(_e: tk.Event | None = None) -> None:
        code = _selected_category_code()
        newreg_cat_code_var.set(code)
        _sync_cat_note_and_second_account()

    def _on_acc1_combo(_e: tk.Event | None = None) -> None:
        newreg_last_account_touched[0] = "acc1"
        _sync_cat_note_and_second_account()

    def _on_acc2_combo(_e: tk.Event | None = None) -> None:
        newreg_last_account_touched[0] = "acc2"
        _sync_cat_note_and_second_account()

    cb_cat.bind("<<ComboboxSelected>>", _on_cat_selected)
    cb_acc1.bind("<<ComboboxSelected>>", _on_acc1_combo)
    cb_acc2.bind("<<ComboboxSelected>>", _on_acc2_combo)
    ent_date.bind("<KeyPress>", _newreg_date_keypress)
    ent_date.bind("<FocusOut>", lambda _e: _normalize_newreg_date_display())
    ent_date.bind("<Button-1>", lambda _e: (_toggle_newreg_date_calendar(), "break")[1])
    def _on_oggi_click() -> None:
        dmin, dmax = immissione_date_bounds()
        tdy = max(dmin, min(date.today(), dmax))
        newreg_date_var.set(to_italian_date(tdy.isoformat()))
        newreg_date_manual_mode[0] = False
        _apply_giro_default_note()
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
    bind_return_and_kp_enter(ent_date, _on_date_enter)

    def _calendar_click_under_widgets(widget: tk.Misc, *anchors: tk.Misc) -> bool:
        cur: tk.Misc | None = widget
        while cur is not None:
            if cur in anchors:
                return True
            try:
                cur = cur.master
            except tk.TclError:
                break
        return False

    def _on_global_button1_dismiss_calendars(event: tk.Event) -> None:
        """Chiude i popup calendario (Movimenti + Nuove registrazioni) se il clic è fuori dal popup e dal relativo campo data."""
        w = event.widget
        pops_open: list[tk.Toplevel] = []
        for p in (calendar_popup_from, calendar_popup_to, newreg_calendar_popup[0], per_start_calendar_popup[0]):
            if p is None:
                continue
            try:
                if p.winfo_exists():
                    pops_open.append(p)
            except tk.TclError:
                pass
        if not pops_open:
            return
        for pop in pops_open:
            try:
                if w.winfo_toplevel() == pop:
                    return
            except tk.TclError:
                pass
        if calendar_popup_from is not None or calendar_popup_to is not None:
            if not _calendar_click_under_widgets(w, date_from_entry, date_to_entry):
                _close_calendar("from")
                _close_calendar("to")
        pop_nr = newreg_calendar_popup[0]
        if pop_nr is not None:
            try:
                if pop_nr.winfo_exists() and not _calendar_click_under_widgets(w, ent_date):
                    try:
                        pop_nr.destroy()
                    except Exception:
                        pass
                    newreg_calendar_popup[0] = None
            except tk.TclError:
                newreg_calendar_popup[0] = None
        pop_ps = per_start_calendar_popup[0]
        if pop_ps is not None:
            try:
                if pop_ps.winfo_exists() and not _calendar_click_under_widgets(w, ent_per_start):
                    try:
                        pop_ps.destroy()
                    except Exception:
                        pass
                    per_start_calendar_popup[0] = None
            except tk.TclError:
                per_start_calendar_popup[0] = None

    root.bind_all("<Button-1>", _on_global_button1_dismiss_calendars, add=True)

    def _on_cat_enter(_e: tk.Event) -> str:
        _on_cat_selected()
        try:
            cb_acc1.focus_set()
        except Exception:
            pass
        return "break"
    bind_return_and_kp_enter(cb_cat, _on_cat_enter)

    def _on_acc1_enter(_e: tk.Event) -> str:
        _sync_cat_note_and_second_account()
        try:
            if _is_giro_label(newreg_cat_var.get()) and row_acc2_outer.winfo_ismapped():
                cb_acc2.focus_set()
            else:
                ent_amt.focus_set()
        except Exception:
            pass
        return "break"
    bind_return_and_kp_enter(cb_acc1, _on_acc1_enter)

    def _on_acc2_enter(_e: tk.Event) -> str:
        try:
            ent_amt.focus_set()
        except Exception:
            pass
        return "break"
    bind_return_and_kp_enter(cb_acc2, _on_acc2_enter)
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
            if _is_giro_label(newreg_cat_var.get()):
                amt_chk = -abs(amt_chk)
            else:
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
        _hide_aggiorna_saldo_btn()
        try:
            if _is_cassa_first_account() or _is_virtuale_account(newreg_acc1_var.get()):
                ent_note.focus_set()
            else:
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

    bind_return_and_kp_enter(ent_amt, _on_amt_enter)
    bind_euro_amount_entry_validation(ent_amt, newreg_amount_var)
    def _on_amt_focusout(_e: tk.Event | None = None) -> None:
        raw = (newreg_amount_var.get() or "").strip()
        if raw:
            try:
                v = normalize_euro_input(raw)
                if v != Decimal("0"):
                    _hide_aggiorna_saldo_btn()
            except Exception:
                pass
    ent_amt.bind("<FocusOut>", _on_amt_focusout)
    bind_return_and_kp_enter(ent_chq, _on_chq_enter)
    bind_return_and_kp_enter(ent_note, _on_note_enter)
    btn_plus.bind("<Button-1>", lambda _e: _apply_sign("+"))
    btn_minus.bind("<Button-1>", lambda _e: _apply_sign("-"))
    btn_confirm.configure(command=lambda: _commit_new_record(finish=False))
    bind_return_and_kp_enter(btn_confirm, lambda _e: (_commit_new_record(finish=False), "break")[1])
    btn_finish.configure(command=lambda: _commit_new_record(finish=True))
    btn_clear.configure(command=_clear_values)
    btn_nuova_reg.bind("<Button-1>", lambda _e: _show_mode("new"))
    btn_reg_periodiche.bind("<Button-1>", lambda _e: _show_mode("periodiche"))
    btn_aggiorna_saldo.configure(command=_on_aggiorna_saldo_cassa_click)
    btn_scarica_virtuale.configure(command=_on_scarica_virtuale_click)

    _last_nb_tab: list[int] = [0]

    def _notebook_virtuale_tab_guard(_e: tk.Event | None = None) -> None:
        nonlocal cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache
        try:
            cur = notebook.index(notebook.select())
        except Exception:
            return
        try:
            nuovi_ix = notebook.index(nuovi_dati_frame)
        except Exception:
            nuovi_ix = 1
        try:
            opzioni_ix = notebook.index(opzioni_frame)
        except Exception:
            opzioni_ix = -1
        if virtuale_discharge_active[0] and cur != nuovi_ix and cur != opzioni_ix:
            messagebox.showwarning(
                "Saldo virtuale",
                f"Il saldo virtuale è di {format_euro_it(virtuale_saldo[0])} €.\n"
                "Occorre azzerarlo prima di uscire dall'immissione dati.\n\n"
                "Per un azzeramento di emergenza, usa le Opzioni.",
            )
            try:
                notebook.select(nuovi_dati_frame)
            except Exception:
                pass
            return
        if cur == nuovi_ix:
            try:
                cat_opts_cache, acc_opts_cache, cat_note_by_code_cache, cat_sign_by_code_cache, cat_raw_name_by_code_cache = (
                    _cat_and_acc_options()
                )
                _sync_cat_note_and_second_account()
                cb_per_cat.configure(values=[n for n, _c in cat_opts_cache])
                cb_per_acc1.configure(values=[n for n, _c in acc_opts_cache])
                cb_per_acc2.configure(values=[n for n, _c in acc_opts_cache])
                _per_sync_cat_and_second()
            except Exception:
                pass
        _last_nb_tab[0] = cur

    bind_return_and_kp_enter(ent_saldo, _on_saldo_cassa_enter)
    ent_saldo.bind("<FocusOut>", lambda _e: _on_saldo_cassa_focusout())
    bind_euro_amount_entry_validation(ent_saldo, newreg_saldo_cassa_var, allow_leading_sign=False)
    _show_mode("new")

    pack_centered_page_title(
        verifica_frame, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )
    ttk.Label(verifica_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(
        statistiche_frame, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )
    ttk.Label(statistiche_frame, text="Pagina in preparazione").pack(anchor=tk.W)
    pack_centered_page_title(
        budget_frame, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )
    ttk.Label(budget_frame, text="Pagina in preparazione").pack(anchor=tk.W)

    pack_centered_page_title(
        aiuto_frame, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )
    ttk.Label(aiuto_frame, text="Pagina in preparazione").pack(anchor=tk.W)

    # --- Scheda Categorie e conti (piano conti unico = ultimo anno; correzioni per nuove registrazioni) ---
    pack_centered_page_title(
        plan_conti_frame, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )
    ttk.Label(
        plan_conti_frame,
        text=(
            "Le categorie mostrate sono l’unione di tutti gli anni (per codice) e degli eventuali codici presenti solo nei movimenti — "
            "stessi nomi che puoi selezionare nei filtri di ricerca quando il piano di un singolo anno è incompleto. "
            f"Massimo {MAX_CATEGORIES_COUNT} categorie e {MAX_ACCOUNTS_COUNT} conti. "
            "Salvare aggiorna i nomi nel piano di tutti gli anni; le registrazioni già inserite restano invariate, salvo che non chiedi "
            "esplicitamente di allineare il nome categoria quando la modifica è una piccola correzione riconducibile al nome precedente. "
            "I nomi di «Consumi ordinari» e «Girata conto/conto» e la nota di «Girata conto/conto» non sono modificabili da qui; "
            "il conto «Cassa» non è modificabile da qui. La nota di «Consumi ordinari» è invece libera. "
            "Non è prevista una categoria «dotazione iniziale»: la prima immissione su un conto si fa con una girata da un altro conto. "
            "Sotto le categorie trovi la sezione Conti (scorri se l’elenco è lungo). "
            "Usa «Salva modifiche» per scrivere nel database cifrato."
        ),
        wraplength=760,
    ).pack(anchor=tk.W, pady=(0, 8))

    plan_conti_status_var = tk.StringVar(value="")
    plan_ref_year_var = tk.StringVar(value="")
    plan_cat_rows: list[dict] = []
    plan_acc_rows: list[dict] = []

    plan_conti_scroll_wrap = ttk.Frame(plan_conti_frame, style="MovCdc.TFrame")
    plan_conti_canvas = tk.Canvas(plan_conti_scroll_wrap, highlightthickness=0, bg=MOVIMENTI_PAGE_BG)
    plan_conti_vscroll = ttk.Scrollbar(plan_conti_scroll_wrap, orient="vertical", command=plan_conti_canvas.yview)
    plan_conti_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    plan_conti_vscroll.pack(side=tk.RIGHT, fill=tk.Y)
    plan_conti_inner = ttk.Frame(plan_conti_canvas, style="MovCdc.TFrame")
    plan_conti_inner_win = plan_conti_canvas.create_window((0, 0), window=plan_conti_inner, anchor="nw")

    def _plan_conti_inner_scroll(_e=None) -> None:
        plan_conti_canvas.configure(scrollregion=plan_conti_canvas.bbox("all"))

    def _plan_conti_canvas_evt(e: tk.Event) -> None:
        plan_conti_canvas.itemconfigure(plan_conti_inner_win, width=e.width)

    plan_conti_inner.bind("<Configure>", lambda _e: _plan_conti_inner_scroll())
    plan_conti_canvas.bind("<Configure>", _plan_conti_canvas_evt)
    plan_conti_canvas.configure(yscrollcommand=plan_conti_vscroll.set)
    plan_conti_canvas.bind("<MouseWheel>", lambda e: plan_conti_canvas.yview_scroll(int(-e.delta / 120), "units"))

    lf_cat = ttk.LabelFrame(plan_conti_inner, text="Categorie", padding=8)
    lf_cat.pack(fill=tk.X, expand=False, pady=(0, 8))
    plan_cat_grid = ttk.Frame(lf_cat)
    plan_cat_grid.pack(fill=tk.BOTH, expand=True)
    cat_btns = ttk.Frame(lf_cat)
    cat_btns.pack(fill=tk.X, pady=(8, 0))

    lf_acc = ttk.LabelFrame(plan_conti_inner, text="Conti", padding=8)
    lf_acc.pack(fill=tk.X, expand=False, pady=(0, 8))
    plan_acc_grid = ttk.Frame(lf_acc)
    plan_acc_grid.pack(fill=tk.BOTH, expand=True)
    acc_btns = ttk.Frame(lf_acc)
    acc_btns.pack(fill=tk.X, pady=(8, 0))

    def _plan_latest_bucket() -> dict | None:
        return plan_conti_reference_bucket(cur_db())

    def _append_category_all_years(new_cat: dict) -> None:
        d = cur_db()
        for yb in d.get("years") or []:
            yb.setdefault("categories", []).append(copy.deepcopy(new_cat))

    def _append_account_all_years(new_acc: dict) -> None:
        d = cur_db()
        for yb in d.get("years") or []:
            yb.setdefault("accounts", []).append(copy.deepcopy(new_acc))

    def _reload_plan_conti_form() -> None:
        for w in plan_cat_grid.winfo_children():
            w.destroy()
        for w in plan_acc_grid.winfo_children():
            w.destroy()
        plan_cat_rows.clear()
        plan_acc_rows.clear()
        d = cur_db()
        if not d.get("years"):
            plan_ref_year_var.set("")
            plan_conti_status_var.set("Nessun anno contabile: usa «Prepara anno corrente» o Import legacy.")
            return
        ly = latest_year_bucket(d)
        n_cat = len(merged_categories_for_plan_editor(d))
        n_acc = len(merge_account_charts_across_years(d))
        y_ly = int(ly.get("year", 0)) if ly else 0
        plan_ref_year_var.set(
            f"Categorie: {n_cat} (elenco unificato). Conti: {n_acc}. Saldi in basso riferiti all’anno {y_ly}."
        )
        plan_conti_status_var.set("")
        ttk.Label(plan_cat_grid, text="Cod.", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Label(plan_cat_grid, text="Nome categoria", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(plan_cat_grid, text="Nota", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=2, sticky="w", padx=2, pady=2)
        ttk.Label(plan_cat_grid, text="", width=10).grid(row=0, column=3, sticky="w")
        visible_cats = merged_categories_for_plan_editor(d)

        cat_row_idx = 0
        for c in visible_cats:
            code = str(c.get("code", ""))
            cat_row_idx += 1
            ri = cat_row_idx
            raw_nm = str(c.get("name", "") or "")
            raw_nt = category_row_merged_note(c)
            if plan_conti_category_name_locked(raw_nm):
                nn = " ".join(category_display_name(raw_nm).lower().replace(".", " ").replace("/", " / ").split())
                if ("girata conto / conto" in nn or "girata conto conto" in nn) and not raw_nt:
                    raw_nt = GIRATA_NOTE_DEFAULT
            name_locked = plan_conti_category_name_locked(raw_nm)
            note_locked = plan_conti_category_note_locked(raw_nm)
            nv = tk.StringVar(value=raw_nm)
            vv = tk.StringVar(value=raw_nt)
            plan_cat_rows.append(
                {
                    "code": code,
                    "name": nv,
                    "note": vv,
                    "orig_name": raw_nm,
                    "orig_note": raw_nt,
                    "locked": name_locked,
                }
            )
            ttk.Label(plan_cat_grid, text=code).grid(row=ri, column=0, sticky="w", padx=2, pady=1)
            est_nm = "readonly" if name_locked else "normal"
            est_nt = "readonly" if note_locked else "normal"
            ttk.Entry(plan_cat_grid, textvariable=nv, width=28, state=est_nm).grid(row=ri, column=1, sticky="we", padx=2, pady=1)
            ttk.Entry(plan_cat_grid, textvariable=vv, width=36, state=est_nt).grid(row=ri, column=2, sticky="we", padx=2, pady=1)
            rm_state = "disabled" if name_locked else "normal"

            def _rm_cat(cd: str = code) -> None:
                d = cur_db()
                cat_row = None
                for yb in d.get("years") or []:
                    cat_row = next(
                        (x for x in yb.get("categories", []) if str(x.get("code", "")) == cd),
                        None,
                    )
                    if cat_row is not None:
                        break
                if cat_row is None:
                    messagebox.showwarning(
                        "Categorie e conti",
                        "Questo codice non è presente nel piano di nessun anno (solo nei movimenti): non si può rimuovere da qui.",
                        parent=root,
                    )
                    return
                if plan_conti_category_name_locked(str(cat_row.get("name", "") or "")):
                    messagebox.showwarning("Categorie e conti", "Questa categoria non è modificabile o eliminabile da qui.", parent=root)
                    return
                if category_code_used_any_year(d, cd):
                    messagebox.showwarning(
                        "Categorie e conti",
                        "Questa categoria è usata da registrazioni: non può essere rimossa.",
                        parent=root,
                    )
                    return
                if len(merged_categories_for_plan_editor(d)) <= 1:
                    messagebox.showwarning("Categorie e conti", "Serve almeno una categoria.", parent=root)
                    return
                if not messagebox.askyesno(
                    "Categorie e conti",
                    f"Rimuovere la categoria {cd} da tutti gli anni?",
                    parent=root,
                ):
                    return
                remove_category_from_all_years(d, cd)
                try:
                    save_encrypted_db_dual(
                        d,
                        Path(data_file_var.get()),
                        Path(key_file_var.get()),
                    )
                except Exception as exc:
                    messagebox.showerror("Categorie e conti", str(exc), parent=root)
                    return
                plan_conti_status_var.set("Categoria rimossa e database salvato.")
                _movements_dirty[0] = True
                try:
                    refresh_balance_footer()
                    refresh_category_account_dropdowns()
                except Exception:
                    pass
                _reload_plan_conti_form()

            ttk.Button(plan_cat_grid, text="Rimuovi", width=9, state=rm_state, command=_rm_cat).grid(
                row=ri, column=3, sticky="w", padx=2, pady=1
            )

        ttk.Label(plan_acc_grid, text="Cod.", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", padx=2, pady=2)
        ttk.Label(plan_acc_grid, text="Nome conto", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, sticky="w", padx=2, pady=2)
        ttk.Label(plan_acc_grid, text="Saldo", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=2, sticky="w", padx=2, pady=2)
        ttk.Label(plan_acc_grid, text="", width=10).grid(row=0, column=3, sticky="w")
        merged_acc = merge_account_charts_across_years(d)
        for ri, a in enumerate(merged_acc, start=1):
            code = str(a.get("code", str(ri))).strip()
            raw_nm = str(a.get("name", "") or "")
            locked_acc = plan_conti_account_is_cassa(raw_nm)
            nv = tk.StringVar(value=raw_nm)
            bal = account_balance_for_code_latest_chart(d, code)
            bal_s = "—" if bal is None else format_euro_it(bal)
            plan_acc_rows.append(
                {
                    "code": code,
                    "name": nv,
                    "orig_name": raw_nm,
                    "locked_acc": locked_acc,
                }
            )
            ttk.Label(plan_acc_grid, text=code).grid(row=ri, column=0, sticky="w", padx=2, pady=1)
            est = "readonly" if locked_acc else "normal"
            ttk.Entry(plan_acc_grid, textvariable=nv, width=36, state=est).grid(row=ri, column=1, sticky="we", padx=2, pady=1)
            ttk.Label(plan_acc_grid, text=bal_s).grid(row=ri, column=2, sticky="w", padx=2, pady=1)

            def _rm_acc(cd: str = code) -> None:
                dd = cur_db()
                acc_row = None
                for yb in dd.get("years") or []:
                    acc_row = next(
                        (x for x in yb.get("accounts", []) if str(x.get("code", "")) == cd),
                        None,
                    )
                    if acc_row is not None:
                        break
                if acc_row is None:
                    messagebox.showwarning(
                        "Categorie e conti",
                        "Questo codice conto non è nel piano di nessun anno.",
                        parent=root,
                    )
                    return
                acc_name_str = str(acc_row.get("name", "") or "")
                if plan_conti_account_is_cassa(acc_name_str):
                    messagebox.showwarning("Categorie e conti", "Il conto Cassa non può essere rimosso.", parent=root)
                    return
                if _is_virtuale_account(acc_name_str):
                    messagebox.showwarning("Categorie e conti", "Il conto VIRTUALE non può essere rimosso.", parent=root)
                    return
                if account_code_used_any_year(dd, cd):
                    messagebox.showwarning(
                        "Categorie e conti",
                        "Questo conto è usato da registrazioni: non può essere rimosso.",
                        parent=root,
                    )
                    return
                b = account_balance_for_code_latest_chart(dd, cd)
                if b is None or b != Decimal("0"):
                    messagebox.showwarning(
                        "Categorie e conti",
                        "Il conto può essere rimosso solo se il saldo è esattamente zero.",
                        parent=root,
                    )
                    return
                if len(merge_account_charts_across_years(dd)) <= 1:
                    messagebox.showwarning("Categorie e conti", "Serve almeno un conto.", parent=root)
                    return
                if not messagebox.askyesno(
                    "Categorie e conti",
                    f"Rimuovere il conto {cd} da tutti gli anni?",
                    parent=root,
                ):
                    return
                remove_account_from_all_years(dd, cd)
                try:
                    save_encrypted_db_dual(
                        dd,
                        Path(data_file_var.get()),
                        Path(key_file_var.get()),
                    )
                except Exception as exc:
                    messagebox.showerror("Categorie e conti", str(exc), parent=root)
                    return
                plan_conti_status_var.set("Conto rimosso e database salvato.")
                _movements_dirty[0] = True
                try:
                    refresh_balance_footer()
                    refresh_category_account_dropdowns()
                except Exception:
                    pass
                _reload_plan_conti_form()

            rm_state = "disabled" if locked_acc else "normal"
            ttk.Button(plan_acc_grid, text="Rimuovi", width=9, state=rm_state, command=_rm_acc).grid(
                row=ri, column=3, sticky="w", padx=2, pady=1
            )
        plan_cat_grid.columnconfigure(1, weight=1)
        plan_cat_grid.columnconfigure(2, weight=1)
        plan_acc_grid.columnconfigure(1, weight=1)
        try:
            plan_conti_canvas.configure(scrollregion=plan_conti_canvas.bbox("all"))
        except Exception:
            pass

    def _save_plan_conti_from_form() -> None:
        d = cur_db()
        if not d.get("years"):
            messagebox.showwarning("Categorie e conti", "Nessun anno contabile nel database.", parent=root)
            return
        for row in plan_cat_rows:
            code = str(row["code"])
            nm = clip_text(row["name"].get() or "", MAX_CATEGORY_NAME_LEN)
            if row.get("locked"):
                nm = clip_text(row.get("orig_name", "") or "", MAX_CATEGORY_NAME_LEN)
            nt = clip_text(row["note"].get() or "", MAX_CATEGORY_NOTE_LEN)
            nt_or_none = nt if nt else None
            on = row.get("orig_name", "")
            if nm != on:
                propagate_category_chart_by_code(d, code, nm, nt_or_none)
                if plan_conti_names_have_attinenza(on, nm) and category_code_used_any_year(d, code):
                    if messagebox.askyesno(
                        "Categorie e conti",
                        "Il nuovo nome è vicino al precedente: vuoi sostituirlo anche in tutte le registrazioni già inserite che usano questa categoria?",
                        parent=root,
                    ):
                        sync_record_category_names_for_code(d, code, nm)
                elif not plan_conti_names_have_attinenza(on, nm):
                    # Solo piano conti: nessun aggiornamento automatico dei movimenti passati.
                    pass
            else:
                propagate_category_chart_by_code(d, code, nm, nt_or_none)
        for row in plan_acc_rows:
            if row.get("locked_acc"):
                continue
            code = str(row["code"])
            nm = clip_text(row["name"].get() or "", MAX_ACCOUNT_NAME_LEN)
            on = row.get("orig_name", "")
            if nm != on:
                propagate_account_chart_by_code(d, code, nm)
                sync_record_account_names_for_code(d, code, nm)
        try:
            save_encrypted_db_dual(
                d,
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Categorie e conti", str(exc), parent=root)
            return
        plan_conti_status_var.set("Modifiche salvate.")
        _movements_dirty[0] = True
        try:
            refresh_balance_footer()
            refresh_category_account_dropdowns()
        except Exception:
            pass
        _reload_plan_conti_form()

    def _prepare_current_year_bucket() -> None:
        d = cur_db()
        y0 = date.today().year
        periodiche.ensure_year_bucket(d, y0)
        _reload_plan_conti_form()

    def _add_blank_category() -> None:
        d = cur_db()
        if not d.get("years"):
            messagebox.showwarning("Categorie e conti", "Crea prima un anno contabile.", parent=root)
            return
        if len(merged_categories_for_plan_editor(d)) >= MAX_CATEGORIES_COUNT:
            messagebox.showwarning(
                "Categorie e conti",
                f"Hai già raggiunto il massimo di {MAX_CATEGORIES_COUNT} categorie.",
                parent=root,
            )
            return
        nums: list[int] = []
        for yb in d.get("years") or []:
            for c in yb.get("categories") or []:
                s = str(c.get("code", "")).strip()
                if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
                    try:
                        nums.append(int(s))
                    except ValueError:
                        pass
        nxt = max(nums) + 1 if nums else 1
        new_cat = {"code": str(nxt), "name": "+Nuova", "note": None}
        _append_category_all_years(new_cat)
        _reload_plan_conti_form()

    def _add_blank_account() -> None:
        d = cur_db()
        if not d.get("years"):
            messagebox.showwarning("Categorie e conti", "Crea prima un anno contabile.", parent=root)
            return
        if len(merge_account_charts_across_years(d)) >= MAX_ACCOUNTS_COUNT:
            messagebox.showwarning(
                "Categorie e conti",
                f"Hai già raggiunto il massimo di {MAX_ACCOUNTS_COUNT} conti.",
                parent=root,
            )
            return
        nums: list[int] = []
        for yb in d.get("years") or []:
            for a in yb.get("accounts") or []:
                s = str(a.get("code", "")).strip()
                if s.isdigit():
                    try:
                        nums.append(int(s))
                    except ValueError:
                        pass
        nxt = max(nums) + 1 if nums else 1
        new_acc = {"code": str(nxt), "name": ""}
        _append_account_all_years(new_acc)
        _reload_plan_conti_form()

    pc_tool = ttk.Frame(plan_conti_frame)
    pc_tool.pack(fill=tk.X, pady=(0, 6))
    ttk.Label(pc_tool, textvariable=plan_ref_year_var).pack(side=tk.LEFT)
    ttk.Button(pc_tool, text="Prepara anno corrente (vuoto)", command=_prepare_current_year_bucket).pack(
        side=tk.LEFT, padx=(12, 8)
    )
    ttk.Button(pc_tool, text="Aggiorna elenco", command=_reload_plan_conti_form).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(pc_tool, text="Salva modifiche", command=_save_plan_conti_from_form).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(plan_conti_frame, textvariable=plan_conti_status_var, foreground="#2e7d32").pack(anchor=tk.W, pady=(0, 6))

    plan_conti_scroll_wrap.pack(fill=tk.BOTH, expand=True)
    ttk.Button(cat_btns, text="Aggiungi categoria", command=_add_blank_category).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(acc_btns, text="Aggiungi conto", command=_add_blank_account).pack(side=tk.LEFT, padx=(0, 8))

    def _try_open_plan_conti_pending() -> None:
        security_auth.ensure_security(cur_db())
        up = cur_db().get("user_profile") or {}
        if not up.get("plan_conti_wizard_pending"):
            return
        if not email_client.is_app_mail_configured(cur_db()):
            return
        up["plan_conti_wizard_pending"] = False
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception:
            pass
        try:
            _reload_plan_conti_form()
            _ensure_plan_conti_tab()
            notebook.select(plan_conti_frame)
        except Exception:
            pass

    _reload_plan_conti_form()
    try:
        notebook.forget(plan_conti_frame)
    except tk.TclError:
        pass

    # Opzioni page (scroll verticale: posta, percorsi, legacy possono superare l’altezza finestra)
    opz_scroll_outer = ttk.Frame(opzioni_frame, style="MovCdc.TFrame")
    opz_scroll_outer.pack(fill=tk.BOTH, expand=True)
    opz_canvas = tk.Canvas(opz_scroll_outer, highlightthickness=0, bg=MOVIMENTI_PAGE_BG)
    opz_vsb = ttk.Scrollbar(opz_scroll_outer, orient="vertical", command=opz_canvas.yview)
    opz_scrollable = ttk.Frame(opz_canvas, style="MovCdc.TFrame")
    opz_scrollable_win = opz_canvas.create_window((0, 0), window=opz_scrollable, anchor="nw")

    def _opz_on_scrollable_configure(_event: object) -> None:
        opz_canvas.configure(scrollregion=opz_canvas.bbox("all"))

    def _opz_on_canvas_configure(event: tk.Event) -> None:
        opz_canvas.itemconfigure(opz_scrollable_win, width=event.width)

    opz_scrollable.bind("<Configure>", _opz_on_scrollable_configure)
    opz_canvas.bind("<Configure>", _opz_on_canvas_configure)
    opz_canvas.configure(yscrollcommand=opz_vsb.set)
    opz_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    opz_vsb.pack(side=tk.RIGHT, fill=tk.Y)

    pack_centered_page_title(
        opz_scrollable, title=_page_banner_title(), banner_style="MovCdc.TFrame", title_bg=MOVIMENTI_PAGE_BG
    )

    opz_plan_row = ttk.Frame(opz_scrollable, style="MovCdc.TFrame")
    opz_plan_row.pack(fill=tk.X, pady=(0, 10))
    ttk.Label(
        opz_plan_row,
        text="Struttura categorie e conti:",
        font=("TkDefaultFont", 11, "bold"),
    ).pack(side=tk.LEFT)
    ttk.Button(
        opz_plan_row,
        text="Apri scheda Categorie e conti…",
        command=lambda: (_ensure_plan_conti_tab(), notebook.select(plan_conti_frame), _reload_plan_conti_form()),
    ).pack(side=tk.LEFT, padx=(12, 0))

    mail_outer = ttk.LabelFrame(opz_scrollable, text="Posta e sicurezza", padding=10)
    mail_outer.pack(fill=tk.X, pady=(0, 14))

    mail_setup_frame = ttk.Frame(mail_outer)
    mail_verified_frame = ttk.Frame(mail_outer)

    admin_notify_var = tk.StringVar()
    smtp_host_var = tk.StringVar()
    smtp_port_var = tk.StringVar(value="587")
    smtp_implicit_ssl_var = tk.BooleanVar(value=False)
    smtp_starttls_var = tk.BooleanVar(value=True)
    imap_host_var = tk.StringVar()
    imap_port_var = tk.StringVar(value="993")
    imap_ssl_var = tk.BooleanVar(value=True)
    ssl_verify_var = tk.BooleanVar(value=True)
    mail_user_var = tk.StringVar()
    mail_password_var = tk.StringVar()
    mail_from_var = tk.StringVar()
    mail_status_var = tk.StringVar(value="")

    def _load_mail_vars_from_db() -> None:
        d = cur_db()
        email_client.ensure_email_settings(d)
        security_auth.ensure_security(d)
        s = d["email_settings"]
        sc = d.get("security_config") or {}
        if not isinstance(sc, dict):
            sc = {}
        admin_notify_var.set((sc.get("admin_notify_email") or "").strip())
        smtp_host_var.set((s.get("smtp_host") or "").strip())
        smtp_port_var.set(str(int(s.get("smtp_port") or 587)))
        smtp_implicit_ssl_var.set(bool(s.get("smtp_implicit_ssl")))
        smtp_starttls_var.set(bool(s.get("smtp_use_starttls", True)))
        imap_host_var.set((s.get("imap_host") or "").strip())
        imap_port_var.set(str(int(s.get("imap_port") or 993)))
        imap_ssl_var.set(bool(s.get("imap_use_ssl", True)))
        ssl_verify_var.set(bool(s.get("ssl_verify_certificates", True)))
        mail_user_var.set((s.get("username") or "").strip())
        mail_password_var.set(s.get("password") or "")
        mail_from_var.set((s.get("from_address") or "").strip())

    def _apply_mail_vars_to_db() -> None:
        d = cur_db()
        email_client.ensure_email_settings(d)
        security_auth.ensure_security(d)
        sc = d.setdefault("security_config", {})
        if not isinstance(sc, dict):
            sc = {}
            d["security_config"] = sc
        s = d["email_settings"]
        sc["admin_notify_email"] = (admin_notify_var.get() or "").strip()
        s["smtp_host"] = (smtp_host_var.get() or "").strip()
        try:
            s["smtp_port"] = int((smtp_port_var.get() or "587").strip())
        except ValueError:
            s["smtp_port"] = 587
        s["smtp_implicit_ssl"] = bool(smtp_implicit_ssl_var.get())
        s["smtp_use_starttls"] = bool(smtp_starttls_var.get())
        s["imap_host"] = (imap_host_var.get() or "").strip()
        try:
            s["imap_port"] = int((imap_port_var.get() or "993").strip())
        except ValueError:
            s["imap_port"] = 993
        s["imap_use_ssl"] = bool(imap_ssl_var.get())
        s["ssl_verify_certificates"] = bool(ssl_verify_var.get())
        s["username"] = (mail_user_var.get() or "").strip()
        s["password"] = mail_password_var.get() or ""
        s["from_address"] = (mail_from_var.get() or "").strip()

    def refresh_mail_security_visibility() -> None:
        d = cur_db()
        security_auth.ensure_security(d)
        sc = d.get("security_config") or {}
        ok = bool(sc.get("email_verified_ok")) if isinstance(sc, dict) else False
        if ok:
            mail_setup_frame.pack_forget()
            mail_verified_frame.pack(fill=tk.X)
        else:
            mail_verified_frame.pack_forget()
            mail_setup_frame.pack(fill=tk.X)

    def _save_mail_settings() -> None:
        _apply_mail_vars_to_db()
        security_auth.ensure_security(cur_db())
        cur_db()["security_config"]["email_verified_ok"] = False
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
            mail_status_var.set("Impostazioni posta salvate. Esegui il test per confermare.")
            refresh_mail_security_visibility()
            try:
                _try_open_plan_conti_pending()
            except Exception:
                pass
        except Exception as exc:
            messagebox.showerror("Posta", str(exc))
            mail_status_var.set(f"Errore salvataggio: {exc}")

    def _test_mail_settings() -> None:
        _apply_mail_vars_to_db()
        ok, msg = email_client.test_email_configuration(cur_db())
        if ok:
            security_auth.ensure_security(cur_db())
            cur_db()["security_config"]["email_verified_ok"] = True
            try:
                save_encrypted_db_dual(
                    cur_db(),
                    Path(data_file_var.get()),
                    Path(key_file_var.get()),
                )
                refresh_mail_security_visibility()
                mail_status_var.set("Test superato.")
                messagebox.showinfo("Test posta", msg)
                _try_open_plan_conti_pending()
            except Exception as exc:
                messagebox.showerror("Posta", str(exc))
        else:
            security_auth.ensure_security(cur_db())
            cur_db()["security_config"]["email_verified_ok"] = False
            mail_status_var.set("Test non superato.")
            messagebox.showerror("Test posta", msg)

    def _repeat_first_access_registration() -> None:
        if not messagebox.askyesno(
            "Ripeti primo accesso",
            "Verranno cancellati profilo, password e stato di registrazione locale.\n"
            "Potrai ripetere il primo accesso al prossimo avvio.\n\n"
            "Procedere?",
        ):
            return
        _apply_mail_vars_to_db()
        security_auth.reset_user_profile_for_registration_restart(cur_db())
        security_auth.ensure_security(cur_db())
        cur_db()["security_config"]["email_verified_ok"] = False
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Posta", str(exc))
            return
        messagebox.showinfo(
            "Riavvio necessario",
            "Chiudi e riapri l'applicazione per completare di nuovo il primo accesso.",
        )
        try:
            root.destroy()
        finally:
            sys.exit(0)

    def _factory_reset_security_and_data() -> None:
        if not messagebox.askyesno(
            "Reset completo",
            "Verranno reimportati i dati dall'archivio legacy predefinito, "
            "cancellati account utente, impostazioni posta e sicurezza.\n\n"
            "L'applicazione si chiuderà: al riavvio andrà rifatto il primo accesso.\n\n"
            "Confermi?",
        ):
            return
        try:
            data_workspace.legacy_import_dir().mkdir(parents=True, exist_ok=True)
            out_json = data_workspace.default_legacy_json_output()
            run_import_legacy(DEFAULT_CDC_ROOT, out_json)
            new_db = json.loads(out_json.read_text(encoding="utf-8"))
            periodiche.ensure_periodic_registrations(new_db)
            email_client.ensure_email_settings(new_db)
            security_auth.ensure_security(new_db)
            security_auth.reset_user_profile_for_registration_restart(new_db)
            new_db["security_config"] = dict(security_auth.DEFAULT_SECURITY_CONFIG)
            new_db["email_settings"] = dict(email_client.DEFAULT_EMAIL_SETTINGS)
            save_encrypted_db_dual(
                new_db,
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Reset", str(exc))
            return
        messagebox.showinfo(
            "Reset eseguito",
            "Operazione completata. Riapri l'applicazione per configurare di nuovo account e posta.",
        )
        try:
            root.destroy()
        finally:
            sys.exit(0)

    def _send_registration_notification_now() -> None:
        _apply_mail_vars_to_db()
        security_auth.ensure_security(cur_db())
        up = cur_db().get("user_profile") or {}
        em = (up.get("email") or "").strip().lower()
        suf = (up.get("display_name_suffix") or "").strip()
        if not em:
            messagebox.showwarning(
                "Registrazione",
                "Nessun profilo con email: completa prima il primo accesso.",
                parent=root,
            )
            return
        if not email_client.is_app_mail_configured(cur_db()):
            messagebox.showwarning(
                "Registrazione",
                "Configura e verifica la posta prima di inviare la notifica.",
                parent=root,
            )
            return
        try:
            email_client.send_registration_signup_notification(
                cur_db(), display_suffix=suf or "—", user_email=em
            )
        except Exception as exc:
            messagebox.showerror("Registrazione", str(exc), parent=root)
            return
        try:
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Salvataggio", str(exc), parent=root)
            return
        messagebox.showinfo(
            "Registrazione",
            "Notifica inviata. Controlla la posta (e lo spam).\n\n"
            "Per risultare «registrato», nella casella IMAP configurata deve comparire un messaggio "
            "(oggetto o corpo) che contenga una di queste righe:\n\n"
            f"REGISTRA:{em}\noppure\nREGISTRATO:{em}",
            parent=root,
        )

    r_ = 0
    ttk.Label(mail_setup_frame, text="Email amministratore (notifiche nuovi accessi)", font=("TkDefaultFont", 11, "bold")).grid(
        row=r_, column=0, columnspan=4, sticky="w", pady=(0, 4)
    )
    r_ += 1
    ttk.Entry(mail_setup_frame, textvariable=admin_notify_var, width=72).grid(row=r_, column=0, columnspan=4, sticky="we", pady=(0, 10))
    r_ += 1
    ttk.Label(mail_setup_frame, text="SMTP", font=("TkDefaultFont", 11, "bold")).grid(row=r_, column=0, columnspan=4, sticky="w")
    r_ += 1
    ttk.Label(mail_setup_frame, text="Server").grid(row=r_, column=0, sticky="w")
    ttk.Entry(mail_setup_frame, textvariable=smtp_host_var, width=36).grid(row=r_, column=1, sticky="we", padx=(6, 8))
    ttk.Label(mail_setup_frame, text="Porta").grid(row=r_, column=2, sticky="w")
    ttk.Entry(mail_setup_frame, textvariable=smtp_port_var, width=8).grid(row=r_, column=3, sticky="w")
    r_ += 1
    ttk.Checkbutton(mail_setup_frame, text="SMTP SSL implicito (465)", variable=smtp_implicit_ssl_var).grid(
        row=r_, column=0, columnspan=2, sticky="w"
    )
    ttk.Checkbutton(mail_setup_frame, text="STARTTLS", variable=smtp_starttls_var).grid(row=r_, column=2, columnspan=2, sticky="w")
    r_ += 1
    ttk.Label(mail_setup_frame, text="IMAP", font=("TkDefaultFont", 11, "bold")).grid(row=r_, column=0, columnspan=4, sticky="w", pady=(8, 0))
    r_ += 1
    ttk.Label(mail_setup_frame, text="Server").grid(row=r_, column=0, sticky="w")
    ttk.Entry(mail_setup_frame, textvariable=imap_host_var, width=36).grid(row=r_, column=1, sticky="we", padx=(6, 8))
    ttk.Label(mail_setup_frame, text="Porta").grid(row=r_, column=2, sticky="w")
    ttk.Entry(mail_setup_frame, textvariable=imap_port_var, width=8).grid(row=r_, column=3, sticky="w")
    r_ += 1
    ttk.Checkbutton(mail_setup_frame, text="IMAP SSL", variable=imap_ssl_var).grid(row=r_, column=0, columnspan=2, sticky="w")
    ttk.Checkbutton(
        mail_setup_frame,
        text="Verifica certificati SSL (lasciare attivo; disattivare solo se errore certificati)",
        variable=ssl_verify_var,
    ).grid(row=r_, column=2, columnspan=2, sticky="w")
    r_ += 1
    ttk.Label(mail_setup_frame, text="Utente (account posta)", font=("TkDefaultFont", 11, "bold")).grid(row=r_, column=0, columnspan=4, sticky="w", pady=(8, 0))
    r_ += 1
    ttk.Entry(mail_setup_frame, textvariable=mail_user_var, width=72).grid(row=r_, column=0, columnspan=4, sticky="we")
    r_ += 1
    ttk.Label(mail_setup_frame, text="Password app / account").grid(row=r_, column=0, sticky="nw", pady=(4, 0))
    ttk.Entry(mail_setup_frame, textvariable=mail_password_var, width=40, show="•").grid(row=r_, column=1, columnspan=3, sticky="w", pady=(4, 0))
    r_ += 1
    tk.Label(
        mail_setup_frame,
        text=(
            "Gmail: usa l’indirizzo completo come utente e una «Password per le app» "
            "(myaccount.google.com/apppasswords), non la password di accesso a Google. "
            "Abilita IMAP in Gmail (Impostazioni → Inoltro e POP/IMAP)."
        ),
        font=("TkDefaultFont", 10),
        fg="#444444",
        justify=tk.LEFT,
        wraplength=720,
    ).grid(row=r_, column=0, columnspan=4, sticky="w", pady=(2, 6))
    r_ += 1
    ttk.Label(mail_setup_frame, text="Da (mittente, opzionale)").grid(row=r_, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(mail_setup_frame, textvariable=mail_from_var, width=50).grid(row=r_, column=1, columnspan=3, sticky="w", pady=(6, 0))
    r_ += 1
    mail_btns = ttk.Frame(mail_setup_frame)
    mail_btns.grid(row=r_, column=0, columnspan=4, sticky="w", pady=(12, 4))
    ttk.Button(mail_btns, text="Salva impostazioni posta", command=_save_mail_settings).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(mail_btns, text="Test connessione (SMTP + IMAP)", command=_test_mail_settings).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(mail_btns, text="Ripeti primo accesso / registrazione", command=_repeat_first_access_registration).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        mail_btns,
        text="Invia notifica registrazione (amministratore + copia a te)",
        command=_send_registration_notification_now,
    ).pack(side=tk.LEFT, padx=(0, 8))
    r_ += 1
    ttk.Label(mail_setup_frame, textvariable=mail_status_var, foreground="#333").grid(row=r_, column=0, columnspan=4, sticky="w")

    for c in range(4):
        mail_setup_frame.columnconfigure(c, weight=1 if c == 1 else 0)

    ttk.Label(
        mail_verified_frame,
        text="La configurazione della posta è stata verificata con successo.",
        font=("TkDefaultFont", 12),
    ).pack(anchor=tk.W)
    ttk.Button(
        mail_verified_frame,
        text="Resettare account, posta e impostazioni di sicurezza…",
        command=_factory_reset_security_and_data,
    ).pack(anchor=tk.W, pady=(10, 0))
    ttk.Button(
        mail_verified_frame,
        text="Invia di nuovo notifica registrazione (primo accesso)",
        command=_send_registration_notification_now,
    ).pack(anchor=tk.W, pady=(12, 0))
    ttk.Label(
        mail_verified_frame,
        text=(
            "Per confermare l'utente come «registrato», una email in INBOX deve contenere "
            "REGISTRA: oppure REGISTRATO: seguiti dall'email utente (come nella notifica inviata)."
        ),
        wraplength=520,
        font=("TkDefaultFont", 10),
    ).pack(anchor=tk.W, pady=(8, 0))

    _load_mail_vars_from_db()
    refresh_mail_security_visibility()

    opzioni_inner = ttk.Frame(opz_scrollable)
    opzioni_inner.pack(fill=tk.X)

    workspace_path_var = tk.StringVar()

    def _refresh_workspace_path_display(*_a: object) -> None:
        try:
            workspace_path_var.set(str(data_workspace.data_dir().resolve()))
        except Exception:
            workspace_path_var.set("—")

    _refresh_workspace_path_display()

    ttk.Label(opzioni_inner, text="Cartella dati configurata", font=("TkDefaultFont", 12, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
    )
    ttk.Label(
        opzioni_inner,
        textvariable=workspace_path_var,
        wraplength=620,
        font=("TkDefaultFont", 11),
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 10))

    legacy_path_var = tk.StringVar(value=str(DEFAULT_CDC_ROOT))

    ttk.Label(
        opzioni_inner,
        text="Cartella dati: sposta insieme file .enc completo, .enc light e .key (stessi nomi).",
        wraplength=620,
    ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 4))

    def browse_data_folder() -> None:
        import light_enc_sidecar

        picked = filedialog.askdirectory(
            initialdir=str(Path(data_file_var.get()).expanduser().parent),
            title="Cartella destinazione per i file dati",
        )
        if not picked:
            return
        dest_dir = Path(picked).expanduser().resolve()
        src_enc = Path(data_file_var.get()).expanduser().resolve()
        src_key = Path(key_file_var.get()).expanduser().resolve()
        src_light = light_enc_sidecar.light_enc_path_for_primary(src_enc).resolve()
        dest_enc = dest_dir / src_enc.name
        dest_key = dest_dir / src_key.name
        dest_light = dest_dir / src_light.name

        if src_enc.parent.resolve() == dest_dir:
            status_var.set("Cartella invariata.")
            return
        moves: list[tuple[str, Path, Path]] = []
        if src_enc.is_file():
            moves.append((src_enc.name, src_enc, dest_enc))
        if src_key.is_file():
            moves.append((src_key.name, src_key, dest_key))
        if src_light.is_file():
            moves.append((src_light.name, src_light, dest_light))
        if not moves:
            messagebox.showwarning("Cartella dati", "Nessun file da spostare (percorsi non validi?).", parent=root)
            return
        bad: list[str] = []
        for _label, src, dst in moves:
            if not src.is_file():
                continue
            if dst.is_file():
                try:
                    if dst.samefile(src):
                        continue
                except OSError:
                    pass
                bad.append(dst.name)
        if bad:
            messagebox.showerror(
                "Cartella dati",
                "Nella cartella scelta esistono già file con lo stesso nome:\n"
                + "\n".join(bad)
                + "\n\nRinomina o spostali, poi riprova.",
                parent=root,
            )
            return
        names = "\n".join(f"• {lbl}" for lbl, _, _ in moves)
        if not messagebox.askyesno(
            "Conferma spostamento",
            f"Verranno spostati in:\n{dest_dir}\n\n{names}\n\nContinuare?",
            parent=root,
        ):
            return
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            for _label, src, dst in moves:
                if src.is_file():
                    shutil.move(str(src), str(dst))
        except Exception as exc:
            messagebox.showerror("Cartella dati", str(exc), parent=root)
            return
        data_file_var.set(str(dest_enc))
        key_file_var.set(str(dest_key))
        _sync_path_holders_from_vars()
        try:
            data_workspace.save_workspace_path(dest_dir)
            data_workspace.set_data_workspace_root(dest_dir)
        except Exception:
            pass
        _refresh_workspace_path_display()
        status_var.set(f"File spostati in: {dest_dir}")

    ttk.Button(opzioni_inner, text="Sposta nella cartella…", command=browse_data_folder).grid(
        row=3, column=0, columnspan=2, sticky="w", pady=(0, 8)
    )

    ttk.Label(opzioni_inner, text="File dati nuova app (criptato)").grid(row=4, column=0, sticky="w", pady=(12, 6))
    data_entry = ttk.Entry(opzioni_inner, textvariable=data_file_var, width=80)
    data_entry.grid(row=5, column=0, sticky="we", padx=(0, 8))

    backup_info_var = tk.StringVar()

    def _refresh_backup_path_hint(*_a: object) -> None:
        try:
            p = Path(data_file_var.get()).expanduser().resolve()
            backup_info_var.set(
                "Copie di sicurezza (Library dell’utente): "
                + str(user_local_backup_enc_path(p).resolve())
                + " e, se generati, stesso prefisso per .key e file *_light in Application Support/ContiDiCasa."
            )
        except Exception:
            backup_info_var.set(
                "Copie di sicurezza: ~/Library/Application Support/ContiDiCasa/<stem>_backup.enc (e .key / light ove presenti)."
            )

    _refresh_backup_path_hint()
    data_file_var.trace_add("write", _refresh_backup_path_hint)

    ttk.Label(
        opzioni_inner,
        textvariable=backup_info_var,
        wraplength=620,
    ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))

    def browse_data_file() -> None:
        picked = filedialog.asksaveasfilename(
            initialdir=str(Path(data_file_var.get()).parent),
            initialfile=Path(data_file_var.get()).name,
            defaultextension=".enc",
            filetypes=[("Encrypted data", "*.enc"), ("All files", "*.*")],
        )
        if picked:
            data_file_var.set(picked)

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_data_file).grid(row=5, column=1, sticky="w")

    ttk.Label(opzioni_inner, text="File chiave cifratura").grid(row=7, column=0, sticky="w", pady=(12, 6))
    key_entry = ttk.Entry(opzioni_inner, textvariable=key_file_var, width=80)
    key_entry.grid(row=8, column=0, sticky="we", padx=(0, 8))

    def browse_key_file() -> None:
        picked = filedialog.asksaveasfilename(
            initialdir=str(Path(key_file_var.get()).parent),
            initialfile=Path(key_file_var.get()).name,
            defaultextension=".key",
            filetypes=[("Key files", "*.key"), ("All files", "*.*")],
        )
        if picked:
            key_file_var.set(picked)

    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_key_file).grid(row=8, column=1, sticky="w")

    status_var = tk.StringVar(value="")
    ttk.Label(opzioni_inner, textvariable=status_var).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def opzioni_restore_from_library_backup() -> None:
        primary = Path(data_file_var.get()).expanduser().resolve()
        kp = Path(key_file_var.get()).expanduser().resolve()
        backup = user_local_backup_enc_path(primary)
        if not backup.is_file():
            messagebox.showerror(
                "Backup non trovato",
                "Nessun file di backup corrispondente in Library:\n"
                f"{backup.resolve()}\n\n"
                "Il nome atteso è <nome file dati senza .enc>_backup.enc nella cartella sopra.",
                parent=root,
            )
            return
        if primary.is_file():
            if not messagebox.askyesno(
                "Sovrascrivere",
                f"Il file operativo esiste già:\n{primary}\n\n"
                "Sovrascriverlo con il contenuto del backup dalla Library?",
                parent=root,
            ):
                return
        try:
            db = restore_enc_from_library_backup_file(
                backup_path=backup,
                primary_target=primary,
                key_path=kp,
            )
        except ValueError as exc:
            messagebox.showerror("Ripristino", str(exc), parent=root)
            return
        except OSError as exc:
            messagebox.showerror("Ripristino", str(exc), parent=root)
            return
        periodiche.ensure_periodic_registrations(db)
        email_client.ensure_email_settings(db)
        security_auth.ensure_security(db)
        db_holder[0] = db
        try:
            save_encrypted_db_dual(db, primary, kp)
        except Exception as exc:
            messagebox.showerror("Salvataggio", str(exc), parent=root)
            return
        _sync_path_holders_from_vars()
        path_holder[0] = primary
        key_path_holder[0] = kp
        populate_movements_trees()
        refresh_balance_footer()
        refresh_window_title()
        _refresh_backup_path_hint()
        status_var.set("Ripristino da Library completato; file light aggiornato.")
        messagebox.showinfo(
            "Ripristino",
            "File ripristinati nel percorso operativo (database, chiave e sidecar light se presenti in Library).",
            parent=root,
        )

    ripristina_btn = ttk.Button(
        opzioni_inner,
        text="Ripristina da backup (Library Mac)…",
        command=opzioni_restore_from_library_backup,
    )

    def _refresh_ripristina_visibility(*_a: object) -> None:
        try:
            show = (
                not session_holder[0].entered_via_backdoor
                and (
                    not Path(data_file_var.get()).expanduser().resolve().is_file()
                    or not Path(key_file_var.get()).expanduser().resolve().is_file()
                )
            )
        except Exception:
            show = False
        if show:
            ripristina_btn.grid(row=10, column=0, columnspan=2, sticky="w", pady=(12, 0))
        else:
            ripristina_btn.grid_remove()

    data_file_var.trace_add("write", _refresh_ripristina_visibility)
    key_file_var.trace_add("write", _refresh_ripristina_visibility)
    _refresh_ripristina_visibility()

    def reload_legacy_overwrite() -> None:
        confirmed = messagebox.askyesno(
            "Conferma import legacy",
            "Confermi l'avvio di ImportLegacy?\n\n"
            "Verranno sostituiti anni, conti, categorie e registrazioni importate dall'archivio legacy.\n"
            "Profilo utente (email/password), impostazioni posta, sicurezza e registrazioni periodiche "
            "restano quelli attuali.",
        )
        if not confirmed:
            status_var.set("Import legacy annullato dall'utente.")
            return
        try:
            legacy_root = Path(legacy_path_var.get())
            previous_db = db_holder[0]
            data_workspace.legacy_import_dir().mkdir(parents=True, exist_ok=True)
            output_json = data_workspace.default_legacy_json_output()
            run_import_legacy(legacy_root, output_json)
            new_db = json.loads(output_json.read_text(encoding="utf-8"))
            _merge_preserved_app_sections_from_previous_db(new_db, previous_db)
            periodiche.ensure_periodic_registrations(new_db)
            email_client.ensure_email_settings(new_db)
            security_auth.ensure_security(new_db)
            save_encrypted_db_dual(
                new_db,
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
            db_holder[0] = new_db
            try:
                new_db.setdefault("user_profile", {})["plan_conti_wizard_pending"] = False
            except Exception:
                pass
            try:
                _reload_plan_conti_form()
            except Exception:
                pass
            populate_movements_trees()
            refresh_balance_footer()
            oob: list[str] = []
            for yd in new_db.get("years", []) or []:
                yn = int(yd.get("year", 0))
                nc = len(yd.get("categories") or [])
                na = len(yd.get("accounts") or [])
                if nc > MAX_CATEGORIES_COUNT:
                    oob.append(f"Anno {yn}: {nc} categorie (massimo consigliato in app: {MAX_CATEGORIES_COUNT})")
                if na > MAX_ACCOUNTS_COUNT:
                    oob.append(f"Anno {yn}: {na} conti (massimo consigliato in app: {MAX_ACCOUNTS_COUNT})")
            if oob:
                messagebox.showwarning(
                    "Import legacy — limiti pratici",
                    "Alcuni anni superano i massimi previsti per nuove voci in «Categorie e conti»:\n\n"
                    + "\n".join(oob)
                    + "\n\nI dati importati restano utilizzabili; non potrai aggiungere categorie o conti oltre questi limiti finché non ne rimuovi.",
                )
            messagebox.showinfo(
                "Import completato",
                "Import legacy completato.\n"
                "Dati contabili aggiornati; profilo, posta e periodiche sono stati mantenuti.",
            )
            status_var.set("Ultimo import: completato (dati legacy aggiornati, impostazioni app conservate).")
        except Exception as exc:
            messagebox.showerror("Errore import", str(exc))
            status_var.set(f"Errore: {exc}")

    def browse_legacy() -> None:
        picked = filedialog.askdirectory(initialdir=legacy_path_var.get() or str(DEFAULT_CDC_ROOT))
        if picked:
            legacy_path_var.set(picked)

    ttk.Label(
        opzioni_inner,
        text="Import legacy (sorgente applicazione precedente)",
        font=("TkDefaultFont", 11, "italic"),
    ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(20, 4))

    ttk.Label(opzioni_inner, text="Sorgente import legacy").grid(row=12, column=0, sticky="w", pady=(0, 6))
    legacy_entry = ttk.Entry(opzioni_inner, textvariable=legacy_path_var, width=80)
    legacy_entry.grid(row=13, column=0, sticky="we", padx=(0, 8))
    ttk.Button(opzioni_inner, text="Sfoglia...", command=browse_legacy).grid(row=13, column=1, sticky="w")

    ttk.Button(
        opzioni_inner,
        text="Ricarica importi legacy (sovrascrive dati nuova app)",
        command=reload_legacy_overwrite,
    ).grid(row=14, column=0, sticky="w", pady=(16, 0))

    # --- Azzeramento di emergenza saldo virtuale ---
    def _emergency_reset_virtuale() -> None:
        if virtuale_saldo[0] <= Decimal("0") and not virtuale_discharge_active[0]:
            messagebox.showinfo("Saldo virtuale", "Non c'è nessun saldo virtuale da azzerare.")
            return
        if not messagebox.askyesno(
            "Azzeramento saldo virtuale",
            f"Il saldo virtuale attuale è {format_euro_it(virtuale_saldo[0])} €.\n\n"
            "Questa operazione azzera il saldo virtuale senza creare registrazioni.\n"
            "Le registrazioni già create NON vengono modificate.\n\n"
            "Confermi l'azzeramento di emergenza?",
        ):
            return
        if not messagebox.askyesno(
            "Azzeramento saldo virtuale",
            "ATTENZIONE: questa operazione non è reversibile.\n"
            "Sei sicuro di voler procedere?",
        ):
            return
        _exit_virtuale_discharge_mode()
        _populate_form_defaults(keep_last=False)
        messagebox.showinfo("Saldo virtuale", "Saldo virtuale azzerato.")

    ttk.Label(
        opzioni_inner,
        text="Saldo virtuale — emergenza",
        font=("TkDefaultFont", 11, "italic"),
    ).grid(row=15, column=0, columnspan=2, sticky="w", pady=(20, 4))

    ttk.Button(
        opzioni_inner,
        text="Azzera saldo virtuale (emergenza)",
        command=_emergency_reset_virtuale,
    ).grid(row=16, column=0, sticky="w", pady=(4, 0))

    # --- Diagnostica e recovery file cifrati ---
    def _enc_file_info(p: Path) -> str | None:
        try:
            if not p.exists():
                return None
            st = p.stat()
            sz = st.st_size
            mod = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M:%S")
            return f"{sz:,} byte — {mod}"
        except Exception:
            return None

    def _enc_files_identical(a: Path, b: Path) -> bool | None:
        """Confronta il contenuto decifrato di due file .enc (i byte grezzi differiscono
        sempre a causa dell'IV casuale di Fernet)."""
        try:
            if not a.exists() or not b.exists():
                return None
            key_path = Path(key_file_var.get())
            if not key_path.exists():
                return None
            key = key_path.read_bytes()
            dec_a = Fernet(key).decrypt(a.read_bytes())
            dec_b = Fernet(key).decrypt(b.read_bytes())
            return dec_a == dec_b
        except Exception:
            return None

    def _enc_pair_report(label: str, dropbox_path: Path, library_path: Path) -> list[str]:
        p_info = _enc_file_info(dropbox_path)
        b_info = _enc_file_info(library_path)
        identical = _enc_files_identical(dropbox_path, library_path)
        lines = [f"— {label} —"]
        lines.append(f"  Dropbox: {p_info or 'Non trovato'}")
        lines.append(f"  Library: {b_info or 'Non trovato'}")
        if identical is None:
            lines.append("  ⚠ Impossibile confrontare (file mancante).")
        elif identical:
            lines.append("  ✓ Identici.")
        else:
            lines.append("  ✗ DIVERSI.")
        return lines

    def _opz_verifica_coerenza_enc() -> None:
        try:
            primary = Path(data_file_var.get())
        except Exception:
            messagebox.showerror("Verifica file", "Percorso file principale non configurato.")
            return
        import light_enc_sidecar
        backup_enc = user_local_backup_enc_path(primary)
        light_dropbox = light_enc_sidecar.light_enc_path_for_primary(primary)
        light_library = user_local_backup_light_path(primary)

        lines = ["Confronto file Dropbox ↔ Library:\n"]
        lines.extend(_enc_pair_report("Database principale (.enc)", primary, backup_enc))
        lines.append("")
        lines.extend(_enc_pair_report("Sidecar mobile (_light.enc)", light_dropbox, light_library))
        lines.append(f"\nDropbox:  {primary.parent}")
        lines.append(f"Library:  {_user_library_conti_support_dir()}")
        messagebox.showinfo("Verifica coerenza file cifrati", "\n".join(lines))

    def _opz_copia_library_su_dropbox() -> None:
        try:
            primary = Path(data_file_var.get())
        except Exception:
            messagebox.showerror("Copia file", "Percorso file principale non configurato.")
            return
        import light_enc_sidecar
        backup_enc = user_local_backup_enc_path(primary)
        light_dropbox = light_enc_sidecar.light_enc_path_for_primary(primary)
        light_library = user_local_backup_light_path(primary)
        if not backup_enc.exists() and not light_library.exists():
            messagebox.showerror("Copia file", "Nessun backup trovato in Library.")
            return
        pairs: list[tuple[Path, Path, str]] = []
        details: list[str] = []
        if backup_enc.exists():
            pairs.append((backup_enc, primary, "Database principale"))
            details.append(f"DB principale: {_enc_file_info(backup_enc) or 'N/D'} → {_enc_file_info(primary) or 'Non trovato'}")
        if light_library.exists():
            pairs.append((light_library, light_dropbox, "Sidecar mobile"))
            details.append(f"Light mobile: {_enc_file_info(light_library) or 'N/D'} → {_enc_file_info(light_dropbox) or 'Non trovato'}")
        msg = (
            "Questa operazione sovrascrive i file su Dropbox con quelli in Library.\n\n"
            + "\n".join(details)
            + "\n\nConfermi la sovrascrittura?"
        )
        if not messagebox.askyesno("Copia Library → Dropbox", msg):
            return
        if not messagebox.askyesno("Copia Library → Dropbox", "Sei sicuro? L'operazione non è reversibile."):
            return
        errors: list[str] = []
        for src, dst, label in pairs:
            try:
                shutil.copy2(src, dst)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        if errors:
            messagebox.showerror("Copia Library → Dropbox", "Errori:\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Copia Library → Dropbox", f"{len(pairs)} file copiati con successo.")

    def _opz_copia_dropbox_su_library() -> None:
        try:
            primary = Path(data_file_var.get())
        except Exception:
            messagebox.showerror("Copia file", "Percorso file principale non configurato.")
            return
        import light_enc_sidecar
        backup_enc = user_local_backup_enc_path(primary)
        light_dropbox = light_enc_sidecar.light_enc_path_for_primary(primary)
        light_library = user_local_backup_light_path(primary)
        if not primary.exists() and not light_dropbox.exists():
            messagebox.showerror("Copia file", "Nessun file trovato su Dropbox.")
            return
        pairs: list[tuple[Path, Path, str]] = []
        details: list[str] = []
        if primary.exists():
            pairs.append((primary, backup_enc, "Database principale"))
            details.append(f"DB principale: {_enc_file_info(primary) or 'N/D'} → {_enc_file_info(backup_enc) or 'Non trovato'}")
        if light_dropbox.exists():
            pairs.append((light_dropbox, light_library, "Sidecar mobile"))
            details.append(f"Light mobile: {_enc_file_info(light_dropbox) or 'N/D'} → {_enc_file_info(light_library) or 'Non trovato'}")
        msg = (
            "Questa operazione sovrascrive i file in Library con quelli da Dropbox.\n\n"
            + "\n".join(details)
            + "\n\nConfermi la sovrascrittura?"
        )
        if not messagebox.askyesno("Copia Dropbox → Library", msg):
            return
        errors: list[str] = []
        for src, dst, label in pairs:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        if errors:
            messagebox.showerror("Copia Dropbox → Library", "Errori:\n" + "\n".join(errors))
        else:
            messagebox.showinfo("Copia Dropbox → Library", f"{len(pairs)} file copiati con successo.")

    ttk.Label(
        opzioni_inner,
        text="Diagnostica file cifrato",
        font=("TkDefaultFont", 11, "italic"),
    ).grid(row=17, column=0, columnspan=2, sticky="w", pady=(20, 4))

    _diag_btn_row = tk.Frame(opzioni_inner, bg=MOVIMENTI_PAGE_BG, highlightthickness=0)
    _diag_btn_row.grid(row=18, column=0, columnspan=2, sticky="w", pady=(4, 0))
    ttk.Button(
        _diag_btn_row,
        text="Verifica coerenza Dropbox ↔ Library",
        command=_opz_verifica_coerenza_enc,
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        _diag_btn_row,
        text="Copia Library → Dropbox",
        command=_opz_copia_library_su_dropbox,
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        _diag_btn_row,
        text="Copia Dropbox → Library",
        command=_opz_copia_dropbox_su_library,
    ).pack(side=tk.LEFT)

    opzioni_inner.columnconfigure(0, weight=1)

    def _opz_canvas_mousewheel(event: tk.Event) -> str | None:
        d = getattr(event, "delta", 0)
        if d:
            opz_canvas.yview_scroll(int(-d / 120), "units")
        return None

    def _opz_canvas_mousewheel_linux(event: tk.Event) -> str | None:
        if event.num == 4:
            opz_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            opz_canvas.yview_scroll(1, "units")
        return None

    def _bind_opz_mousewheel_recursive(w: tk.Misc) -> None:
        w.bind("<MouseWheel>", _opz_canvas_mousewheel, add="+")
        w.bind("<Button-4>", _opz_canvas_mousewheel_linux, add="+")
        w.bind("<Button-5>", _opz_canvas_mousewheel_linux, add="+")
        try:
            for ch in w.winfo_children():
                _bind_opz_mousewheel_recursive(ch)
        except tk.TclError:
            pass

    opz_canvas.bind("<MouseWheel>", _opz_canvas_mousewheel)
    opz_canvas.bind("<Button-4>", _opz_canvas_mousewheel_linux)
    opz_canvas.bind("<Button-5>", _opz_canvas_mousewheel_linux)
    _bind_opz_mousewheel_recursive(opz_scrollable)

    def _startup_periodic_due_check() -> None:
        today = date.today()
        try:
            n = periodiche.materialize_all_due(cur_db(), today)
            if n <= 0:
                return
            save_encrypted_db_dual(
                cur_db(),
                Path(data_file_var.get()),
                Path(key_file_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Registrazioni periodiche", str(exc))
            return
        populate_movements_trees()
        refresh_balance_footer()
        try:
            _per_refresh_tree()
        except Exception:
            pass
        messagebox.showinfo(
            "Registrazioni periodiche",
            f"Sono state create {n} registrazioni da scadenze periodiche in sospeso.",
        )

    def _open_opzioni_if_mail_incomplete() -> None:
        if virtuale_discharge_active[0]:
            return
        try:
            if not email_client.is_app_mail_configured(cur_db()):
                notebook.select(opzioni_frame)
        except Exception:
            pass

    def _startup_check_virtuale_pending() -> None:
        if not virtuale_discharge_active[0]:
            return
        try:
            notebook.select(nuovi_dati_frame)
        except Exception:
            pass
        try:
            _show_mode("new")
        except Exception:
            pass
        messagebox.showwarning(
            "Saldo virtuale non azzerato",
            f"Il saldo virtuale è di {format_euro_it(virtuale_saldo[0])} €.\n\n"
            "La sessione precedente si è interrotta prima dell'azzeramento.\n"
            "Occorre completare lo scarico del saldo virtuale.\n\n"
            "In alternativa, usa «Azzera saldo virtuale (emergenza)» nelle Opzioni.",
        )

    def _startup_periodic_then_virtuale() -> None:
        _startup_periodic_due_check()
        _startup_check_virtuale_pending()

    root.after(200, _open_opzioni_if_mail_incomplete)
    root.after(350, _startup_periodic_then_virtuale)
    root.after(900, _try_open_plan_conti_pending)

    def _poll_registration_once() -> None:
        try:
            if security_auth.poll_registration_emails(cur_db()):
                save_encrypted_db_dual(
                    cur_db(),
                    Path(data_file_var.get()),
                    Path(key_file_var.get()),
                )
                refresh_window_title()
        except Exception:
            pass

    root.after(900, _poll_registration_once)

    def _present_main_window() -> None:
        """Mostra la finestra principale solo a UI pronta; evita flash nero (fullscreen Cocoa) su macOS."""
        try:
            if platform.system() == "Darwin":
                try:
                    root.attributes("-fullscreen", False)
                except Exception:
                    pass
                sw = root.winfo_screenwidth()
                sh = root.winfo_screenheight()
                root.geometry(f"{sw}x{sh}+0+0")
            else:
                root.geometry("1200x760")
                try:
                    root.state("zoomed")
                except Exception:
                    pass
            root.deiconify()
            root.lift()
            root.focus_force()
            root.update_idletasks()
        except Exception:
            pass

    _present_main_window()
    root.mainloop()


def main() -> None:
    if Fernet is None:
        print("Installa cryptography: pip install cryptography", file=sys.stderr)
        sys.exit(1)

    root = tk.Tk()
    root.title("Conti di casa")
    # La root resta nascosta fino al bisogno (evita la grande finestra vuota dietro i dialoghi).
    try:
        root.withdraw()
    except Exception:
        pass

    if not security_auth.verify_pillow_for_login_ui(parent=None):
        print("Avvio interrotto: Pillow non disponibile per UI login.", file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        return

    try:
        root.deiconify()
        root.lift()
    except Exception:
        pass

    if not data_workspace.configure_data_workspace_interactive(root):
        print("Avvio annullato: cartella dati non configurata.", file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        return

    try:
        root.withdraw()
    except Exception:
        pass

    up = os_boot_time.seconds_since_os_boot()
    if up is not None and up < _BOOT_DROPBOX_CONFIRM_WITHIN_SECONDS:
        if not messagebox.askokcancel(
            "Conti di casa",
            "Hai controllato che Dropbox sia aggiornato?\n\n"
            "Se la cartella dati è in Dropbox e non ha ancora finito di sincronizzare, attendere "
            "prima di continuare.\n\n"
            "OK = continua e carica il database\n"
            "Annulla = esci dall'applicazione",
            parent=None,
        ):
            print("Avvio annullato: conferma Dropbox dopo boot non accettata.", file=sys.stderr)
            try:
                root.destroy()
            except Exception:
                pass
            return

    # Root ridotta al minimo: serve come master per lo splash Dropbox; evita la cornice vuota grande.
    try:
        root.deiconify()
        root.minsize(1, 1)
        root.geometry("1x1+0+0")
        root.update_idletasks()
    except Exception:
        pass

    db, resolved_path = load_database_at_startup(sync_ui_parent=root)

    db_holder: list[dict] = [db]
    path_holder: list[Path] = [resolved_path]
    key_path_holder: list[Path] = [data_workspace.default_key_file().resolve()]

    def save_db() -> None:
        periodiche.ensure_periodic_registrations(db_holder[0])
        email_client.ensure_email_settings(db_holder[0])
        security_auth.ensure_security(db_holder[0])
        save_encrypted_db_dual(
            db_holder[0],
            path_holder[0],
            key_path_holder[0],
        )

    security_auth.ensure_security(db_holder[0])
    if not mail_gate.run_startup_mail_gate(root, db_holder[0], save_db):
        try:
            messagebox.showwarning(
                "Conti di casa",
                "Configurazione posta non completata.\nL'applicazione verrà chiusa.",
                parent=None,
            )
        except Exception:
            print("Configurazione posta annullata.", file=sys.stderr)
        print("Avvio interrotto: startup mail gate non completato.", file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        return
    if not security_auth.run_first_access_wizard_if_needed(root, db_holder[0], save_db):
        try:
            messagebox.showwarning(
                "Conti di casa",
                "Primo accesso non completato.\nL'applicazione verrà chiusa.",
                parent=None,
            )
        except Exception:
            print("Primo accesso non completato o annullato.", file=sys.stderr)
        print("Avvio interrotto: wizard primo accesso non completato.", file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        return
    def persist_utenza_precedente_before_nuova_utenza() -> None:
        """Salva il DB corrente sul file .enc canonico dell’email in profilo (posta/sicurezza/periodiche restano di quell’utenza)."""
        d = db_holder[0]
        security_auth.ensure_security(d)
        up = d.get("user_profile") or {}
        em = (up.get("email") or "").strip().lower()
        if not em or not (up.get("password_hash") or "").strip():
            return
        target = per_user_encrypted_db_path(em)
        periodiche.ensure_periodic_registrations(d)
        email_client.ensure_email_settings(d)
        security_auth.ensure_security(d)
        save_encrypted_db_dual(d, target, key_path_holder[0])

    ok, session = security_auth.run_login_dialog(
        root,
        db_holder[0],
        save_db,
        before_nuova_utenza=persist_utenza_precedente_before_nuova_utenza,
        after_prepare_nuova_utenza=reset_contabili_for_nuova_utenza,
    )
    if not ok or session is None:
        try:
            messagebox.showinfo(
                "Conti di casa",
                "Accesso annullato.\nPer usare il programma avvia di nuovo l'applicazione.",
                parent=None,
            )
        except Exception:
            print("Accesso annullato.", file=sys.stderr)
        print("Avvio interrotto: login annullato.", file=sys.stderr)
        try:
            root.destroy()
        except Exception:
            pass
        return
    assert session is not None

    if session.user_email:
        try:
            data_workspace.save_last_login_email(session.user_email)
        except Exception:
            pass

    path_holder[0] = migrate_data_path_after_login(db_holder[0], session, path_holder[0])
    if session.entered_via_backdoor:
        security_auth.ensure_security(db_holder[0])
        session.is_registered = bool(
            (db_holder[0].get("user_profile") or {}).get("registration_verified")
        )
    build_ui(db_holder[0], root, session, path_holder, key_path_holder)


if __name__ == "__main__":
    main()
