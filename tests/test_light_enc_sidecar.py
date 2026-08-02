"""Test merge sidecar light → database completo (``light_enc_sidecar.py``)."""
from __future__ import annotations

import copy
import unittest

from light_enc_sidecar import (
    LIGHT_EDIT_SUPERSEDES_LEGACY,
    LIGHT_EDIT_SUPERSEDES_SI,
    LIGHT_EDIT_SUPERSEDES_YEAR,
    LIGHT_RECORD_ID_KEY,
    merge_light_new_records_into_main,
    merge_light_sidecar_into_main,
    upsert_light_session_records_in_main,
)


def _year_bucket(year: int, records: list[dict] | None = None) -> dict:
    return {
        "year": year,
        "accounts": [],
        "categories": [],
        "records": records or [],
    }


def _rec(
    *,
    rid: str = "",
    year: int = 2025,
    amount=10,
    legacy: str = "",
    source_index: int = 1,
    date_iso: str = "2025-03-01",
    extra: dict | None = None,
) -> dict:
    lk = legacy or (f"APP:conti_light:{year}:{rid}" if rid else "")
    out = {
        "year": year,
        LIGHT_RECORD_ID_KEY: rid,
        "legacy_registration_key": lk,
        "source_index": source_index,
        "date_iso": date_iso,
        "amount": amount,
    }
    if extra:
        out.update(extra)
    return out


class LightEncSidecarMergeTests(unittest.TestCase):
    def test_merge_new_record_by_uuid(self) -> None:
        main = {"years": [_year_bucket(2025)]}
        light = {"years": [_year_bucket(2025, [_rec(rid="uuid-new")])]}
        n_new, n_up = merge_light_sidecar_into_main(main, light)
        self.assertEqual((n_new, n_up), (1, 0))
        self.assertEqual(len(main["years"][0]["records"]), 1)
        self.assertEqual(
            main["years"][0]["records"][0][LIGHT_RECORD_ID_KEY],
            "uuid-new",
        )

    def test_upsert_updates_existing_amount(self) -> None:
        main = {
            "years": [
                _year_bucket(
                    2025,
                    [_rec(rid="uuid-x", amount=5, legacy="APP:conti_light:2025:uuid-x")],
                )
            ]
        }
        light = {
            "years": [
                _year_bucket(
                    2025,
                    [_rec(rid="uuid-x", amount=99, legacy="APP:conti_light:2025:uuid-x")],
                )
            ]
        }
        n_up = upsert_light_session_records_in_main(main, light)
        self.assertEqual(n_up, 1)
        self.assertEqual(main["years"][0]["records"][0]["amount"], 99)
        n_new = merge_light_new_records_into_main(main, light)
        self.assertEqual(n_new, 0)

    def test_preserves_account_verification_fields_on_upsert(self) -> None:
        main_rec = _rec(
            rid="uuid-v",
            amount=5,
            extra={
                "account_primary_flags": "*",
                "account_primary_with_flags": "Cassa *",
            },
        )
        main = {"years": [_year_bucket(2025, [copy.deepcopy(main_rec)])]}
        light_rec = _rec(rid="uuid-v", amount=99, extra={"account_primary_flags": ""})
        light = {"years": [_year_bucket(2025, [light_rec])]}
        upsert_light_session_records_in_main(main, light)
        updated = main["years"][0]["records"][0]
        self.assertEqual(updated["amount"], 99)
        self.assertEqual(updated["account_primary_flags"], "*")
        self.assertEqual(updated["account_primary_with_flags"], "Cassa *")

    def test_supersedes_removes_old_year_row(self) -> None:
        main = {
            "years": [
                _year_bucket(
                    2024,
                    [
                        _rec(
                            rid="",
                            year=2024,
                            legacy="OLD:1",
                            source_index=3,
                            amount=1,
                        )
                    ],
                ),
                _year_bucket(2025),
            ]
        }
        light_rec = _rec(rid="uuid-move", year=2025, amount=50)
        light_rec[LIGHT_EDIT_SUPERSEDES_YEAR] = 2024
        light_rec[LIGHT_EDIT_SUPERSEDES_LEGACY] = "OLD:1"
        light_rec[LIGHT_EDIT_SUPERSEDES_SI] = 3
        light = {"years": [_year_bucket(2025, [light_rec])]}
        n_new, n_up = merge_light_sidecar_into_main(main, light)
        self.assertGreater(n_new + n_up, 0)
        self.assertEqual(len(main["years"][0]["records"]), 0)
        y2025 = next(y for y in main["years"] if y["year"] == 2025)
        self.assertEqual(len(y2025["records"]), 1)
        self.assertEqual(y2025["records"][0][LIGHT_RECORD_ID_KEY], "uuid-move")

    def test_cancelled_flag_propagates_via_upsert(self) -> None:
        main = {
            "years": [
                _year_bucket(
                    2025,
                    [_rec(rid="uuid-c", amount=10, extra={"is_cancelled": False})],
                )
            ]
        }
        light = {
            "years": [
                _year_bucket(
                    2025,
                    [_rec(rid="uuid-c", amount=10, extra={"is_cancelled": True})],
                )
            ]
        }
        n_up = upsert_light_session_records_in_main(main, light)
        self.assertEqual(n_up, 1)
        self.assertTrue(main["years"][0]["records"][0]["is_cancelled"])

    def test_light_sidecar_copies_without_ios_id_do_not_count_as_updates(self) -> None:
        """Righe del light già nel completo (senza conti_light_record_id) non sono «modifiche»."""
        shared = _rec(rid="", legacy="DESKTOP:2025:1", amount=42)
        main = {"years": [_year_bucket(2025, [copy.deepcopy(shared)])]}
        light = {"years": [_year_bucket(2025, [copy.deepcopy(shared)])]}
        n_new, n_up = merge_light_sidecar_into_main(main, light)
        self.assertEqual((n_new, n_up), (0, 0))

    def test_identical_ios_row_does_not_count_as_update(self) -> None:
        rec = _rec(rid="uuid-same", amount=10)
        main = {"years": [_year_bucket(2025, [copy.deepcopy(rec)])]}
        light = {"years": [_year_bucket(2025, [copy.deepcopy(rec)])]}
        n_new, n_up = merge_light_sidecar_into_main(main, light)
        self.assertEqual((n_new, n_up), (0, 0))


if __name__ == "__main__":
    unittest.main()
