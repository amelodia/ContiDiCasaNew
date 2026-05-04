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

from decimal import Decimal
from typing import Any


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
