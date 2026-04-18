#!/usr/bin/env python3
"""
Stampa il saldo assoluto (e altre righe footer) per un conto del piano ultimo anno,
usando gli stessi calcoli di main_app.saldi_footer_amount_vectors.

Uso:
  python3 scripts/check_saldo_assoluto_account.py "CC.PP.TT"
  python3 scripts/check_saldo_assoluto_account.py "CC.PP.TT" 3250,33   # verifica uguaglianza (exit 0/1)
"""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402
from main_app import load_encrypted_db, saldi_footer_amount_vectors  # noqa: E402


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def main() -> int:
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not needle:
        print("Uso: python3 scripts/check_saldo_assoluto_account.py <nome_o_codice_conto> [importo_atteso]", file=sys.stderr)
        return 2

    expected: Decimal | None = None
    if len(sys.argv) > 2:
        raw = sys.argv[2].strip().replace(".", "").replace(",", ".")
        try:
            expected = Decimal(raw).quantize(Decimal("0.01"))
        except Exception:
            print("Importo atteso non valido.", file=sys.stderr)
            return 2

    saved = data_workspace.load_saved_workspace_path()
    if saved is None:
        print("Nessuna cartella dati in ~/Library/Application Support/ContiDiCasa/data_workspace.json", file=sys.stderr)
        return 3
    data_workspace.set_data_workspace_root(saved)

    key_path = data_workspace.default_key_file()
    if not key_path.is_file():
        print(f"Manca la chiave: {key_path}", file=sys.stderr)
        return 4

    cands = sorted(
        (p for p in saved.glob("conti_utente_*.enc") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not cands:
        print(f"Nessun conti_utente_*.enc in {saved}", file=sys.stderr)
        return 5

    db = load_encrypted_db(cands[0], key_path)
    if not db:
        print("Decifratura fallita (chiave o file .enc).", file=sys.stderr)
        return 6

    v = saldi_footer_amount_vectors(db, today_iso=None)
    if not v:
        print("saldi_footer_amount_vectors ha restituito None.", file=sys.stderr)
        return 7

    names = list(v["names"])
    codes = list(v["account_codes"])
    absv = list(v["saldo_assoluti"])
    nneedle = _norm(needle)

    idx = None
    for i, nm in enumerate(names):
        if _norm(nm) == nneedle or str(codes[i]).strip() == needle:
            idx = i
            break
    if idx is None:
        for i, nm in enumerate(names):
            if nneedle in _norm(nm):
                idx = i
                break

    if idx is None:
        print("Conto non trovato. Nomi nel footer:", file=sys.stderr)
        for i, nm in enumerate(names):
            print(f"  [{codes[i]}] {nm!r}", file=sys.stderr)
        return 8

    a = absv[idx]
    print(f"Conto: {names[idx]!r} (codice colonna: {codes[idx]})")
    print(f"  saldo_assoluto: {a}")
    print(f"  saldo_oggi:     {v['saldo_oggi'][idx]}")
    print(f"  spese_future:   {v['spese_future'][idx]}")
    print(f"  spese_cc:       {v['spese_cc'][idx]}")
    print(f"  disponibilita: {v['disponibilita'][idx]}")
    print(f"  credit_card:    {v['is_credit_card'][idx]}")

    if expected is not None:
        ok = a.quantize(Decimal("0.01")) == expected
        print(f"\nUguale a {expected}? {'SÌ' if ok else 'NO'}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
