"""Pacchetto «light» per client iOS (specifica + utilità) senza dipendere dall'UI desktop."""

from .crypto_db import (
    load_encrypted_db,
    per_user_encrypted_db_path,
    resolve_per_user_enc_path_if_present,
    save_encrypted_db_single,
)
from .light_auth import load_db_for_email, try_login

__all__ = [
    "load_encrypted_db",
    "load_db_for_email",
    "per_user_encrypted_db_path",
    "resolve_per_user_enc_path_if_present",
    "save_encrypted_db_single",
    "try_login",
]
