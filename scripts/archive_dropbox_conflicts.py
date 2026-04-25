#!/usr/bin/env python3
"""Archivia in modo reversibile le conflicted copies Dropbox dei file .enc.

Lo script NON cancella i file: li sposta in una sottocartella `conflicted_archive/<timestamp>/`
e scrive un manifest JSON con origine/destinazione.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace


def _is_conflicted(path: Path) -> bool:
    name = path.name.lower()
    return "conflicted copy" in name or "copia in conflitto" in name


def main() -> int:
    ap = argparse.ArgumentParser(description="Archivia conflicted copies Dropbox (.enc), senza cancellarle")
    ap.add_argument("--workspace", help="Cartella dati; default: data_workspace.json")
    ap.add_argument("--yes", action="store_true", help="Esegui davvero lo spostamento")
    args = ap.parse_args()

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else data_workspace.load_saved_workspace_path()
    if workspace is None or not workspace.is_dir():
        print("Cartella dati non trovata.", file=sys.stderr)
        return 2

    conflicts = sorted(
        (p for p in workspace.glob("*.enc") if p.is_file() and _is_conflicted(p)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not conflicts:
        print(f"Nessuna conflicted copy .enc trovata in {workspace}")
        return 0

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = workspace / "conflicted_archive" / ts
    print(f"Cartella dati: {workspace}")
    print(f"Conflicted copies da archiviare: {len(conflicts)}")
    print(f"Archivio: {archive_dir}")
    if not args.yes:
        print("\nDry-run: nessun file spostato. Rilancia con --yes per eseguire.")
        for p in conflicts:
            print(f"- {p.name}")
        return 0

    archive_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "workspace": str(workspace),
        "archive_dir": str(archive_dir),
        "files": [],
    }
    for p in conflicts:
        dest = archive_dir / p.name
        shutil.move(str(p), str(dest))
        manifest["files"].append({"from": str(p), "to": str(dest), "size": dest.stat().st_size})
        print(f"archiviato: {p.name}")

    (archive_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nCompletato. Nessun file e' stato cancellato.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
