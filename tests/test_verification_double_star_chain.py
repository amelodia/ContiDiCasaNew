#!/usr/bin/env python3
"""Test helper: buchi post-cutoff interrompono l'avanzamento di **."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import verification_post_cutoff_unmarked_breaks_double_star_chain  # noqa: E402


class TestVerificationDoubleStarChainBreak(unittest.TestCase):
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

    def test_unmarked_before_cutoff_does_not_use_helper(self) -> None:
        # Gestito dal ramo in-scope di _ver_place_double_star (break su unmarked).
        self.assertFalse(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=0,
                date_iso="2026-07-02",
                cutoff_iso="2026-07-31",
                reg_n=29221,
                floor_reg=None,
                in_movimenti=True,
            )
        )

    def test_starred_or_hidden_do_not_break(self) -> None:
        self.assertFalse(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=1,
                date_iso="2026-08-02",
                cutoff_iso="2026-07-31",
                reg_n=29384,
                floor_reg=None,
                in_movimenti=True,
            )
        )
        self.assertFalse(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=0,
                date_iso="2026-08-02",
                cutoff_iso="2026-07-31",
                reg_n=29384,
                floor_reg=None,
                in_movimenti=False,
            )
        )

    def test_under_or_at_floor_ignored(self) -> None:
        self.assertFalse(
            verification_post_cutoff_unmarked_breaks_double_star_chain(
                stars=0,
                date_iso="2026-08-02",
                cutoff_iso="2026-07-31",
                reg_n=29384,
                floor_reg=29384,
                in_movimenti=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
