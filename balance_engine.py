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
            by_code[code_key] = Decimal(str(raw[i]))
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
