#!/usr/bin/env python3
"""
Scompone il saldo assoluto in app (stessi passi di ``hybrid_absolute_balances_for_saldi``) per ogni
colonna conto dell’ultimo anno: *sld* legacy, registrazioni app, annulli import, correzioni su righe .dat
modificate, eventuale sostituzione «twin import».

Serve a verificare dove nasce uno scarto rispetto all’estratto **senza** rifare subito l’import legacy.

Uso (cartella dati da data_workspace.json, come l’altra utility):
  python3 scripts/print_hybrid_saldi_breakdown.py

Percorsi espliciti:
  python3 scripts/print_hybrid_saldi_breakdown.py --enc /percorso/conti_utente_X.enc --key /percorso/conti_di_casa.key
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402
from main_app import (  # noqa: E402
    compute_balances_from_2022_asof,
    compute_cancelled_imported_records_balance_adjustment,
    compute_imported_active_records_edit_balance_adjustment,
    compute_new_records_effect,
    format_euro_it,
    hybrid_absolute_balances_for_saldi,
    import_cancel_twin_balance_keys,
    latest_year_bucket,
    legacy_absolute_account_amounts,
    load_encrypted_db,
    _indices_touched_by_import_twin_actives,
)


def _resolve_db_enc_key(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None]:
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Scomposizione saldi assoluti (debug)")
    ap.add_argument("--enc", help="File .enc (default: più recente nella cartella dati)")
    ap.add_argument("--key", help="File chiave .key")
    args = ap.parse_args()

    enc_p, key_p = _resolve_db_enc_key(args)
    if enc_p is None or key_p is None:
        print(
            "Specificare --enc e --key oppure configurare la cartella dati (data_workspace).",
            file=sys.stderr,
        )
        return 2
    if not key_p.is_file():
        print(f"Chiave mancante: {key_p}", file=sys.stderr)
        return 3

    db = load_encrypted_db(enc_p, key_p)
    if not db:
        print("Decifratura fallita.", file=sys.stderr)
        return 4

    yb = latest_year_bucket(db)
    if not yb:
        print("Nessun anno nel DB.", file=sys.stderr)
        return 5
    accounts = yb.get("accounts") or []
    n = len(accounts)
    if n == 0:
        print("Piano conti vuoto.", file=sys.stderr)
        return 6

    today = date.today().isoformat()[:10]
    la = legacy_absolute_account_amounts(db, n)
    new_fx = compute_new_records_effect(db)
    canc = compute_cancelled_imported_records_balance_adjustment(db, cutoff_date_iso=today)
    edit_adj = compute_imported_active_records_edit_balance_adjustment(db)

    tk = import_cancel_twin_balance_keys(db)
    aff: set[int] = set()
    replay_excl: list[Decimal] | None = None
    if tk:
        aff = _indices_touched_by_import_twin_actives(db, tk)
        _, _, replay_excl = compute_balances_from_2022_asof(
            db, cutoff_date_iso="9999-12-31", exclude_import_twin_actives=True
        )

    final_h = hybrid_absolute_balances_for_saldi(db, today_cancel_cutoff_iso=today)
    if final_h is None or len(final_h) != n:
        print("hybrid_absolute_balances_for_saldi inatteso.", file=sys.stderr)
        return 7

    print(f"File: {enc_p}")
    print(f"Data riferimento (cutoff annulli, solo per colonne legacy sotto): {today}")
    print(
        "Saldo «finale» in app = solo replay movimenti (cutoff 9999-12-31) + correzione twin; "
        "non usa più *sld*+patch. Le colonne legacy/+app/+annulli/+edit servono al confronto col file import."
    )
    print(f"Twin import: {len(tk)} chiavi; colonne sostituite da replay escludendo gemello: {sorted(aff)}")
    print()

    w_code = max(4, max((len(str(a.get("code", ""))) for a in accounts), default=4))
    w_name = max(8, min(28, max((len(str(a.get("name", ""))) for a in accounts), default=16)))

    if la is None:
        print("*sld* legacy assente: il saldo finale usa solo il replay movimenti (fallback).")
        print()
    hdr = (
        f"{'cod':>{w_code}}  {'nome':<{w_name}}  {'legacy':>14}  {'+app':>14}  {'+annulli':>14}  "
        f"{'+edit.dat':>14}  {'=pre':>14}  {'finale':>14}  note"
    )
    print(hdr)
    print("-" * len(hdr))

    for i in range(n):
        ac = accounts[i]
        code = str(ac.get("code", "") or "").strip() or "—"
        name = (str(ac.get("name", "") or "").strip())[:w_name]
        if la is None:
            leg_s = "—"
            pre = final_h[i]
        else:
            a0 = la[i] if i < len(la) else Decimal("0")
            a1 = new_fx[i] if i < len(new_fx) else Decimal("0")
            a2 = canc[i] if i < len(canc) else Decimal("0")
            a3 = edit_adj[i] if i < len(edit_adj) else Decimal("0")
            pre = a0 + a1 + a2 + a3
            leg_s = format_euro_it(a0)
            app_s = format_euro_it(a1)
            can_s = format_euro_it(a2)
            ed_s = format_euro_it(a3)
            pre_s = format_euro_it(pre)

            note = ""
            if i in aff and replay_excl is not None and i < len(replay_excl):
                note = "replay twin"
            elif not tk or i not in aff:
                note = ""

            fin = final_h[i]
            ok = fin == (replay_excl[i] if (i in aff and replay_excl is not None and i < len(replay_excl)) else pre)
            if not ok and la is not None:
                note = f"{note + ' (!)' if note else 'scarto (!)'}"
            print(
                f"{code:>{w_code}}  {name:<{w_name}}  {leg_s:>14}  {app_s:>14}  {can_s:>14}  "
                f"{ed_s:>14}  {pre_s:>14}  {format_euro_it(fin):>14}  {note}"
            )
            continue

        fin = final_h[i]
        print(f"{code:>{w_code}}  {name:<{w_name}}  {leg_s:>14}  {'—':>14}  {'—':>14}  {'—':>14}  {'—':>14}  {format_euro_it(fin):>14}  replay")

    print()
    print(
        "Legenda: legacy = saldo *sld* per codice; +app = sole righe create in app; "
        "+annulli = compensazione righe import annullate; +edit.dat = differenza righe import modificate vs .dat; "
        "pre = somma prima del twin; «replay twin» = colonna rimpiazzata dal replay senza gemello attivo."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
