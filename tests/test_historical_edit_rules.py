from __future__ import annotations

import unittest

from main_app import record_is_historical_category_note_only


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


if __name__ == "__main__":
    unittest.main()
