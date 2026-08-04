#!/usr/bin/env python3
"""
Ispeziona registrazioni per diagnosi verifica (flag * / **, floor, date).

Uso:
  python3 scripts/inspect_verification_regs.py --account-name BCC.ROMA --reg-n 23984 29221 29395
  python3 scripts/inspect_verification_regs.py --account-code 6 --reg-n 29395
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


def _resolve_db(enc: str | None, key: str | None) -> tuple[dict, Path]:
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
    ap = argparse.ArgumentParser(description="Ispeziona flag verifica su reg_n / conto")
    ap.add_argument("--enc", default=None)
    ap.add_argument("--key", default=None)
    ap.add_argument("--account-name", default="BCC.ROMA")
    ap.add_argument("--account-code", default=None)
    ap.add_argument("--reg-n", nargs="+", type=int, required=True)
    args = ap.parse_args()

    db, enc_p = _resolve_db(args.enc, args.key)
    print(f"DB: {enc_p}")

    acc_code = (args.account_code or "").strip()
    if not acc_code:
        acc_code = _account_code_by_name(db, args.account_name) or ""
    if not acc_code:
        raise SystemExit(f"Conto non trovato: {args.account_name!r}")
    print(f"Conto: {args.account_name!r} code={acc_code}")

    all_records: list[dict] = []
    for yd in db.get("years") or []:
        all_records.extend(list(yd.get("records") or []))
    all_records.sort(key=record_merge_sort_key)
    reg_map = unified_registration_sequence_map(all_records)
    ordered = sorted(
        [(reg_map[record_legacy_stable_key(r)], r) for r in all_records],
        key=lambda x: x[0],
    )

    floor_reg = None
    floor_date = ""
    for reg_n, rec in reversed(ordered):
        if rec.get("is_cancelled"):
            continue
        touches, side = _touches(rec, acc_code)
        if not touches:
            continue
        if _stars(rec, side) >= 2:
            floor_reg = reg_n
            floor_date = str(rec.get("date_iso") or "")
            break
    print(f"Floor ** attuale: reg_n={floor_reg} date={floor_date}")

    want = set(args.reg_n)
    print("--- target rows ---")
    found: dict[int, dict] = {}
    for reg_n, rec in ordered:
        if reg_n not in want:
            continue
        touches, side = _touches(rec, acc_code)
        pf = str(rec.get("account_primary_flags") or "")
        sf = str(rec.get("account_secondary_flags") or "")
        found[reg_n] = rec
        print(
            f"reg_n={reg_n} date={rec.get('date_iso')} year={rec.get('year')} "
            f"amt={rec.get('amount_eur')} cancelled={bool(rec.get('is_cancelled'))} "
            f"in_movimenti={show_record_in_movements_grid(rec)}"
        )
        print(
            f"  primary={rec.get('account_primary_code')!r}/{pf!r} "
            f"secondary={rec.get('account_secondary_code')!r}/{sf!r} "
            f"with={rec.get('account_primary_with_flags')!r}/{rec.get('account_secondary_with_flags')!r}"
        )
        print(
            f"  touches={touches} side={side} stars={_stars(rec, side) if touches else '-'} "
            f"key={record_legacy_stable_key(rec)}"
        )
        note = str(rec.get("note") or "")[:80]
        print(f"  note={note!r}")
        if floor_reg is not None:
            under = reg_n < floor_reg
            print(f"  under_floor={under} (search_scope={'no' if under else 'maybe'})")

    missing = sorted(want - set(found))
    if missing:
        print(f"ATTENZIONE: reg_n non trovati: {missing}")

    # Gaps under floor on this account
    print("--- unmarked under floor (same account, Movimenti-visible) ---")
    gaps = []
    if floor_reg is not None:
        for reg_n, rec in ordered:
            if reg_n >= floor_reg:
                break
            if rec.get("is_cancelled"):
                continue
            touches, side = _touches(rec, acc_code)
            if not touches:
                continue
            if _stars(rec, side) >= 1:
                continue
            if not show_record_in_movements_grid(rec):
                continue
            gaps.append((reg_n, str(rec.get("date_iso") or ""), str(rec.get("amount_eur") or "")))
            print(f"  gap reg_n={reg_n} date={rec.get('date_iso')} amt={rec.get('amount_eur')}")
    print(f"gap_count={len(gaps)}")

    # Classify A/B/C for requested unmarked targets
    print("--- classification ---")
    for reg_n in sorted(want):
        rec = found.get(reg_n)
        if not rec:
            print(f"{reg_n}: NOT_FOUND")
            continue
        touches, side = _touches(rec, acc_code)
        stars = _stars(rec, side) if touches else 0
        if stars >= 2:
            print(f"{reg_n}: FLOOR_ROW (**)")
            continue
        if stars >= 1:
            print(f"{reg_n}: VERIFIED (*)")
            continue
        d = str(rec.get("date_iso") or "")
        if floor_reg is not None and reg_n < floor_reg:
            if floor_date and d and d > floor_date:
                # post-floor-date but under reg floor — classic supplement / jump candidate
                print(f"{reg_n}: CLASS_A_or_B under_floor unmarked date={d} (possible cutoff-skip or prior floor)")
            else:
                print(f"{reg_n}: CLASS_B under_floor unmarked date={d} (trapped by prior/current **)")
        else:
            print(f"{reg_n}: OPEN unmarked at/after floor (not trapped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
