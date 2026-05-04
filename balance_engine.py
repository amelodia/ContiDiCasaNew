"""
Punto di accesso stabile per i saldi contabili.

Regola attuale:

- il saldo consolidato 2026 resta la base contabile quando è disponibile;
- le registrazioni nuove modificano quella base;
- modifiche o annulli su registrazioni importate pre-2026 producono una correzione;
- se manca la base consolidata, l'app usa il ricalcolo completo come fallback storico.

Questo modulo contiene il cuore dei calcoli saldi. ``main_app.py`` mantiene wrapper
compatibili per l'UI e per i casi legacy non ancora separati.
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


def account_codes_equal(a: object, b: object) -> bool:
    return _canonical_account_code(str(a or "")) == _canonical_account_code(str(b or "")) != ""


def account_has_non_cancelled_movement_touching_code(db: dict, account_code: str) -> bool:
    """True se una registrazione attiva coinvolge il codice conto indicato."""
    code = str(account_code or "").strip()
    if not code:
        return False
    for yd in db.get("years") or []:
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled"):
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            if account_codes_equal(rec.get("account_primary_code", ""), code):
                return True
            if is_giroconto_record(rec) and account_codes_equal(rec.get("account_secondary_code", ""), code):
                return True
    return False


def credit_card_column_flags(db: dict, n_accounts: int) -> list[bool]:
    """True per indice conto se il conto corrente è marcato come carta di credito."""
    if n_accounts <= 0:
        return []
    latest = _latest_year_bucket(db)
    if not latest:
        return [False] * n_accounts
    accounts = latest.get("accounts") or []
    return [bool(accounts[i].get("credit_card")) if i < len(accounts) else False for i in range(n_accounts)]


def credit_card_commitments_by_account_index(db: dict) -> list[Decimal]:
    """Impegni carta espliciti per conto; per ora non ci sono righe dedicate e resta un vettore zero."""
    latest = _latest_year_bucket(db)
    if not latest:
        return []
    return [Decimal("0") for _ in latest.get("accounts") or []]


def credit_card_footer_amounts(db: dict, saldo_assoluti: list[Decimal]) -> list[Decimal]:
    """Riga «Spese per carte di credito» per il footer Saldi."""
    n_accounts = len(saldo_assoluti)
    if n_accounts == 0:
        return []
    latest = _latest_year_bucket(db)
    if not latest:
        return []
    accounts = latest.get("accounts") or []
    base = credit_card_commitments_by_account_index(db)
    out = [(base[i] if i < len(base) else Decimal("0")) for i in range(n_accounts)]
    for i in range(min(n_accounts, len(accounts))):
        account = accounts[i]
        if not bool(account.get("credit_card")):
            continue
        ref_code = str(account.get("credit_card_reference_code") or "").strip()
        if not ref_code:
            continue
        ref_index = account_column_index(accounts, ref_code)
        if ref_index < 0 or ref_index >= n_accounts or ref_index == i:
            continue
        card_code = str(account.get("code", "") or "").strip()
        if not account_has_non_cancelled_movement_touching_code(db, card_code):
            continue
        out[ref_index] = out[ref_index] + saldo_assoluti[i]
    return out


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


def record_legacy_stable_key(rec: dict) -> str:
    key = rec.get("legacy_registration_key")
    if isinstance(key, str) and key.strip():
        return key
    return f"{rec.get('year', '')}:{rec.get('source_folder', '')}:{rec.get('source_file', '')}:{rec.get('source_index', '')}"


def imported_record_balance_twin_key(rec: dict) -> tuple[str, str, str, str]:
    stable = str(rec.get("legacy_registration_key") or "").strip() or record_legacy_stable_key(rec)
    return (
        str(rec.get("year", "")).strip(),
        str(rec.get("source_folder", "")).strip(),
        str(rec.get("source_file", "")).strip(),
        stable,
    )


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


def compose_consolidated_absolute_balances(db: dict, n_accounts: int) -> list[Decimal] | None:
    """Saldo assoluto ordinario: base consolidata + delta app + correzioni storico."""
    base = consolidated_base_balances(db, n_accounts)
    if base is None:
        return None
    new_fx = new_records_effect(db)
    canc = cancelled_imported_records_adjustment(db)
    edit_adj = imported_active_records_edit_adjustment(db)
    return [
        base[i]
        + (new_fx[i] if i < len(new_fx) else Decimal("0"))
        + (canc[i] if i < len(canc) else Decimal("0"))
        + (edit_adj[i] if i < len(edit_adj) else Decimal("0"))
        for i in range(n_accounts)
    ]


def future_dated_records_effect(
    db: dict,
    *,
    today_iso: str,
    excluded_import_twin_keys: set[tuple[str, str, str, str]] | None = None,
) -> tuple[int, list[str], list[Decimal]]:
    """Effetto netto delle sole registrazioni con data successiva a ``today_iso``."""
    latest = _latest_year_bucket(db)
    if not latest:
        from datetime import date

        return (date.today().year, [], [])
    latest_year = int(latest.get("year", 0) or 0)
    accounts = latest.get("accounts") or []
    n_accounts = len(accounts)
    excluded = excluded_import_twin_keys or set()
    balances = [Decimal("0") for _ in accounts]

    for yd in db.get("years") or []:
        y = int(yd.get("year", 0) or 0)
        if y > latest_year:
            continue
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled"):
                continue
            if rec.get("is_virtuale_discharge"):
                continue
            if (
                excluded
                and (rec.get("raw_record") or "").strip()
                and imported_record_balance_twin_key(rec) in excluded
            ):
                continue
            ry = int(rec.get("year", 0) or 0)
            if is_dotazione_record(rec) and ry != LEGACY_DOTAZIONE_YEAR:
                continue
            rec_date = str(rec.get("date_iso", "") or "")
            if not rec_date or rec_date <= today_iso:
                continue
            amount = parse_euro_amount(rec.get("amount_eur", "0"))
            c1_idx = account_column_index(accounts, rec.get("account_primary_code", ""))
            c2_idx = account_column_index(accounts, rec.get("account_secondary_code", ""))
            if 0 <= c1_idx < n_accounts:
                balances[c1_idx] += amount
            if is_giroconto_record(rec) and 0 <= c2_idx < n_accounts:
                balances[c2_idx] -= amount

    return latest_year, [str(a.get("name", "") or "") for a in accounts], balances


def balances_at_date(
    db: dict,
    *,
    asof_iso: str,
    absolute_balances: list[Decimal],
    excluded_import_twin_keys: set[tuple[str, str, str, str]] | None = None,
) -> list[Decimal] | None:
    """Saldo alla data: saldi assoluti meno effetto delle registrazioni future."""
    _year, _names, future = future_dated_records_effect(
        db,
        today_iso=asof_iso,
        excluded_import_twin_keys=excluded_import_twin_keys,
    )
    if len(future) != len(absolute_balances):
        return None
    return [absolute_balances[i] - future[i] for i in range(len(absolute_balances))]


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


def light_saldi_snapshot_from_footer_vectors(vectors: dict[str, Any]) -> dict[str, object] | None:
    """Converte i vettori saldi desktop nel blocco JSON ``light_saldi``."""
    if not vectors:
        return None
    names = list(vectors["names"])
    codes = list(vectors["account_codes"])
    abs_vals: list[Decimal] = list(vectors["saldo_assoluti"])
    oggi_vals: list[Decimal] = list(vectors["saldo_oggi"])
    sf_vals: list[Decimal] = list(vectors["spese_future"])
    scc_vals: list[Decimal] = list(vectors["spese_cc"])
    raw_disp_oggi = vectors.get("disponibilita_oggi")
    disp_oggi_vals: list[Decimal] = list(raw_disp_oggi) if raw_disp_oggi else []
    disp_vals: list[Decimal] = list(vectors.get("disponibilita_assoluta") or vectors["disponibilita"])
    is_cc = list(vectors["is_credit_card"])
    rows: list[dict[str, object]] = []
    for i in range(len(names)):
        disp_oggi = disp_oggi_vals[i] if i < len(disp_oggi_vals) else (Decimal("0") if bool(is_cc[i]) else oggi_vals[i])
        rows.append(
            {
                "account_code": str(codes[i]).strip() or str(i + 1),
                "account_name": names[i],
                "saldo_assoluto": str(abs_vals[i]),
                "saldo_alla_data": str(oggi_vals[i]),
                "spese_future": str(sf_vals[i]),
                "disponibilita_oggi": str(disp_oggi),
                "spese_cc": str(scc_vals[i]),
                "impegni_carte": str(scc_vals[i]),
                "disponibilita": str(disp_vals[i]),
                "disponibilita_assoluta": str(disp_vals[i]),
                "credit_card": bool(is_cc[i]),
            }
        )
    totals = vectors["totals"]
    if not isinstance(totals, dict):
        totals = {}
    total_abs = totals.get("saldo_assoluti_non_cc", Decimal("0"))
    total_sf = totals.get("spese_future_non_cc", Decimal("0"))
    total_scc = totals.get("spese_cc_non_cc", Decimal("0"))
    total_disp = totals.get("disponibilita_non_cc", Decimal("0"))
    return {
        "snapshot_date_iso": str(vectors["snapshot_date_iso"]),
        "year_basis": int(vectors["year_basis"]),
        "rows": rows,
        "totals": {
            "saldo_assoluti_non_cc": str(total_abs),
            "spese_future_non_cc": str(total_sf),
            "disponibilita_oggi_non_cc": str(totals.get("disponibilita_oggi_non_cc", total_abs - total_sf)),
            "spese_cc_non_cc": str(total_scc),
            "impegni_carte_non_cc": str(
                totals.get("impegni_carte_non_cc", total_scc)
            ),
            "disponibilita_non_cc": str(total_disp),
            "disponibilita_assoluta_non_cc": str(
                totals.get("disponibilita_assoluta_non_cc", total_disp)
            ),
        },
    }


def compute_light_saldi_snapshot(db: dict, *, today_iso: str | None = None) -> dict[str, Any] | None:
    """Blocco ``light_saldi`` da scrivere nel sidecar iPhone."""
    vectors = compute_footer_vectors(db, today_iso=today_iso)
    if not vectors:
        return None
    return light_saldi_snapshot_from_footer_vectors(vectors)
