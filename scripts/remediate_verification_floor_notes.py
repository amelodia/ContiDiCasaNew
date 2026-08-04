#!/usr/bin/env python3
"""
Istruzioni (e dry-run) per arretrare il confine ** dopo buchi non verificati.

I dati BCC.ROMA diagnosticati (2026-08-04):
  - Floor ** su reg_n=29395 (2026-07-31, «Per 5008 07»)
  - Buchi sotto floor: 29221 (Inps ML 2026/07, unmarked) e 29384 (Inps ML 2026/08, unmarked)
  - reg_n=23984 NON è BCC.ROMA: è CORR.ING (codice 8) già con *

Remediation UI (consigliata, senza script che riscrive il .enc):
  1. Movimenti → apri la registrazione 29395 (BCC.ROMA, **).
  2. «Forza verifica» / cancellazione verifica sul conto BCC.ROMA
     (il confine ** arretra sulla registrazione precedente verificata dello stesso conto).
  3. Scheda Verifica → BCC.ROMA → riesegui abbinamento per 29221 e 29384
     (e ogni altra non verificata rientrata in fascio).
  4. Chiudi il ciclo di verifica così il nuovo ** resta solo dopo una catena senza buchi.

Uso dry-run:
  python3 scripts/remediate_verification_floor_notes.py --account-name BCC.ROMA
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402

from main_app import (  # noqa: E402
    account_codes_match_for_verification,
    load_encrypted_db,
    record_legacy_stable_key,
    record_merge_sort_key,
    show_record_in_movements_grid,
    unified_registration_sequence_map,
    verification_flag_star_equivalent_count,
)


def _resolve_db(enc: str | None, key: str | None):
    if enc and key:
        enc_p = Path(enc).expanduser().resolve()
        key_p = Path(key).expanduser().resolve()
    else:
        saved = data_workspace.load_saved_workspace_path()
        if saved is None:
            raise SystemExit("Nessuna cartella dati in data_workspace.json")
        data_workspace.set_data_workspace_root(saved)
        key_p = data_workspace.default_key_file()
        cands = data_workspace.primary_user_enc_files_sorted(saved)
        if not cands:
            raise SystemExit(f"Nessun .enc in {saved}")
        enc_p = cands[0]
    db = load_encrypted_db(enc_p, key_p)
    if not db:
        raise SystemExit(f"Decifratura fallita: {enc_p}")
    return db, enc_p


def _account_code_by_name(db: dict, name: str) -> str | None:
    needle = " ".join((name or "").split()).casefold()
    for yd in reversed(list(db.get("years") or [])):
        for a in yd.get("accounts") or []:
            if not isinstance(a, dict):
                continue
            nm = " ".join(str(a.get("name") or "").split()).casefold()
            if nm == needle:
                return str(a.get("code") or "").strip() or None
    return None


def _touches(rec: dict, acc_code: str) -> tuple[bool, str]:
    ac = str(acc_code or "").strip()
    c1 = str(rec.get("account_primary_code", "")).strip()
    c2 = str(rec.get("account_secondary_code", "")).strip()
    if c1 and account_codes_match_for_verification(c1, ac):
        return True, "primary"
    if c2 and account_codes_match_for_verification(c2, ac):
        return True, "secondary"
    return False, ""


def _stars(rec: dict, side: str) -> int:
    fk = "account_primary_flags" if side == "primary" else "account_secondary_flags"
    return verification_flag_star_equivalent_count(str(rec.get(fk) or ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="Stampa remediation floor ** (sola lettura)")
    ap.add_argument("--enc", default=None)
    ap.add_argument("--key", default=None)
    ap.add_argument("--account-name", default="BCC.ROMA")
    ap.add_argument("--account-code", default=None)
    args = ap.parse_args()

    print(__doc__)
    db, enc_p = _resolve_db(args.enc, args.key)
    acc = (args.account_code or "").strip() or (_account_code_by_name(db, args.account_name) or "")
    if not acc:
        raise SystemExit("conto non trovato")
    print(f"DB={enc_p}\nconto={args.account_name!r} code={acc}\n")

    recs: list[dict] = []
    for yd in db.get("years") or []:
        recs.extend(list(yd.get("records") or []))
    recs.sort(key=record_merge_sort_key)
    rmap = unified_registration_sequence_map(recs)
    ordered = sorted([(rmap[record_legacy_stable_key(r)], r) for r in recs], key=lambda x: x[0])

    floor = None
    for reg_n, rec in reversed(ordered):
        if rec.get("is_cancelled"):
            continue
        t, side = _touches(rec, acc)
        if t and _stars(rec, side) >= 2:
            floor = (reg_n, rec)
            break
    if not floor:
        print("Nessun ** sul conto: nessuna remediation floor necessaria.")
        return 0
    fr, frec = floor
    print(f"Floor attuale: reg_n={fr} date={frec.get('date_iso')} note={(frec.get('note') or '')[:60]!r}")
    print("Buchi Movimenti-visibili unmarked sotto floor:")
    n = 0
    for reg_n, rec in ordered:
        if reg_n >= fr:
            break
        if rec.get("is_cancelled"):
            continue
        t, side = _touches(rec, acc)
        if not t or _stars(rec, side) >= 1:
            continue
        if not show_record_in_movements_grid(rec):
            continue
        n += 1
        print(f"  - reg_n={reg_n} date={rec.get('date_iso')} amt={rec.get('amount_eur')} note={(rec.get('note') or '')[:50]!r}")
    print(f"Totale buchi={n}")
    print("\nAzione: Forza verifica su reg_n=%s, poi verificare i buchi in sessione Verifica." % fr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
