"""Retention backup pre-salvataggio in Library (``pre_save_backups``)."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import main_app


def test_prune_old_presave_backups_keeps_recent_only(tmp_path: Path) -> None:
    bdir = tmp_path / "pre_save_backups"
    bdir.mkdir()
    recent = bdir / "conti_utente_x_20260101_120000.enc"
    old = bdir / "conti_utente_x_20251201_120000.enc"
    recent.write_bytes(b"x")
    old.write_bytes(b"y")
    old_ts = (datetime.now() - timedelta(days=10)).timestamp()
    os.utime(old, (old_ts, old_ts))

    main_app._prune_old_presave_backups(bdir)

    assert recent.is_file()
    assert not old.is_file()


def test_write_timestamped_presave_backup_prunes_after_copy(tmp_path: Path) -> None:
    src = tmp_path / "conti_utente_test.enc"
    src.write_bytes(b"db")
    bdir = tmp_path / "pre_save_backups"
    stale = bdir / "conti_utente_test_20250101_000000.enc"
    bdir.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"stale")
    stale_ts = (datetime.now() - timedelta(days=30)).timestamp()
    os.utime(stale, (stale_ts, stale_ts))

    with patch.object(main_app, "_presave_backups_dir", return_value=bdir):
        main_app._write_timestamped_presave_backup(src)

    remaining = list(bdir.glob("conti_utente_test_*.enc"))
    assert len(remaining) == 1
    assert not stale.is_file()
    assert remaining[0].stat().st_size == 2


def test_autorecover_corrupted_primary_from_presave(tmp_path: Path) -> None:
    ws = tmp_path / "data"
    ws.mkdir()
    key_path = ws / "conti_di_casa.key"
    from cryptography.fernet import Fernet

    key_path.write_bytes(Fernet.generate_key())
    primary = ws / "conti_utente_abc.enc"
    primary.write_bytes(b"")

    bdir = tmp_path / "pre_save_backups"
    bdir.mkdir()
    good = bdir / "conti_utente_abc_backup_20260713_120000.enc"
    token = Fernet(key_path.read_bytes()).encrypt(b'{"years":[]}')
    good.write_bytes(token)

    import data_workspace

    data_workspace.set_data_workspace_root(ws)
    with (
        patch.object(main_app, "_presave_backups_dir", return_value=bdir),
        patch.object(main_app, "_user_library_conti_support_dir", return_value=tmp_path / "lib"),
        patch.object(main_app.messagebox, "showinfo"),
    ):
        out = main_app._try_autorecover_corrupted_database_at_startup()

    assert out is not None
    db, path = out
    assert path == primary
    assert primary.stat().st_size > 256
    assert db == {"years": []}
