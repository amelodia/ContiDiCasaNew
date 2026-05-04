from __future__ import annotations

import unittest
from decimal import Decimal

from import_legacy import format_euro_it, normalize_euro_input


class NormalizeEuroInputTests(unittest.TestCase):
    def test_accepts_italian_decimal_comma(self) -> None:
        self.assertEqual(normalize_euro_input("1234,56"), Decimal("1234.56"))

    def test_accepts_thousands_separator_and_decimal_comma(self) -> None:
        self.assertEqual(normalize_euro_input("1.234,56"), Decimal("1234.56"))

    def test_accepts_decimal_dot(self) -> None:
        self.assertEqual(normalize_euro_input("-12.50"), Decimal("-12.50"))

    def test_accepts_unicode_minus(self) -> None:
        self.assertEqual(normalize_euro_input("−12,50"), Decimal("-12.50"))

    def test_rejects_more_than_two_decimal_places(self) -> None:
        with self.assertRaises(ValueError):
            normalize_euro_input("12,345")

    def test_rejects_amount_above_limit(self) -> None:
        with self.assertRaises(ValueError):
            normalize_euro_input("1000000000,00")

    def test_rejects_empty_amount(self) -> None:
        with self.assertRaises(ValueError):
            normalize_euro_input("   ")


class FormatEuroItTests(unittest.TestCase):
    def test_formats_positive_amount_italian_style(self) -> None:
        self.assertEqual(format_euro_it(Decimal("1234.5")), "1.234,50")

    def test_formats_negative_amount_italian_style(self) -> None:
        self.assertEqual(format_euro_it(Decimal("-9876543.21")), "-9.876.543,21")


if __name__ == "__main__":
    unittest.main()
