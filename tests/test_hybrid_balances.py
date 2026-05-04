from __future__ import annotations

import unittest
from decimal import Decimal

from balance_engine import compute_absolute_balances


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
