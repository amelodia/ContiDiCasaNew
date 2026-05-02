#!/usr/bin/env python3
"""
Incrementa solo il saldo «di base» *sld* legacy per **un** conto, senza aggiungere registrazioni.

Il footer «Saldi assoluti» usa ``hybrid_absolute_balances_for_saldi``: parte da ``legacy_saldi.amounts``
(per codice conto), poi applica movimenti app / correzioni import. Questo script modifica solo la voce
``legacy_saldi.amounts[j]`` del bucket anno di riferimento dove ``accounts[j].code`` coincide col codice
richiesto (es. AMEX = 9).

Chiudere l'app desktop prima di salvare.

Senza ``--enc``, viene usato il database **completo** (``conti_utente_*.enc``), mai il sidecar ``*_light.enc``.

Esempi:
  python3 scripts/bump_legacy_saldo_one_account.py --dry-run --year 2026 --account-code 9 --delta 7730.16
  python3 scripts/bump_legacy_saldo_one_account.py --year 2026 --account-code 9 --delta 7730.16 \\
      --enc /percorso/conti_utente_....enc --key /percorso/conti_di_casa.key
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402
from light_enc_sidecar import write_light_enc_sidecar  # noqa: E402
from iphone_light.crypto_db import load_encrypted_db, save_encrypted_db_single  # noqa: E402
from main_app import (  # noqa: E402
    _canonical_legacy_saldo_code_key,
    account_balance_for_code_latest_chart,
    hybrid_absolute_balances_for_saldi,
    latest_year_bucket,
    year_bucket_for_calendar_year,
)


def _resolve_enc_key(args: argparse.Namespace) -> tuple[Path | None, Path | None]:
    if args.enc and args.key:
        return Path(args.enc).expanduser().resolve(), Path(args.key).expanduser().resolve()
    saved = data_workspace.load_saved_workspace_path()
    if saved is None:
        return None, None
    data_workspace.set_data_workspace_root(saved)
    key_path = data_workspace.default_key_file()
    cands = data_workspace.primary_user_enc_files_sorted(saved)
    if not cands:
        return None, None
    return cands[0], key_path


def _find_legacy_amount_index(y_ref: dict, account_code: str) -> int | None:
    want = _canonical_legacy_saldo_code_key(account_code)
    if not want:
        return None
    for j, a in enumerate(y_ref.get("accounts") or []):
        ck = _canonical_legacy_saldo_code_key(str(a.get("code", "")))
        if ck == want:
            return j
    return None


def _amount_to_dec(s: object) -> Decimal:
    try:
        return Decimal(str(s).strip())
    except InvalidOperation:
        return Decimal("0")


def _fmt_legacy_amount(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".") or "0"


def main() -> int:
    ap = argparse.ArgumentParser(description="Corregge una sola colonna del saldo legacy (*sld*)")
    ap.add_argument("--year", type=int, default=2026, help="Anno del bucket con legacy_saldi (default 2026)")
    ap.add_argument(
        "--account-code",
        required=True,
        help="Codice conto numerico (es. 9 per AMEX)",
    )
    ap.add_argument(
        "--delta",
        required=True,
        help="Importo da sommare al saldo legacy di quel conto (es. 7730.16)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Mostra solo PRIMA/DOPO senza salvare")
    ap.add_argument("--enc", help="File .enc")
    ap.add_argument("--key", help="File chiave .key")
    args = ap.parse_args()

    try:
        delta = Decimal(str(args.delta).replace(",", ".").strip())
    except InvalidOperation:
        print("Delta non numerico.", file=sys.stderr)
        return 2

    enc_p, key_p = _resolve_enc_key(args)
    if enc_p is None or key_p is None:
        print("Specificare --enc e --key oppure la cartella dati in data_workspace.", file=sys.stderr)
        return 3
    if not enc_p.is_file() or not key_p.is_file():
        print("File .enc o .key non trovato.", file=sys.stderr)
        return 4

    db = load_encrypted_db(enc_p, key_p)
    if not db:
        print("Decifratura fallita.", file=sys.stderr)
        return 5

    y_ref = year_bucket_for_calendar_year(db, int(args.year))
    if not y_ref:
        print(f"Anno {args.year} assente nel DB.", file=sys.stderr)
        return 6

    ls = y_ref.get("legacy_saldi")
    if not isinstance(ls, dict):
        print("Nessun blocco legacy_saldi in quell'anno: impossibile correggere la base *sld*.", file=sys.stderr)
        return 7

    raw = ls.get("amounts")
    if not isinstance(raw, list) or not raw:
        print("legacy_saldi.amounts assente o vuoto.", file=sys.stderr)
        return 8

    acc_code = str(args.account_code).strip()
    j = _find_legacy_amount_index(y_ref, acc_code)
    if j is None:
        print(f"Conto con codice «{acc_code}» non trovato nel piano conti {args.year}.", file=sys.stderr)
        return 9

    # All'import *sld* il vettore può essere più corto del piano conti: le colonne mancanti valgono 0
    # (vedi ``legacy_absolute_account_amounts`` in main_app). Estendiamo con zeri fino all'indice richiesto.
    while len(raw) <= j:
        raw.append("0")

    name = ""
    try:
        name = str((y_ref.get("accounts") or [])[j].get("name") or "").strip()
    except Exception:
        pass

    old_s = raw[j]
    old_dec = _amount_to_dec(old_s)
    new_dec = old_dec + delta

    today = date.today().isoformat()[:10]
    saldo_prima = account_balance_for_code_latest_chart(db, acc_code)
    saldo_h_prima = hybrid_absolute_balances_for_saldi(db, today_cancel_cutoff_iso=today)

    print(f"Conto: codice {acc_code}" + (f" ({name})" if name else ""))
    print(f"Indice legacy_saldi.amounts: {j}")
    print(f"legacy importo PRIMA: {old_s!r}  (→ {_amount_to_dec(old_s)})")
    print(f"Delta: {delta}")
    print(f"legacy importo DOPO: {_fmt_legacy_amount(new_dec)!r}")

    if saldo_prima is not None:
        print(f"Saldo assoluto (footer) prima — colonna questo conto: {saldo_prima}")
    idx_hint: int | None = None
    y_latest = latest_year_bucket(db)
    if y_latest:
        for i2, a2 in enumerate((y_latest or {}).get("accounts") or []):
            if _canonical_legacy_saldo_code_key(str(a2.get("code", ""))) == _canonical_legacy_saldo_code_key(
                acc_code
            ):
                idx_hint = i2
                break
        if idx_hint is not None and saldo_h_prima and idx_hint < len(saldo_h_prima):
            print(f"Vettore hybrid (stesso ordine footer) prima — indice {idx_hint}: {saldo_h_prima[idx_hint]}")

    if args.dry_run:
        if saldo_prima is not None:
            print(f"[dry-run] Saldo assoluto atteso dopo: {saldo_prima + delta} (solo se gli altri addendi restano uguali)")
        print("Nessuna modifica salvata.")
        return 0

    raw[j] = _fmt_legacy_amount(new_dec)

    save_encrypted_db_single(db, enc_p, key_p)
    try:
        write_light_enc_sidecar(db, enc_p, key_p)
    except Exception:
        pass

    db2 = load_encrypted_db(enc_p, key_p)
    if db2:
        saldo_dopo = account_balance_for_code_latest_chart(db2, acc_code)
        print(f"Saldo assoluto (footer) dopo — questo conto: {saldo_dopo}")
        print(f"Salvato: {enc_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
