#!/usr/bin/env python3
"""Test: candidati verifica — Girata mostra l'altro conto (1° / 2°)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import verification_candidate_category_display  # noqa: E402


class TestVerificationCandidateCategoryDisplay(unittest.TestCase):
    def test_non_girata_unchanged(self) -> None:
        rec = {
            "category_code": "3",
            "category_name": "Spese varie",
            "account_primary_name": "CC.PP.TT",
            "account_secondary_name": "Cassa",
        }
        self.assertEqual(
            verification_candidate_category_display("Spese varie", rec, verified_side="primary"),
            "Spese varie",
        )

    def test_girata_when_verifying_primary_shows_second(self) -> None:
        rec = {
            "category_code": "1",
            "category_name": "Girata conto/conto",
            "account_primary_name": "CC.PP.TT",
            "account_secondary_name": "Cassa",
        }
        self.assertEqual(
            verification_candidate_category_display(
                "Girata conto/conto", rec, verified_side="primary"
            ),
            "Girata conto/conto — 2° conto: Cassa",
        )

    def test_girata_when_verifying_secondary_shows_first(self) -> None:
        rec = {
            "category_code": "1",
            "category_name": "Girata conto/conto",
            "account_primary_name": "BCC.ROMA",
            "account_secondary_name": "CC.PP.TT",
        }
        self.assertEqual(
            verification_candidate_category_display(
                "Girata conto/conto", rec, verified_side="secondary"
            ),
            "Girata conto/conto — 1° conto: BCC.ROMA",
        )


if __name__ == "__main__":
    unittest.main()
