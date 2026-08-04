#!/usr/bin/env python3
"""Test: riassegnazione conto e riposizionamento del confine **."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import (  # noqa: E402
    apply_account_verification_star_count,
    reanchor_double_star_before_reg_for_account,
    verification_flag_star_equivalent_count,
)


def _rec(code: str, flags: str = "") -> dict:
    return {
        "account_primary_code": code,
        "account_primary_flags": flags,
        "account_primary_with_flags": f"{code}{flags}" if code else "",
        "account_secondary_code": "",
        "account_secondary_flags": "",
        "account_secondary_with_flags": "",
        "is_cancelled": False,
    }


class TestReanchorDoubleStarOnAccountChange(unittest.TestCase):
    def test_demotes_later_double_and_promotes_previous(self) -> None:
        prev = _rec("2", "*")
        edited = _rec("2", "")  # riassegnata a conto 2, senza *
        later = _rec("2", "**")
        ordered = [(10, prev), (20, edited), (30, later)]
        changed = reanchor_double_star_before_reg_for_account(
            ordered, account_code="2", before_reg_n=20
        )
        self.assertTrue(changed)
        self.assertEqual(verification_flag_star_equivalent_count(str(later["account_primary_flags"])), 1)
        self.assertEqual(verification_flag_star_equivalent_count(str(prev["account_primary_flags"])), 2)
        self.assertEqual(later["account_primary_with_flags"], "2*")
        self.assertEqual(prev["account_primary_with_flags"], "2**")

    def test_noop_when_no_later_double(self) -> None:
        prev = _rec("2", "*")
        edited = _rec("2", "")
        later = _rec("2", "*")
        ordered = [(10, prev), (20, edited), (30, later)]
        changed = reanchor_double_star_before_reg_for_account(
            ordered, account_code="2", before_reg_n=20
        )
        self.assertFalse(changed)
        self.assertEqual(prev["account_primary_flags"], "*")
        self.assertEqual(later["account_primary_flags"], "*")

    def test_secondary_side_and_digit_padding(self) -> None:
        prev = {
            "account_primary_code": "9",
            "account_primary_flags": "",
            "account_primary_with_flags": "9",
            "account_secondary_code": "08",
            "account_secondary_flags": "*",
            "account_secondary_with_flags": "08*",
            "is_cancelled": False,
        }
        later = {
            "account_primary_code": "8",
            "account_primary_flags": "**",
            "account_primary_with_flags": "8**",
            "account_secondary_code": "",
            "account_secondary_flags": "",
            "account_secondary_with_flags": "",
            "is_cancelled": False,
        }
        ordered = [(5, prev), (6, _rec("1")), (7, later)]
        changed = reanchor_double_star_before_reg_for_account(
            ordered, account_code="8", before_reg_n=6
        )
        self.assertTrue(changed)
        self.assertEqual(verification_flag_star_equivalent_count(str(later["account_primary_flags"])), 1)
        self.assertEqual(verification_flag_star_equivalent_count(str(prev["account_secondary_flags"])), 2)

    def test_apply_account_flags_helper(self) -> None:
        r = _rec("2", "")
        apply_account_verification_star_count(r, "primary", 2)
        self.assertEqual(r["account_primary_flags"], "**")
        self.assertEqual(r["account_primary_with_flags"], "2**")


if __name__ == "__main__":
    unittest.main()
