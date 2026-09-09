#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from estratto_conto_pdf import (  # noqa: E402
    _looks_like_amex_estratto,
    _parse_statement_text,
)


def _movement_line(date: str, amount: str, amount_column: int, note: str) -> str:
    prefix = f" {date}                 {date}"
    return prefix + (" " * (amount_column - len(prefix))) + amount + "           " + note


class TestBancoPostaAccreditiSign(unittest.TestCase):
    def test_layout_columns_determine_sign(self) -> None:
        text = "\n".join(
            [
                "Estratto conto poste.it",
                "Data contabile Data valuta Addebiti Accrediti Descrizione",
                _movement_line("01/08/26", "183,00", 152, "PAGAMENTO POS"),
                _movement_line("02/08/26", "6.992,33", 294, "ACCREDITAMENTO PENSIONE"),
                " 31/08/26" + (" " * 150) + "183,00           TOTALE USCITE",
                " 31/08/26" + (" " * 292) + "6.992,33           TOTALE ENTRATE",
                " 31/08/26" + (" " * 330) + "6.809,33           SALDO FINALE",
            ]
        )

        rows, closing_balance = _parse_statement_text(text, max_note_len=500)

        self.assertEqual([row["amount"] for row in rows], [Decimal("-183.00"), Decimal("6992.33")])
        self.assertEqual(closing_balance, Decimal("6809.33"))
        self.assertFalse(any("TOTALE" in str(row["note"]).upper() for row in rows))

    def test_american_express_beneficiary_does_not_select_amex_parser(self) -> None:
        text = "\n".join(
            [
                "Estratto conto poste.it",
                _movement_line(
                    "05/08/26",
                    "5.728,96",
                    136,
                    "DOMICILIAZIONE AMERICAN EXPRESS ITA",
                ),
                _movement_line("21/08/26", "1.000,00", 294, "BONIFICO SEPA DA CLIENTE"),
            ]
        )

        self.assertFalse(_looks_like_amex_estratto(text))
        rows, _ = _parse_statement_text(text, max_note_len=500)
        self.assertEqual([row["amount"] for row in rows], [Decimal("-5728.96"), Decimal("1000.00")])


if __name__ == "__main__":
    unittest.main()
