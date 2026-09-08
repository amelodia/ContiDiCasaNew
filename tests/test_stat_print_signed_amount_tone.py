#!/usr/bin/env python3
"""Test tone detection for colored statistics print amounts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import _stat_print_signed_amount_tone  # noqa: E402


class TestStatPrintSignedAmountTone(unittest.TestCase):
    def test_pos_neg(self) -> None:
        self.assertEqual(_stat_print_signed_amount_tone("+1.234,56 €"), "pos")
        self.assertEqual(_stat_print_signed_amount_tone("-12,00 €"), "neg")
        self.assertEqual(_stat_print_signed_amount_tone("−5,5 %"), "neg")
        self.assertEqual(_stat_print_signed_amount_tone("+3,2 %"), "pos")

    def test_empty_or_unsigned(self) -> None:
        self.assertIsNone(_stat_print_signed_amount_tone(""))
        self.assertIsNone(_stat_print_signed_amount_tone("—"))
        self.assertIsNone(_stat_print_signed_amount_tone("0,00 €"))
        self.assertIsNone(_stat_print_signed_amount_tone("TOTALI"))


if __name__ == "__main__":
    unittest.main()
