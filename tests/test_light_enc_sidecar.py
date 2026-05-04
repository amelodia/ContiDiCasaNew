from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from light_enc_sidecar import (
    LIGHT_RECORD_ID_KEY,
    light_enc_path_for_primary,
    light_window_start_iso,
    merge_light_new_records_into_main,
    record_in_light_window,
)


class LightPathTests(unittest.TestCase):
    def test_light_path_adds_single_suffix(self) -> None:
        self.assertEqual(
            light_enc_path_for_primary(Path("/tmp/conti_utente_abc.enc")),
            Path("/tmp/conti_utente_abc_light.enc"),
        )

    def test_light_path_collapses_repeated_light_suffixes(self) -> None:
        self.assertEqual(
            light_enc_path_for_primary(Path("/tmp/conti_utente_abc_light_light.enc")),
            Path("/tmp/conti_utente_abc_light.enc"),
        )


class LightWindowTests(unittest.TestCase):
    def test_light_window_start_is_365_days_before_today(self) -> None:
        self.assertEqual(light_window_start_iso(today=date(2026, 5, 4)), "2025-05-04")

    def test_record_in_light_window_includes_start_date_and_future_dates(self) -> None:
        self.assertTrue(record_in_light_window({"date_iso": "2025-05-04"}, "2025-05-04"))
        self.assertTrue(record_in_light_window({"date_iso": "2026-06-01"}, "2025-05-04"))

    def test_record_in_light_window_excludes_older_or_invalid_dates(self) -> None:
        self.assertFalse(record_in_light_window({"date_iso": "2025-05-03"}, "2025-05-04"))
        self.assertFalse(record_in_light_window({"date_iso": ""}, "2025-05-04"))


class MergeLightRecordsTests(unittest.TestCase):
    def test_merge_adds_only_new_light_records(self) -> None:
        main = {
            "years": [
                {
                    "year": 2026,
                    "accounts": [{"code": "1", "name": "Cassa"}],
                    "categories": [{"code": "1", "name": "+Stipendio"}],
                    "records": [
                        {
                            LIGHT_RECORD_ID_KEY: "existing-id",
                            "source_index": 7,
                            "registration_number": 40,
                        }
                    ],
                }
            ]
        }
        light = {
            "years": [
                {
                    "year": 2026,
                    "records": [
                        {LIGHT_RECORD_ID_KEY: "existing-id", "amount_eur": "1.00"},
                        {LIGHT_RECORD_ID_KEY: "new-id", "amount_eur": "2.00"},
                    ],
                }
            ]
        }

        added = merge_light_new_records_into_main(main, light)

        self.assertEqual(added, 1)
        records = main["years"][0]["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1][LIGHT_RECORD_ID_KEY], "new-id")
        self.assertEqual(records[1]["source_index"], 8)
        self.assertEqual(records[1]["legacy_registration_number"], 8)
        self.assertEqual(records[1]["legacy_registration_key"], "APP:conti_light:2026:new-id")
        self.assertEqual(records[1]["registration_number"], 41)

    def test_merge_creates_missing_year_from_latest_plan(self) -> None:
        main = {
            "years": [
                {
                    "year": 2025,
                    "accounts": [{"code": "1", "name": "Cassa"}],
                    "categories": [{"code": "1", "name": "+Stipendio"}],
                    "records": [],
                }
            ]
        }
        light = {
            "years": [
                {
                    "year": 2026,
                    "records": [{LIGHT_RECORD_ID_KEY: "new-id", "amount_eur": "2.00"}],
                }
            ]
        }

        added = merge_light_new_records_into_main(main, light)

        self.assertEqual(added, 1)
        self.assertEqual([y["year"] for y in main["years"]], [2025, 2026])
        created = main["years"][1]
        self.assertEqual(created["accounts"], [{"code": "1", "name": "Cassa"}])
        self.assertEqual(created["categories"], [{"code": "1", "name": "+Stipendio"}])
        self.assertEqual(created["records"][0]["legacy_registration_key"], "APP:conti_light:2026:new-id")


if __name__ == "__main__":
    unittest.main()
