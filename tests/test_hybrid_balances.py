from __future__ import annotations

import unittest
from decimal import Decimal

from balance_engine import (
    cancelled_imported_records_adjustment,
    compute_absolute_balances,
    imported_active_records_edit_adjustment,
    consolidated_base_balances,
    new_records_effect,
    parse_euro_amount,
)


def _legacy_raw_record(
    *,
    amount_eur: str,
    category_code: str = "02",
    account_primary_code: str = "1",
    account_secondary_code: str = " ",
) -> str:
    """Record legacy minimo, lungo 121 caratteri, con i campi usati dal ricalcolo saldi."""
    chars = list(" " * 121)
    chars[0:8] = list("20250101")
    chars[23:37] = list(amount_eur.replace(".", ",").rjust(14))
    chars[37:39] = list(category_code.rjust(2))
    chars[39:40] = list(account_primary_code[:1])
    chars[42:43] = list(account_secondary_code[:1])
    chars[120:121] = list("X")
    return "".join(chars)


def _db_with_consolidated_2026_balance(*records: dict) -> dict:
    accounts = [
        {"code": "1", "name": "Cassa"},
        {"code": "2", "name": "Banca"},
    ]
    categories = [
        {"code": "1", "name": "=Girata conto/conto"},
        {"code": "2", "name": "-Spese"},
    ]
    return {
        "years": [
            {
                "year": 2025,
                "accounts": accounts,
                "categories": categories,
                "records": list(records),
            },
            {
                "year": 2026,
                "accounts": accounts,
                "categories": categories,
                "legacy_saldi": {"amounts": ["1000.00", "2000.00"]},
                "records": [],
            },
        ]
    }


class HybridBalancesTests(unittest.TestCase):
    def test_parse_euro_amount_accepts_at_most_two_decimals_without_rounding(self) -> None:
        self.assertEqual(parse_euro_amount("12"), Decimal("12"))
        self.assertEqual(parse_euro_amount("12.3"), Decimal("12.3"))
        self.assertEqual(parse_euro_amount("12,30"), Decimal("12.30"))

    def test_parse_euro_amount_rejects_more_than_two_decimals(self) -> None:
        with self.assertRaises(ValueError):
            parse_euro_amount("12.345")

    def test_consolidated_base_balances_follow_account_codes_after_reorder(self) -> None:
        db = {
            "years": [
                {
                    "year": 2026,
                    "accounts": [
                        {"code": "01", "name": "Cassa"},
                        {"code": "02", "name": "Banca"},
                    ],
                    "legacy_saldi": {"amounts": ["1000.00", "2000.00"]},
                    "records": [],
                },
                {
                    "year": 2027,
                    "accounts": [
                        {"code": "2", "name": "Banca"},
                        {"code": "1", "name": "Cassa"},
                    ],
                    "records": [],
                },
            ]
        }

        self.assertEqual(
            consolidated_base_balances(db, 2),
            [Decimal("2000.00"), Decimal("1000.00")],
        )

    def test_consolidated_base_balances_reject_more_than_two_decimals(self) -> None:
        db = _db_with_consolidated_2026_balance()
        db["years"][1]["legacy_saldi"] = {"amounts": ["1000.001", "2000.00"]}

        with self.assertRaises(ValueError):
            consolidated_base_balances(db, 2)

    def test_new_records_effect_includes_app_records_and_giroconto_secondary_side(self) -> None:
        db = _db_with_consolidated_2026_balance()
        db["years"][1]["records"].extend(
            [
                {
                    "year": 2026,
                    "amount_eur": "-30.00",
                    "category_code": "2",
                    "category_name": "-Spese",
                    "account_primary_code": "1",
                    "raw_record": "",
                },
                {
                    "year": 2026,
                    "amount_eur": "100.00",
                    "category_code": "1",
                    "category_name": "=Girata conto/conto",
                    "account_primary_code": "1",
                    "account_secondary_code": "2",
                    "raw_record": "",
                },
                {
                    "year": 2026,
                    "amount_eur": "999.00",
                    "category_code": "2",
                    "category_name": "-Spese",
                    "account_primary_code": "1",
                    "raw_record": _legacy_raw_record(amount_eur="999.00"),
                },
            ]
        )

        self.assertEqual(
            new_records_effect(db),
            [Decimal("70.00"), Decimal("-100.00")],
        )

    def test_cancelled_imported_records_adjustment_reverses_imported_effect(self) -> None:
        db = _db_with_consolidated_2026_balance(
            {
                "year": 2025,
                "amount_eur": "-40.00",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "raw_record": _legacy_raw_record(amount_eur="-40.00"),
                "is_cancelled": True,
            }
        )

        self.assertEqual(
            cancelled_imported_records_adjustment(db),
            [Decimal("40.00"), Decimal("0")],
        )

    def test_imported_active_records_edit_adjustment_uses_current_minus_original(self) -> None:
        db = _db_with_consolidated_2026_balance(
            {
                "year": 2025,
                "amount_eur": "-55.00",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "raw_record": _legacy_raw_record(amount_eur="-40.00"),
            }
        )

        self.assertEqual(
            imported_active_records_edit_adjustment(db),
            [Decimal("-15.00"), Decimal("0")],
        )

    def test_uses_consolidated_2026_saldo_without_replaying_pre_2026_records(self) -> None:
        db = _db_with_consolidated_2026_balance(
            {
                "year": 2025,
                "date_iso": "2025-06-01",
                "amount_eur": "999.00",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "account_secondary_code": "",
                "raw_record": _legacy_raw_record(amount_eur="999.00"),
            }
        )

        self.assertEqual(
            compute_absolute_balances(db, today_iso="2026-05-04"),
            [Decimal("1000.00"), Decimal("2000.00")],
        )

    def test_new_2026_records_are_added_to_consolidated_saldo(self) -> None:
        db = _db_with_consolidated_2026_balance()
        db["years"][1]["records"].append(
            {
                "year": 2026,
                "date_iso": "2026-02-01",
                "amount_eur": "-25.50",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "account_secondary_code": "",
                "raw_record": "",
            }
        )

        self.assertEqual(
            compute_absolute_balances(db, today_iso="2026-05-04"),
            [Decimal("974.50"), Decimal("2000.00")],
        )

    def test_editing_imported_pre_2026_record_adjusts_consolidated_saldo_by_delta(self) -> None:
        db = _db_with_consolidated_2026_balance(
            {
                "year": 2025,
                "date_iso": "2025-06-01",
                "amount_eur": "-120.00",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "account_secondary_code": "",
                "raw_record": _legacy_raw_record(amount_eur="-100.00"),
            }
        )

        self.assertEqual(
            compute_absolute_balances(db, today_iso="2026-05-04"),
            [Decimal("980.00"), Decimal("2000.00")],
        )

    def test_cancelling_imported_pre_2026_record_removes_it_from_consolidated_saldo(self) -> None:
        db = _db_with_consolidated_2026_balance(
            {
                "year": 2025,
                "date_iso": "2025-06-01",
                "amount_eur": "-100.00",
                "category_code": "2",
                "category_name": "-Spese",
                "account_primary_code": "1",
                "account_secondary_code": "",
                "is_cancelled": True,
                "raw_record": _legacy_raw_record(amount_eur="-100.00"),
            }
        )

        self.assertEqual(
            compute_absolute_balances(db, today_iso="2026-05-04"),
            [Decimal("1100.00"), Decimal("2000.00")],
        )


if __name__ == "__main__":
    unittest.main()
