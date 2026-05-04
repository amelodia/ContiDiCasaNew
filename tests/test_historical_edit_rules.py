from __future__ import annotations

import unittest

from main_app import (
    category_label_is_giroconto,
    historical_record_can_change_category_to,
    record_is_historical_category_note_only,
)


class HistoricalEditRulesTests(unittest.TestCase):
    def test_pre_2022_non_giroconto_allows_only_category_and_note(self) -> None:
        self.assertTrue(
            record_is_historical_category_note_only(
                {
                    "date_iso": "2021-12-31",
                    "category_code": "2",
                    "category_name": "-Spese",
                }
            )
        )

    def test_pre_2022_giroconto_is_not_category_note_only_editable(self) -> None:
        self.assertFalse(
            record_is_historical_category_note_only(
                {
                    "date_iso": "2021-12-31",
                    "category_code": "1",
                    "category_name": "=Girata conto/conto",
                }
            )
        )

    def test_2022_and_later_records_are_not_historical_category_note_only(self) -> None:
        self.assertFalse(
            record_is_historical_category_note_only(
                {
                    "date_iso": "2022-01-01",
                    "category_code": "2",
                    "category_name": "-Spese",
                }
            )
        )

    def test_giroconto_label_is_recognized_across_punctuation_variants(self) -> None:
        self.assertTrue(category_label_is_giroconto("Girata conto/conto"))
        self.assertTrue(category_label_is_giroconto("GIRATA.CONTO/CONTO"))
        self.assertTrue(category_label_is_giroconto("Girata conto conto"))

    def test_historical_record_cannot_change_from_giroconto(self) -> None:
        self.assertFalse(
            historical_record_can_change_category_to(
                {
                    "date_iso": "2021-12-31",
                    "category_code": "1",
                    "category_name": "=Girata conto/conto",
                },
                "-Spese",
            )
        )

    def test_historical_record_cannot_change_to_giroconto(self) -> None:
        self.assertFalse(
            historical_record_can_change_category_to(
                {
                    "date_iso": "2021-12-31",
                    "category_code": "2",
                    "category_name": "-Spese",
                },
                "Girata conto/conto",
            )
        )

    def test_historical_record_can_change_to_non_giroconto_category(self) -> None:
        self.assertTrue(
            historical_record_can_change_category_to(
                {
                    "date_iso": "2021-12-31",
                    "category_code": "2",
                    "category_name": "-Spese",
                },
                "-Casa",
            )
        )


if __name__ == "__main__":
    unittest.main()
