#!/usr/bin/env python3
"""Inventario sicuro dei file cifrati Conti di casa e delle conflicted copies Dropbox.

Lo script e' volutamente read-only: non cancella, non sposta e non riscrive file.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"cryptography non disponibile: {exc}") from exc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace


def _is_conflicted(path: Path) -> bool:
    name = path.name.lower()
    return "conflicted copy" in name or "copia in conflitto" in name


def _is_light(path: Path) -> bool:
    stem = path.stem.lower()
    return stem.endswith("_light") or "_light " in stem or "_light_" in stem


def _records_info(db: dict[str, Any]) -> tuple[int, str, int, int]:
    years = db.get("years") if isinstance(db, dict) else []
    if not isinstance(years, list):
        return 0, "", 0, 0
    n_records = 0
    latest_date = ""
    active = 0
    cancelled = 0
    for yb in years:
        if not isinstance(yb, dict):
            continue
        records = yb.get("records") or []
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            n_records += 1
            if rec.get("is_cancelled"):
                cancelled += 1
            else:
                active += 1
            d = str(rec.get("date_iso") or "")[:10]
            if d and d > latest_date:
                latest_date = d
    return n_records, latest_date, active, cancelled


def _light_new_ids(db: dict[str, Any]) -> int:
    years = db.get("years") if isinstance(db, dict) else []
    if not isinstance(years, list):
        return 0
    out = 0
    for yb in years:
        if not isinstance(yb, dict):
            continue
        for rec in yb.get("records") or []:
            if isinstance(rec, dict) and str(rec.get("conti_light_record_id") or "").strip():
                out += 1
    return out


def _summarize_file(path: Path, fernet: Fernet) -> dict[str, Any]:
    st = path.stat()
    info: dict[str, Any] = {
        "file": path.name,
        "path": str(path),
        "kind": "light" if _is_light(path) else "full",
        "conflicted": _is_conflicted(path),
        "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        "mtime_ts": st.st_mtime,
        "size": st.st_size,
        "decrypt_ok": False,
        "records": None,
        "active_records": None,
        "cancelled_records": None,
        "latest_record_date": "",
        "years": "",
        "light_record_ids": None,
        "error": "",
    }
    try:
        raw = fernet.decrypt(path.read_bytes())
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("JSON decifrato non e' un oggetto")
        n, latest, active, cancelled = _records_info(obj)
        years = obj.get("years") or []
        ylist = []
        if isinstance(years, list):
            for yb in years:
                if isinstance(yb, dict) and yb.get("year") is not None:
                    ylist.append(str(yb.get("year")))
        info.update(
            decrypt_ok=True,
            records=n,
            active_records=active,
            cancelled_records=cancelled,
            latest_record_date=latest,
            years=",".join(ylist),
            light_record_ids=_light_new_ids(obj),
        )
    except Exception as exc:
        info["error"] = repr(exc)
    return info


def _score(info: dict[str, Any]) -> tuple[int, str, float, int]:
    # Ordine conservativo: decifrabile, ultima data registrazione, mtime, numero record.
    return (
        1 if info.get("decrypt_ok") else 0,
        str(info.get("latest_record_date") or ""),
        float(info.get("mtime_ts") or 0.0),
        int(info.get("records") or 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventario read-only delle conflicted copies Dropbox")
    ap.add_argument("--workspace", help="Cartella dati; default: data_workspace.json")
    ap.add_argument("--json", action="store_true", help="Stampa JSON invece del report testuale")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else data_workspace.load_saved_workspace_path()
    if workspace is None or not workspace.is_dir():
        print("Cartella dati non trovata.", file=sys.stderr)
        return 2
    key_path = workspace / "conti_di_casa.key"
    if not key_path.is_file():
        print(f"Chiave mancante: {key_path}", file=sys.stderr)
        return 3
    fernet = Fernet(key_path.read_bytes())
    files = sorted(workspace.glob("*.enc"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = [_summarize_file(p, fernet) for p in files]
    full = [r for r in rows if r["kind"] == "full"]
    light = [r for r in rows if r["kind"] == "light"]
    best_full = max(full, key=_score) if full else None
    best_light = max(light, key=_score) if light else None

    payload = {
        "workspace": str(workspace),
        "key": str(key_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "counts": {
            "enc_files": len(rows),
            "conflicted": sum(1 for r in rows if r["conflicted"]),
            "full": len(full),
            "light": len(light),
        },
        "best_full_candidate": best_full,
        "best_light_candidate": best_light,
        "files": rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"Cartella dati: {workspace}")
    print(f"File .enc: {len(rows)}  conflicted: {payload['counts']['conflicted']}  full: {len(full)}  light: {len(light)}")
    print()
    for title, row in (("Miglior candidato FULL", best_full), ("Miglior candidato LIGHT", best_light)):
        print(f"{title}:")
        if row is None:
            print("  (nessuno)")
        else:
            print(
                "  {file}\n"
                "  mtime={mtime} size={size} decrypt={decrypt_ok} records={records} "
                "active={active_records} latest={latest_record_date} conflicted={conflicted}".format(**row)
            )
        print()
    print("Dettaglio (piu' recenti prima):")
    for r in rows:
        marker = "CONFLICT" if r["conflicted"] else "official"
        print(
            f"- [{marker:8}] [{r['kind']:5}] {r['mtime']} size={r['size']} "
            f"dec={r['decrypt_ok']} rec={r['records']} active={r['active_records']} "
            f"latest={r['latest_record_date']} light_ids={r['light_record_ids']} :: {r['file']}"
        )
        if r["error"]:
            print(f"    errore: {r['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
