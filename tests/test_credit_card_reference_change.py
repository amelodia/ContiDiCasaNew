#!/usr/bin/env python3
"""Test: cambio credit_card_reference_code sposta le spese CC in Saldi."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import (  # noqa: E402
    compute_spese_cc_footer_amounts,
    propagate_account_credit_card_reference_by_code,
    reference_accounts_for_credit_card,
    validate_credit_card_reference_code,
)


def _minimal_db() -> dict:
    """Piano: 1=BancaA, 2=Carta, 3=BancaB; una riga attiva sulla carta."""
    return {
        "years": [
            {
                "year": 2026,
                "accounts": [
                    {"code": "1", "name": "BancaA"},
                    {
                        "code": "2",
                        "name": "CartaX",
                        "credit_card": True,
                        "credit_card_reference_code": "1",
                    },
                    {"code": "3", "name": "BancaB"},
                    {"code": "4", "name": "Cassa"},
                    {"code": "5", "name": "VIRTUALE"},
                ],
                "categories": [{"code": "1", "name": "Varie"}],
                "records": [
                    {
                        "year": 2026,
                        "date_iso": "2026-06-01",
                        "category_code": "1",
                        "account_primary_code": "2",
                        "account_secondary_code": "",
                        "amount_eur": "-50.00",
                        "is_cancelled": False,
                        "source_folder": "APP",
                        "source_file": "manual",
                        "source_index": 1,
                    }
                ],
            }
        ]
    }


class TestCreditCardReferenceChange(unittest.TestCase):
    def test_spese_cc_follow_reference_code(self) -> None:
        db = _minimal_db()
        # Indici: 0 BancaA, 1 Carta (-100 saldo assoluto finto), 2 BancaB
        saldo = [Decimal("1000.00"), Decimal("-100.00"), Decimal("500.00"), Decimal("0"), Decimal("0")]
        before = compute_spese_cc_footer_amounts(db, saldo)
        self.assertEqual(before[0], Decimal("-100.00"))  # su BancaA
        self.assertEqual(before[2], Decimal("0"))

        propagate_account_credit_card_reference_by_code(db, "2", "3")
        self.assertEqual(
            db["years"][0]["accounts"][1]["credit_card_reference_code"],
            "3",
        )
        after = compute_spese_cc_footer_amounts(db, saldo)
        self.assertEqual(after[0], Decimal("0"))
        self.assertEqual(after[2], Decimal("-100.00"))  # ora su BancaB

    def test_validate_and_reference_list(self) -> None:
        db = _minimal_db()
        choices = reference_accounts_for_credit_card(db)
        codes = {c for _, c in choices}
        self.assertIn("1", codes)
        self.assertIn("3", codes)
        self.assertNotIn("2", codes)
        self.assertNotIn("4", codes)  # Cassa
        self.assertNotIn("5", codes)  # VIRTUALE
        self.assertIsNone(validate_credit_card_reference_code(db, "2", "3"))
        self.assertIsNotNone(validate_credit_card_reference_code(db, "2", "2"))
        self.assertIsNotNone(validate_credit_card_reference_code(db, "2", "4"))
        self.assertIsNotNone(validate_credit_card_reference_code(db, "2", ""))


if __name__ == "__main__":
    unittest.main()
