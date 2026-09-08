#!/usr/bin/env python3
"""Test: buchi Movimenti-visibili interrompono l'avanzamento di **; gap sotto floor."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import (  # noqa: E402
    list_verification_gaps_under_double_star_floor,
    verification_post_cutoff_unmarked_breaks_double_star_chain,
    verification_unmarked_movimenti_breaks_double_star_chain,
)


class TestVerificationDoubleStarChainBreak(unittest.TestCase):
    def test_unmarked_in_movimenti_always_breaks(self) -> None:
        self.assertTrue(
            verification_unmarked_movimenti_breaks_double_star_chain(stars=0, in_movimenti=True)
        )
        # Anche se la data sarebbe «prima del cutoff», il buco apre comunque la catena.
        self.assertTrue(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=0,
                date_iso="2026-07-02",
                cutoff_iso="2026-07-31",
                reg_n=29221,
                floor_reg=None,
                in_movimenti=True,
            )
        )

    def test_unmarked_after_cutoff_breaks(self) -> None:
        self.assertTrue(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=0,
                date_iso="2026-08-02",
                cutoff_iso="2026-07-31",
                reg_n=29384,
                floor_reg=29235,
                in_movimenti=True,
            )
        )

    def test_starred_or_hidden_do_not_break(self) -> None:
        self.assertFalse(
            verification_unmarked_movimenti_breaks_double_star_chain(stars=1, in_movimenti=True)
        )
        self.assertFalse(
            verification_unmarked_movimenti_breaks_double_star_chain(stars=0, in_movimenti=False)
        )

    def test_gaps_under_floor_filtered_by_min_date(self) -> None:
        legacy = {
            "account_primary_code": "6",
            "account_primary_flags": "",
            "account_secondary_code": "",
            "account_secondary_flags": "",
            "date_iso": "1994-01-31",
            "category_code": "1",
            "is_cancelled": False,
        }
        recent = {
            "account_primary_code": "6",
            "account_primary_flags": "",
            "account_secondary_code": "",
            "account_secondary_flags": "",
            "date_iso": "2026-07-01",
            "category_code": "1",
            "is_cancelled": False,
        }
        floor_row = {
            "account_primary_code": "6",
            "account_primary_flags": "**",
            "account_secondary_code": "",
            "account_secondary_flags": "",
            "date_iso": "2026-07-18",
            "category_code": "1",
            "is_cancelled": False,
        }
        ordered = [(100, legacy), (200, recent), (300, floor_row)]
        gaps = list_verification_gaps_under_double_star_floor(
            ordered, account_code="6", floor_reg=300, min_date_iso="2025-01-01"
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0][0], 200)


if __name__ == "__main__":
    unittest.main()
