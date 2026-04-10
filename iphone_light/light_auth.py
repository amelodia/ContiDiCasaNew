"""
Login «light»: solo email + password contro il profilo nel DB già creato sul desktop.
Niente ospite, niente backdoor, niente wizard primo accesso (presupposto fatto su desktop).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from security_auth import AppSession, ensure_security, verify_password

from .crypto_db import load_encrypted_db


def per_user_enc_path_for_email(email: str, *, primary_enc_path: Path) -> Path:
    em = email.strip().lower()
    h = hashlib.sha256(em.encode("utf-8")).hexdigest()[:20]
    return primary_enc_path.parent / f"conti_utente_{h}.enc"


def load_db_for_email(enc_path: Path, key_path: Path, email: str) -> tuple[dict | None, Path]:
    """
    Carica il database operativo: se esiste il file per-utente per quell'email nella stessa
    cartella del .enc principale, usa quello (come ``load_database_at_startup`` sul desktop).
    Ritorna ``(db, path_effettivo)`` per salvataggi senza backup sul file giusto.
    """
    base = load_encrypted_db(enc_path, key_path)
    if base is None:
        return None, enc_path
    pu = per_user_enc_path_for_email(email, primary_enc_path=enc_path)
    if pu.is_file() and pu.resolve() != enc_path.resolve():
        db2 = load_encrypted_db(pu, key_path)
        if db2 is not None:
            return db2, pu
    return base, enc_path


def try_login(db: dict, email: str, password: str) -> AppSession | None:
    """Ritorna sessione «registrata» se credenziali valide; altrimenti None."""
    ensure_security(db)
    up = db.get("user_profile") or {}
    em = (email or "").strip().lower()
    if not em or not (up.get("password_hash") or "").strip():
        return None
    if em != (up.get("email") or "").strip().lower():
        return None
    if not verify_password(up, password):
        return None
    verified = bool(up.get("registration_verified"))
    return AppSession(
        is_registered=verified,
        entered_via_backdoor=False,
        user_email=em,
    )
