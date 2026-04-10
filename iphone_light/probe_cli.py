#!/usr/bin/env python3
"""
CLI di prova (macOS/Linux): verifica caricamento DB + login light senza Tk/Pillow.
Non è l'app iPhone; serve a validare percorsi Dropbox e credenziali.

Esempio dalla root del repo (usa i path reali del tuo `.enc` completo e della `.key`):
  python3 -m iphone_light.probe_cli --enc data/conti_utente_<hash>.enc --key data/conti_di_casa.key
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

# Repo root sul sys.path quando si esegue come -m iphone_light.probe_cli
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from iphone_light.crypto_db import save_encrypted_db_single  # noqa: E402
from iphone_light.light_auth import load_db_for_email, try_login  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Probe login light (Conti di casa)")
    p.add_argument("--enc", type=Path, required=True, help="File .enc principale o per-utente")
    p.add_argument("--key", type=Path, required=True, help="File chiave Fernet")
    p.add_argument("--dry-save", action="store_true", help="Dopo login, prova salvataggio senza backup")
    args = p.parse_args()
    enc = args.enc.resolve()
    key = args.key.resolve()
    if not enc.is_file():
        print(f"File .enc non trovato: {enc}", file=sys.stderr)
        return 1
    if not key.is_file():
        print(f"File chiave non trovato: {key}", file=sys.stderr)
        return 1

    email = input("Email (come sul desktop): ").strip()
    if not email:
        print("Email obbligatoria.", file=sys.stderr)
        return 1
    db, enc_used = load_db_for_email(enc, key, email)
    if db is None:
        print("Impossibile decifrare il database (chiave errata o file corrotto).", file=sys.stderr)
        return 1
    pw = getpass.getpass("Password: ")
    sess = try_login(db, email, pw)
    if sess is None:
        print("Accesso negato.", file=sys.stderr)
        return 1
    nrec = 0
    try:
        for y in db.get("years") or []:
            nrec += len(y.get("records") or [])
    except Exception:
        pass
    print(f"OK — registrato={sess.is_registered} — registrazioni indicativi: ~{nrec}")
    if args.dry_save:
        save_encrypted_db_single(db, enc_used, key)
        print(f"Salvato (solo questo file, nessun backup): {enc_used}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
