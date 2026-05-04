from __future__ import annotations

import unittest
from decimal import Decimal

from balance_engine import credit_card_column_flags, credit_card_footer_amounts


class CreditCardFooterTests(unittest.TestCase):
    def test_card_balance_is_reported_on_reference_account_when_card_has_movements(self) -> None:
        db = {
            "years": [
                {
                    "year": 2026,
                    "accounts": [
                        {"code": "1", "name": "Conto"},
                        {
                            "code": "2",
                            "name": "Carta",
                            "credit_card": True,
                            "credit_card_reference_code": "1",
                        },
                    ],
                    "records": [
                        {
                            "year": 2026,
                            "category_code": "2",
                            "account_primary_code": "2",
                            "amount_eur": "-45.00",
                        }
                    ],
                }
            ]
        }

        self.assertEqual(
            credit_card_footer_amounts(db, [Decimal("100.00"), Decimal("-45.00")]),
            [Decimal("-45.00"), Decimal("0")],
        )

    def test_card_without_movements_does_not_affect_reference_account(self) -> None:
        db = {
            "years": [
                {
                    "year": 2026,
                    "accounts": [
                        {"code": "1", "name": "Conto"},
                        {
                            "code": "2",
                            "name": "Carta",
                            "credit_card": True,
                            "credit_card_reference_code": "1",
                        },
                    ],
                    "records": [],
                }
            ]
        }

        self.assertEqual(
            credit_card_footer_amounts(db, [Decimal("100.00"), Decimal("-45.00")]),
            [Decimal("0"), Decimal("0")],
        )

    def test_credit_card_flags_follow_latest_account_chart(self) -> None:
        db = {
            "years": [
                {
                    "year": 2026,
                    "accounts": [
                        {"code": "1", "name": "Conto"},
                        {"code": "2", "name": "Carta", "credit_card": True},
                    ],
                }
            ]
        }

        self.assertEqual(credit_card_column_flags(db, 3), [False, True, False])


if __name__ == "__main__":
    unittest.main()
