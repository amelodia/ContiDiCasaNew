from __future__ import annotations

import unittest
from decimal import Decimal

from balance_engine import light_saldi_snapshot_from_footer_vectors


class LightSaldiSnapshotTests(unittest.TestCase):
    def test_snapshot_serializes_footer_vectors_for_ios_light(self) -> None:
        snapshot = light_saldi_snapshot_from_footer_vectors(
            {
                "year_basis": 2026,
                "names": ["Cassa", "Carta"],
                "account_codes": ["1", "2"],
                "saldo_assoluti": [Decimal("100.00"), Decimal("-30.00")],
                "saldo_oggi": [Decimal("90.00"), Decimal("-30.00")],
                "spese_future": [Decimal("10.00"), Decimal("0")],
                "disponibilita_oggi": [Decimal("90.00"), Decimal("0")],
                "spese_cc": [Decimal("-30.00"), Decimal("0")],
                "impegni_carte": [Decimal("-30.00"), Decimal("0")],
                "disponibilita": [Decimal("70.00"), Decimal("0")],
                "disponibilita_assoluta": [Decimal("70.00"), Decimal("0")],
                "is_credit_card": [False, True],
                "totals": {
                    "saldo_assoluti_non_cc": Decimal("100.00"),
                    "spese_future_non_cc": Decimal("10.00"),
                    "disponibilita_oggi_non_cc": Decimal("90.00"),
                    "spese_cc_non_cc": Decimal("-30.00"),
                    "impegni_carte_non_cc": Decimal("-30.00"),
                    "disponibilita_non_cc": Decimal("70.00"),
                    "disponibilita_assoluta_non_cc": Decimal("70.00"),
                },
                "snapshot_date_iso": "2026-05-04",
            }
        )

        self.assertEqual(snapshot["snapshot_date_iso"], "2026-05-04")
        self.assertEqual(snapshot["year_basis"], 2026)
        self.assertEqual(
            snapshot["rows"][0],
            {
                "account_code": "1",
                "account_name": "Cassa",
                "saldo_assoluto": "100.00",
                "saldo_alla_data": "90.00",
                "spese_future": "10.00",
                "disponibilita_oggi": "90.00",
                "spese_cc": "-30.00",
                "impegni_carte": "-30.00",
                "disponibilita": "70.00",
                "disponibilita_assoluta": "70.00",
                "credit_card": False,
            },
        )
        self.assertEqual(snapshot["rows"][1]["credit_card"], True)
        self.assertEqual(snapshot["totals"]["disponibilita_oggi_non_cc"], "90.00")
        self.assertEqual(snapshot["totals"]["disponibilita_non_cc"], "70.00")


if __name__ == "__main__":
    unittest.main()
