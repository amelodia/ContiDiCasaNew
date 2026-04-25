"""
Lettura/scrittura del database cifrato (Fernet), allineata a main_app.py.
Nessun backup secondario: un solo file di uscita (adatto a scenario iPhone / Dropbox).
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None
    InvalidToken = Exception


def per_user_encrypted_db_path(email: str) -> Path:
    """Stesso schema di main_app.per_user_encrypted_db_path."""
    h = hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:20]
    return Path("data") / f"conti_utente_{h}.enc"


def load_encrypted_db(output_path: Path, key_path: Path) -> dict | None:
    if Fernet is None:
        raise RuntimeError("Installa cryptography: pip install cryptography")
    if not output_path.exists() or not key_path.exists():
        return None
    key = key_path.read_bytes()
    token = output_path.read_bytes()
    try:
        raw = Fernet(key).decrypt(token)
    except InvalidToken:
        return None
    return json.loads(raw.decode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _has_dropbox_conflicted_enc(data_dir: Path) -> bool:
    for p in data_dir.glob("*.enc"):
        name = p.name.lower()
        if p.is_file() and ("conflicted copy" in name or "copia in conflitto" in name):
            return True
    return False


def save_encrypted_db_single(db: dict, output_path: Path, key_path: Path) -> None:
    """Salva solo su ``output_path`` (nessuna copia di backup locale)."""
    if Fernet is None:
        raise RuntimeError("Installa cryptography: pip install cryptography")
    if not key_path.exists():
        raise FileNotFoundError(f"File chiave mancante: {key_path}")
    if _has_dropbox_conflicted_enc(output_path.parent):
        raise RuntimeError("Salvataggio bloccato: ci sono copie Dropbox in conflitto nella cartella dati.")
    key = key_path.read_bytes()
    token = Fernet(key).encrypt(json.dumps(db, ensure_ascii=True, indent=2).encode("utf-8"))
    _atomic_write_bytes(output_path, token)


def resolve_per_user_enc_path_if_present(db: dict, *, primary_enc_path: Path) -> Path | None:
    """
    Stesso schema del desktop: il file dedicato all'utente è ``conti_utente_<hash>.enc`` nella **stessa cartella**
    del file .enc principale indicato (stesso nome file che usa ``per_user_encrypted_db_path``).
    """
    from security_auth import ensure_security

    ensure_security(db)
    up = db.get("user_profile") or {}
    em = (up.get("email") or "").strip().lower()
    ph = (up.get("password_hash") or "").strip()
    if not em or not ph:
        return None
    h = hashlib.sha256(em.encode("utf-8")).hexdigest()[:20]
    candidate = primary_enc_path.parent / f"conti_utente_{h}.enc"
    if candidate.is_file():
        return candidate
    return None
