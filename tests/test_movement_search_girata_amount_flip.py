#!/usr/bin/env python3
"""Test: ricerca Movimenti — Girata sul 2° conto filtra invertendo segno/colore importo."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import (  # noqa: E402
    format_amount_for_movement_search,
    movement_search_flip_amount_for_filtered_account,
)


def _girata(amt: str = "-10.00") -> dict:
    return {
        "year": 2026,
        "category_code": "1",
        "category_name": "Girata conto/conto",
        "account_primary_name": "CC.PP.TT",
        "account_secondary_name": "Cassa",
        "amount_eur": amt,
    }


class TestMovementSearchGirataAmountFlip(unittest.TestCase):
    def test_no_filter_no_flip(self) -> None:
        rec = _girata()
        self.assertFalse(
            movement_search_flip_amount_for_filtered_account(
                rec, filter_account_norm="", account_1_name="CC.PP.TT", account_2_name="Cassa"
            )
        )

    def test_filter_primary_no_flip(self) -> None:
        rec = _girata()
        self.assertFalse(
            movement_search_flip_amount_for_filtered_account(
                rec,
                filter_account_norm="cc.pp.tt",
                account_1_name="CC.PP.TT",
                account_2_name="Cassa",
            )
        )
        text, tag = format_amount_for_movement_search(
            rec,
            filter_account_norm="cc.pp.tt",
            account_1_name="CC.PP.TT",
            account_2_name="Cassa",
        )
        self.assertEqual(tag, "neg")
        self.assertTrue(text.startswith("-") or "-" in text[:3])

    def test_filter_secondary_flips(self) -> None:
        rec = _girata("-25.50")
        self.assertTrue(
            movement_search_flip_amount_for_filtered_account(
                rec,
                filter_account_norm="cassa",
                account_1_name="CC.PP.TT",
                account_2_name="Cassa",
            )
        )
        text, tag = format_amount_for_movement_search(
            rec,
            filter_account_norm="cassa",
            account_1_name="CC.PP.TT",
            account_2_name="Cassa",
        )
        self.assertEqual(tag, "pos")
        self.assertTrue(text.startswith("+"))

    def test_non_girata_no_flip(self) -> None:
        rec = {
            "year": 2026,
            "category_code": "3",
            "category_name": "Spese",
            "account_primary_name": "CC.PP.TT",
            "account_secondary_name": "Cassa",
            "amount_eur": "-10.00",
        }
        self.assertFalse(
            movement_search_flip_amount_for_filtered_account(
                rec,
                filter_account_norm="cassa",
                account_1_name="CC.PP.TT",
                account_2_name="Cassa",
            )
        )


if __name__ == "__main__":
    unittest.main()
