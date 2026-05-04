"""
Punto di accesso stabile per i saldi contabili.

Regola attuale:

- il saldo consolidato 2026 resta la base contabile quando è disponibile;
- le registrazioni nuove modificano quella base;
- modifiche o annulli su registrazioni importate pre-2026 producono una correzione;
- se manca la base consolidata, l'app usa il ricalcolo completo come fallback storico.

Per ora le formule restano in ``main_app.py``. Questo modulo isola i chiamanti dal file UI
monolitico e rende più semplice spostare i calcoli in modo incrementale.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

PLAN_REFERENCE_YEAR = 2026
LEGACY_DOTAZIONE_YEAR = 1990
LEGACY_DAT_RECORD_LEN = 121


def _latest_year_bucket(db: dict) -> dict | None:
    years = db.get("years") or []
    if not years:
        return None
    return max(years, key=lambda y: int(y.get("year", 0) or 0))


def _year_bucket_for_calendar_year(db: dict, year: int) -> dict | None:
    for yb in db.get("years") or []:
        try:
            if int(yb.get("year", 0) or 0) == int(year):
                return yb
        except (TypeError, ValueError):
            continue
    return None


def _canonical_account_code(code: str) -> str:
    """Chiave stabile per mappare conti: ``06`` e ``6`` coincidono."""
    s = str(code or "").strip()
    if not s:
        return ""
    if s.isdigit():
        return str(int(s))
    return s


def parse_euro_amount(value: object) -> Decimal:
    """Importo euro esatto: massimo due decimali, nessun arrotondamento implicito."""
    amount = Decimal(str(value).strip().replace(",", "."))
    if amount.as_tuple().exponent < -2:
        raise ValueError("Gli importi euro possono avere al massimo due decimali.")
    return amount


def _category_code_int(rec: dict) -> int | None:
    raw = str(rec.get("category_code", "")).strip()
    if not raw.isdigit():
        return None
    return int(raw)


def is_giroconto_record(rec: dict) -> bool:
    """True per giroconto conto/conto, con le stesse regole storiche del desktop."""
    cat_name = str(rec.get("category_name") or "").upper()
    if "GIRATA.CONTO/CONTO" in cat_name or "GIRATA CONTO/CONTO" in cat_name:
        return True
    return _category_code_int(rec) == 1


def is_dotazione_record(rec: dict) -> bool:
    return _category_code_int(rec) == 0


def account_column_index(accounts: list[dict], code_raw: object) -> int:
    """Indice colonna conto nell'ordine corrente, cercando per codice e non per posizione."""
    wanted = _canonical_account_code(str(code_raw or ""))
    if not wanted:
        return -1
    for i, account in enumerate(accounts):
        if _canonical_account_code(str(account.get("code", ""))) == wanted:
            return i
    return -1


def record_contribution_vector(rec: dict, accounts: list[dict], n_accounts: int) -> list[Decimal]:
    """Effetto della singola registrazione sulle colonne conto."""
    out = [Decimal("0") for _ in range(n_accounts)]
    y = int(rec.get("year", 0) or 0)
    if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
        return out
    amount = parse_euro_amount(rec.get("amount_eur", "0"))
    c1_idx = account_column_index(accounts, rec.get("account_primary_code", ""))
    c2_idx = account_column_index(accounts, rec.get("account_secondary_code", ""))
    if 0 <= c1_idx < n_accounts:
        out[c1_idx] += amount
    if is_giroconto_record(rec) and 0 <= c2_idx < n_accounts:
        out[c2_idx] -= amount
    return out


def synthetic_record_from_legacy_dat_raw(raw_line: str, host_year: int) -> dict | None:
    """Ricostruisce i campi contabili minimi dalla riga legacy `.dat` originale."""
    line = raw_line if isinstance(raw_line, str) else str(raw_line)
    if len(line) < LEGACY_DAT_RECORD_LEN:
        return None
    try:
        from import_legacy import format_money, parse_amount

        amount_eur = parse_amount(line[23:37])
        amount_str = format_money(amount_eur)
    except Exception:
        return None
    cat_code_raw = line[37:39].strip()
    acc1_code = line[39:40].strip()
    acc2_code = line[42:43].strip()
    return {
        "year": host_year,
        "amount_eur": amount_str,
        "category_code": cat_code_raw if cat_code_raw.isdigit() else "0",
        "category_name": "",
        "account_primary_code": acc1_code if acc1_code.isdigit() else "",
        "account_secondary_code": acc2_code if acc2_code.isdigit() else "",
    }


def consolidated_base_balances(db: dict, n_accounts: int) -> list[Decimal] | None:
    """Saldi consolidati 2026 allineati all'ordine conti dell'ultimo anno.

    Il saldo consolidato proviene dal blocco ``legacy_saldi`` del bucket 2026. Se gli
    anni successivi hanno lo stesso piano conti ma in ordine diverso, il mapping avviene
    per codice conto e non per posizione.
    """
    y_ref = _year_bucket_for_calendar_year(db, PLAN_REFERENCE_YEAR)
    if not y_ref:
        return None
    ls = y_ref.get("legacy_saldi")
    if not isinstance(ls, dict):
        return None
    raw = ls.get("amounts")
    if not isinstance(raw, list) or not raw:
        return None

    by_code: dict[str, Decimal] = {}
    for i, account in enumerate(y_ref.get("accounts") or []):
        if i >= len(raw):
            break
        code_key = _canonical_account_code(str(account.get("code", "")))
        if not code_key:
            continue
        try:
            by_code[code_key] = parse_euro_amount(raw[i])
        except InvalidOperation:
            by_code[code_key] = Decimal("0")

    latest = _latest_year_bucket(db)
    if not latest:
        return None
    latest_accounts = latest.get("accounts") or []
    out: list[Decimal] = []
    for i in range(n_accounts):
        if i >= len(latest_accounts):
            out.append(Decimal("0"))
            continue
        code_key = _canonical_account_code(str(latest_accounts[i].get("code", "")))
        if not code_key:
            code_key = str(i + 1)
        out.append(by_code.get(code_key, Decimal("0")))
    return out


def new_records_effect(db: dict) -> list[Decimal]:
    """Effetto netto sui conti delle registrazioni create nell'app.

    Sono escluse righe annullate, righe importate legacy (``raw_record`` pieno) e scarichi
    del saldo virtuale. Le girate conto/conto incidono anche sul conto secondario.
    """
    latest = _latest_year_bucket(db)
    if not latest:
        return []
    accounts = latest.get("accounts") or []
    n_accounts = len(accounts)
    balances = [Decimal("0") for _ in accounts]

    for yd in db.get("years") or []:
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled"):
                continue
            if (rec.get("raw_record") or "").strip():
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            y = int(rec.get("year", 0) or 0)
            if is_dotazione_record(rec) and y != LEGACY_DOTAZIONE_YEAR:
                continue
            amount = parse_euro_amount(rec.get("amount_eur", "0"))
            c1_idx = account_column_index(accounts, rec.get("account_primary_code", ""))
            c2_idx = account_column_index(accounts, rec.get("account_secondary_code", ""))
            if 0 <= c1_idx < n_accounts:
                balances[c1_idx] += amount
            if is_giroconto_record(rec) and 0 <= c2_idx < n_accounts:
                balances[c2_idx] -= amount
    return balances


def cancelled_imported_records_adjustment(db: dict) -> list[Decimal]:
    """Correzione per righe importate annullate dopo il saldo consolidato.

    Il saldo consolidato contiene ancora l'effetto originario della riga importata:
    annullarla in app deve quindi aggiungere l'effetto opposto.
    """
    latest = _latest_year_bucket(db)
    if not latest:
        return []
    accounts = latest.get("accounts") or []
    n_accounts = len(accounts)
    adj = [Decimal("0") for _ in accounts]

    latest_year = int(latest.get("year", 0) or 0)
    for yd in db.get("years") or []:
        y = int(yd.get("year", 0) or 0)
        if y > latest_year:
            continue
        for rec in yd.get("records") or []:
            if not rec.get("is_cancelled"):
                continue
            if not (rec.get("raw_record") or "").strip():
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            ry = int(rec.get("year", 0) or 0)
            if is_dotazione_record(rec) and ry != LEGACY_DOTAZIONE_YEAR:
                continue
            amount = -parse_euro_amount(rec.get("amount_eur", "0"))
            c1_idx = account_column_index(accounts, rec.get("account_primary_code", ""))
            c2_idx = account_column_index(accounts, rec.get("account_secondary_code", ""))
            if 0 <= c1_idx < n_accounts:
                adj[c1_idx] += amount
            if is_giroconto_record(rec) and 0 <= c2_idx < n_accounts:
                adj[c2_idx] -= amount
    return adj


def imported_active_records_edit_adjustment(db: dict) -> list[Decimal]:
    """Correzione per righe importate ancora attive ma modificate in app.

    Aggiunge ``contributo_attuale - contributo_originale_raw`` per ogni riga importata
    non annullata. Questo mantiene valido il saldo consolidato senza rigiocare tutto lo
    storico pre-2026.
    """
    latest = _latest_year_bucket(db)
    if not latest:
        return []
    accounts = latest.get("accounts") or []
    n_accounts = len(accounts)
    adj = [Decimal("0") for _ in accounts]

    latest_year = int(latest.get("year", 0) or 0)
    for yd in db.get("years") or []:
        y = int(yd.get("year", 0) or 0)
        if y > latest_year:
            continue
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled"):
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            raw = str(rec.get("raw_record") or "").strip()
            if len(raw) < LEGACY_DAT_RECORD_LEN:
                continue
            synth = synthetic_record_from_legacy_dat_raw(raw, y)
            if synth is None:
                continue
            original = record_contribution_vector(synth, accounts, n_accounts)
            current = record_contribution_vector(rec, accounts, n_accounts)
            for i in range(n_accounts):
                adj[i] += current[i] - original[i]
    return adj


def compute_absolute_balances(db: dict, *, today_iso: str) -> list[Decimal] | None:
    """Saldi assoluti per conto, allineati al footer Saldi del desktop."""
    import main_app

    return main_app.hybrid_absolute_balances_for_saldi(
        db,
        today_cancel_cutoff_iso=today_iso,
    )


def compute_balances_at_date(db: dict, *, asof_iso: str) -> list[Decimal] | None:
    """Saldi per conto alla data indicata, allineati al footer Saldi del desktop."""
    import main_app

    return main_app.hybrid_balances_saldo_in_data(db, asof_iso=asof_iso)


def compute_footer_vectors(db: dict, *, today_iso: str | None = None) -> dict[str, Any] | None:
    """Vettori completi del footer Saldi: assoluti, alla data, future, carte e disponibilità."""
    import main_app

    return main_app.saldi_footer_amount_vectors(db, today_iso=today_iso)


def compute_light_saldi_snapshot(db: dict, *, today_iso: str | None = None) -> dict[str, Any] | None:
    """Blocco ``light_saldi`` da scrivere nel sidecar iPhone."""
    import main_app

    return main_app.compute_light_saldi_snapshot(db, today_iso=today_iso)
