#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main_app import (  # noqa: E402
    _euro_text_with_leading_sign,
    bind_euro_amount_entry_validation,
)


class _FakeVar:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class _FakeEntry:
    def __init__(self, value: str) -> None:
        self.value = value
        self.validate = "none"
        self.validatecommand = None
        self.cursor = 0

    def register(self, callback):
        return callback

    def configure(self, **kwargs) -> None:
        if "validate" in kwargs:
            self.validate = kwargs["validate"]
        if "validatecommand" in kwargs:
            self.validatecommand = kwargs["validatecommand"]

    def cget(self, name: str) -> str:
        return self.validate if name == "validate" else ""

    def bind(self, *_args, **_kwargs) -> None:
        return None

    def after_idle(self, callback) -> None:
        callback()

    def get(self) -> str:
        return self.value

    def delete(self, _first, _last) -> None:
        self.value = ""

    def insert(self, _index, text: str) -> None:
        self.value = text

    def icursor(self, index) -> None:
        self.cursor = len(self.value) if str(index) == "end" else int(index)

    def selection_clear(self) -> None:
        return None


class TestEuroAmountSignEdit(unittest.TestCase):
    def test_plus_replaces_minus_without_changing_amount(self) -> None:
        self.assertEqual(_euro_text_with_leading_sign("-1.234,56", "+"), "+1.234,56")

    def test_minus_replaces_plus_without_changing_amount(self) -> None:
        self.assertEqual(_euro_text_with_leading_sign("+1.234,56", "-"), "-1.234,56")

    def test_unicode_minus_is_normalized(self) -> None:
        self.assertEqual(_euro_text_with_leading_sign("1.234,56", "−"), "-1.234,56")

    def test_sign_only_input_is_supported(self) -> None:
        self.assertEqual(_euro_text_with_leading_sign("", "+"), "+")

    def test_validation_fallback_handles_plus_typed_at_end(self) -> None:
        var = _FakeVar("-1.234,56")
        entry = _FakeEntry(var.get())
        bind_euro_amount_entry_validation(entry, var, require_leading_sign=True)
        callback = entry.validatecommand[0]

        accepted = callback("1", "-1.234,56+", "+", "9", "-1.234,56")

        self.assertFalse(accepted)
        self.assertEqual(var.get(), "+1.234,56")
        self.assertEqual(entry.value, "+1.234,56")
        self.assertEqual(entry.cursor, len(entry.value))


if __name__ == "__main__":
    unittest.main()
