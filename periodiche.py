"""
Registrazioni periodiche: logica date, persistenza nel DB, materializzazione movimenti.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from import_legacy import MAX_CHEQUE_LEN, MAX_RECORD_NOTE_LEN, format_money

CADENCE_CHOICES: list[tuple[str, str]] = [
    ("daily", "Quotidiana"),
    ("weekly", "Settimanale"),
    ("monthly", "Mensile"),
    ("bimonthly", "Bimensile"),
    ("quarterly", "Trimestrale"),
    ("quadrimestral", "Quadrimestrale"),
    ("semiannual", "Semestrale"),
    ("annual", "Annuale"),
]

CADENCE_IDS = {c[0] for c in CADENCE_CHOICES}
CADENCE_LABEL_IT = dict(CADENCE_CHOICES)


def cadence_label(cid: str) -> str:
    return CADENCE_LABEL_IT.get(cid, cid)


def ensure_periodic_registrations(db: dict) -> None:
    if "periodic_registrations" not in db or not isinstance(db["periodic_registrations"], list):
        db["periodic_registrations"] = []
    for rule in db["periodic_registrations"]:
        if not isinstance(rule, dict):
            continue
        if str(rule.get("cadence") or "") == "biweekly":
            rule["cadence"] = "weekly"


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def advance_by_cadence(d: date, cadence: str) -> date:
    if cadence == "daily":
        return d + timedelta(days=1)
    if cadence == "weekly":
        return d + timedelta(days=7)
    if cadence == "monthly":
        return _add_months(d, 1)
    if cadence == "bimonthly":
        return _add_months(d, 2)
    if cadence == "quarterly":
        return _add_months(d, 3)
    if cadence == "quadrimestral":
        return _add_months(d, 4)
    if cadence == "semiannual":
        return _add_months(d, 6)
    if cadence == "annual":
        return _add_months(d, 12)
    return d + timedelta(days=1)


def previous_by_cadence(d: date, cadence: str) -> date:
    """Inverso di advance_by_cadence: data L tale che advance(L, cadence) == d (stessa logica di calendario)."""
    if cadence == "daily":
        return d - timedelta(days=1)
    if cadence == "weekly":
        return d - timedelta(days=7)
    if cadence == "monthly":
        return _add_months(d, -1)
    if cadence == "bimonthly":
        return _add_months(d, -2)
    if cadence == "quarterly":
        return _add_months(d, -3)
    if cadence == "quadrimestral":
        return _add_months(d, -4)
    if cadence == "semiannual":
        return _add_months(d, -6)
    if cadence == "annual":
        return _add_months(d, -12)
    return d - timedelta(days=1)


def _parse_iso(s: str | None) -> date | None:
    if not s or not str(s).strip():
        return None
    try:
        return date.fromisoformat(str(s).strip()[:10])
    except Exception:
        return None


def next_due_date(rule: dict) -> date | None:
    """Prossima data in cui va creata una registrazione (non oltre la logica della regola)."""
    if not rule.get("active", True):
        return None
    cadence = str(rule.get("cadence") or "")
    if cadence not in CADENCE_IDS:
        return None
    anchor = _parse_iso(rule.get("start_anchor_iso"))
    if anchor is None:
        return None
    last_m = _parse_iso(rule.get("last_materialized_iso"))
    if last_m is None:
        return anchor
    return advance_by_cadence(last_m, cadence)


def count_all_records(db: dict) -> int:
    return sum(len(y.get("records", [])) for y in db.get("years", []))


def _max_source_index_for_year(db: dict, year: int) -> int:
    for yd in db.get("years", []):
        if int(yd.get("year", 0)) == int(year):
            return max((int(r.get("source_index", 0) or 0) for r in yd.get("records", [])), default=0)
    return 0


def _sanitize_line(value: str, *, max_len: int | None = None) -> str:
    out = (value or "").replace("\r", " ").replace("\n", " ").strip()
    return out[:max_len] if max_len is not None else out


def _periodic_auto_note_suffix(cadence: str, year: int, movement_date_iso: str) -> str | None:
    """Suffisso data da aggiungere alla nota per alcune cadenze (anno/mese o solo anno)."""
    c = str(cadence or "")
    if c in {"monthly", "bimonthly", "quarterly"}:
        return f"{year:04d}/{int(movement_date_iso[5:7]):02d}"
    if c == "annual":
        return f"{year:04d}"
    return None


def build_periodic_record(
    db: dict,
    rule: dict,
    movement_date_iso: str,
    registration_number: int,
) -> dict:
    """Costruisce un record come immissione manuale, con source_file periodic."""
    tpl: dict[str, Any] = rule.get("template") or {}
    y = int(movement_date_iso[:4])
    si = _max_source_index_for_year(db, y) + 1
    rid = str(rule.get("id") or uuid.uuid4())
    legacy_key = f"APP:periodic:{rid}:{movement_date_iso}:{si}"
    giro = bool(tpl.get("is_giroconto"))
    acc2_code = str(tpl.get("account_secondary_code") or "") if giro else ""
    acc2_name = str(tpl.get("account_secondary_name") or "") if giro else ""
    acc2_flags = str(tpl.get("account_secondary_flags") or "")
    chq = _sanitize_line(str(tpl.get("cheque") or ""), max_len=MAX_CHEQUE_LEN) or "-"
    note = _sanitize_line(str(tpl.get("note") or ""), max_len=MAX_RECORD_NOTE_LEN) or "-"
    cadence = str(rule.get("cadence") or "")
    suffix = _periodic_auto_note_suffix(cadence, y, movement_date_iso)
    if suffix:
        # Suffisso data dell’istanza; se c’è testo manuale nella nota modello, si concatena (non si sostituisce).
        base = (note or "").strip()
        if not base or base == "-":
            note = suffix
        else:
            merged = f"{base.rstrip()} {suffix}"
            note = _sanitize_line(merged, max_len=MAX_RECORD_NOTE_LEN) or suffix
    amt_eur = str(tpl.get("amount_eur") or "0.00")
    amt_dec = Decimal(str(amt_eur.replace(",", ".")))
    return {
        "year": y,
        "source_folder": "APP",
        "source_file": "periodic",
        "source_index": si,
        "legacy_registration_number": si,
        "legacy_registration_key": legacy_key,
        "registration_number": registration_number,
        "periodic_rule_id": rid,
        "date_iso": movement_date_iso,
        "category_code": str(tpl.get("category_code") or ""),
        "category_name": str(tpl.get("category_name") or ""),
        "category_note": str(tpl.get("category_note") or ""),
        "account_primary_code": str(tpl.get("account_primary_code") or ""),
        "account_primary_flags": str(tpl.get("account_primary_flags") or ""),
        "account_primary_with_flags": str(tpl.get("account_primary_with_flags") or tpl.get("account_primary_code") or ""),
        "account_primary_name": str(tpl.get("account_primary_name") or ""),
        "account_secondary_code": acc2_code,
        "account_secondary_flags": acc2_flags,
        "account_secondary_with_flags": (
            f"{acc2_code}{acc2_flags}" if acc2_code and acc2_flags else (acc2_code or "")
        ),
        "account_secondary_name": acc2_name,
        "amount_eur": format_money(amt_dec),
        "amount_lire_original": None,
        "note": note,
        "cheque": chq,
        "raw_flags": "",
        "is_cancelled": False,
        "source_currency": "E",
        "display_currency": "E",
        "display_amount": format_money(amt_dec),
        "raw_record": "",
    }


_PLAN_REF_YEAR = 2026


def _chart_clone_template_for_periodiche(db: dict) -> dict | None:
    for y in db.get("years", []) or []:
        if int(y.get("year", 0)) == _PLAN_REF_YEAR:
            return y
    ys = db.get("years", []) or []
    if not ys:
        return None
    return max(ys, key=lambda yy: int(yy["year"]))


def ensure_year_bucket(db: dict, target_year: int) -> dict:
    import json

    for y in db.get("years", []):
        if int(y.get("year", 0)) == int(target_year):
            return y
    if not db.get("years"):
        new_y = {
            "year": int(target_year),
            "folder": "",
            "source_files": {},
            "legacy_saldi": None,
            "categories": [{"code": "1", "name": "+Nuova", "note": None}],
            "accounts": [{"code": "1", "name": ""}],
            "records": [],
        }
        db.setdefault("years", []).append(new_y)
        db["years"].sort(key=lambda yy: int(yy["year"]))
        return new_y
    template = _chart_clone_template_for_periodiche(db)
    if not template:
        template = max(db["years"], key=lambda yy: int(yy["year"]))
    new_y = {
        "year": int(target_year),
        "accounts": json.loads(json.dumps(template.get("accounts", []))),
        "categories": json.loads(json.dumps(template.get("categories", []))),
        "records": [],
    }
    db["years"].append(new_y)
    db["years"].sort(key=lambda yy: int(yy["year"]))
    return new_y


def materialize_one_occurrence(db: dict, rule: dict, today: date) -> bool:
    """
    Se la regola è attiva e la prossima scadenza è <= oggi, crea una registrazione e aggiorna last_materialized_iso.
    Ritorna True se ha creato.
    """
    ensure_periodic_registrations(db)
    if not rule.get("active", True):
        return False
    nd = next_due_date(rule)
    if nd is None or nd > today:
        return False
    iso = nd.isoformat()
    reg_n = count_all_records(db) + 1
    rec = build_periodic_record(db, rule, iso, reg_n)
    yb = ensure_year_bucket(db, int(rec["year"]))
    yb["records"].append(rec)
    rule["last_materialized_iso"] = iso
    return True


def materialize_all_due(db: dict, today: date, *, max_total: int = 2000) -> int:
    """Esegue passate finché ci sono scadenze da soddisfare. Ritorna il numero di registrazioni create."""
    ensure_periodic_registrations(db)
    created = 0
    while created < max_total:
        progressed = False
        for rule in db["periodic_registrations"]:
            if materialize_one_occurrence(db, rule, today):
                created += 1
                progressed = True
        if not progressed:
            break
    return created


def list_due_rules(db: dict, today: date) -> list[dict]:
    """Regole attive con prossima creazione <= oggi (almeno una occorrenza in sospeso)."""
    ensure_periodic_registrations(db)
    out: list[dict] = []
    for rule in db["periodic_registrations"]:
        if not rule.get("active", True):
            continue
        nd = next_due_date(rule)
        if nd is not None and nd <= today:
            out.append(rule)
    return out


def new_rule_id() -> str:
    return str(uuid.uuid4())
