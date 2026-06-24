"""
Sidecar cifrato per l'app iOS light: ``*_light.enc`` nella stessa cartella del file ``.enc`` completo.

- Il desktop, dopo ogni salvataggio del DB completo, rigenera il file light con solo le
  registrazioni nella finestra mobile (ultimi 365 giorni + date future), più metadati
  completi (profilo, categorie/conti per anno incluso).
- All'avvio il desktop legge ``*_light.enc``, fonde **nuove righe** (``conti_light_record_id``) e **modifiche**
  (upsert / sospensioni) nel DB completo e, se qualcosa è stato importato, salva completo + sidecar avvisando
  l'utente. Se il merge è vuoto e il file light esiste già, **non** riscrive il sidecar (meno versioni Dropbox).
  Se ``*_light.enc`` manca, lo crea all'avvio.
- L'app iOS **non** riscrive il file ``.enc`` completo: aggiorna solo ``*_light.enc`` (con backup locale prima
  della scrittura); l'integrazione nel completo avviene sul desktop.
- Il JSON light include ``light_saldi`` (saldi allineati al **footer Saldi** del desktop: assoluti, alla data,
  di cui spese future, spese per carte di credito sulle colonne di riferimento, disponibilità (assoluti+CC, senza spese future); conti congelati esclusi)
  calcolati sul **DB completo**, così l'app iOS non ricostruisce i saldi dai soli movimenti nella finestra mobile.

L'app light usa la stessa **cartella dati** scelta sul desktop: ``.key``, ``conti_utente_<hash>.enc`` e
``conti_utente_<hash>_light.enc`` affiancati. Per ogni nuova registrazione sul telefono,
impostare ``conti_light_record_id`` a un UUID nuovo prima di salvare.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None

# Chiave record creata dall'app light (non usata dal desktop per inserimenti normali)
LIGHT_RECORD_ID_KEY = "conti_light_record_id"
LIGHT_EDIT_SUPERSEDES_YEAR = "conti_light_edit_supersedes_year"
LIGHT_EDIT_SUPERSEDES_LEGACY = "conti_light_edit_supersedes_legacy_key"
LIGHT_EDIT_SUPERSEDES_SI = "conti_light_edit_supersedes_source_index"
_ACCOUNT_VERIFICATION_FIELD_KEYS = (
    "account_primary_flags",
    "account_primary_with_flags",
    "account_secondary_flags",
    "account_secondary_with_flags",
)


def light_enc_path_for_primary(primary_enc: Path) -> Path:
    """Es. ``…/conti_utente_<hash>.enc`` → ``…/conti_utente_<hash>_light.enc`` nella stessa cartella.

    Se si passa per errore un path che è già ``*_light.enc`` (o con più ``_light`` nel nome, es. dopo
    copie o impostazione errata in Opzioni), i suffissi ``_light`` finali nello *stem* vengono tolti
    **prima** di aggiungerne uno solo, così non si generano ``*_light_light_light.enc`` in serie.
    """
    stem = primary_enc.stem
    _suf = "_light"
    while stem.endswith(_suf) and len(stem) > len(_suf):
        stem = stem[: -len(_suf)]
    return primary_enc.parent / f"{stem}{_suf}.enc"


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


def light_window_start_iso(*, today: date | None = None) -> str:
    """Primo giorno incluso della finestra (ISO), pari a oggi − 365 giorni."""
    t = today or date.today()
    return (t - timedelta(days=365)).isoformat()


def record_in_light_window(rec: dict, window_start_iso: str) -> bool:
    """True se ``date_iso`` è nella finestra [window_start, +∞)."""
    d = str(rec.get("date_iso") or "").strip()
    if len(d) < 10:
        return False
    return d[:10] >= window_start_iso[:10]


def build_light_database(full_db: dict) -> dict:
    """
    Copia profonda del DB con ``years`` ridotte: solo registrazioni nella finestra mobile,
    più l'anno di calendario massimo (anche senza movimenti) per consentire nuove immissioni.
    """
    window = light_window_start_iso()
    years_in = full_db.get("years") or []
    if not years_in:
        return copy.deepcopy(full_db)

    max_year = max(int(y.get("year", 0)) for y in years_in)
    years_out: list[dict] = []
    seen_max = False

    def _record_sort_key_newest_first(rec: dict) -> tuple[str, int]:
        """Allineato all’app iOS: data ISO decrescente, poi source_index decrescente."""
        d = str(rec.get("date_iso") or "").strip()[:10]
        try:
            si = int(rec.get("source_index") or 0)
        except (TypeError, ValueError):
            si = 0
        return (d, si)

    for y in years_in:
        yn = int(y.get("year", 0))
        filtered = [copy.deepcopy(r) for r in y.get("records") or [] if record_in_light_window(r, window)]
        filtered.sort(key=_record_sort_key_newest_first, reverse=True)
        if yn != max_year and not filtered:
            continue
        yc = copy.deepcopy(y)
        yc["records"] = filtered
        years_out.append(yc)
        if yn == max_year:
            seen_max = True

    if not seen_max:
        tmpl = next(y for y in years_in if int(y.get("year", 0)) == max_year)
        yc = {
            "year": max_year,
            "accounts": copy.deepcopy(tmpl.get("accounts", [])),
            "categories": copy.deepcopy(tmpl.get("categories", [])),
            "records": [],
        }
        for k, v in tmpl.items():
            if k not in yc:
                yc[k] = copy.deepcopy(v)
        years_out.append(yc)

    years_out.sort(key=lambda yy: int(yy["year"]))
    out = copy.deepcopy(full_db)
    out["years"] = years_out
    out["light_sidecar_generated_at"] = date.today().isoformat()
    out["light_sidecar_window_start"] = window
    _attach_light_saldi_snapshot(out, full_db)
    return out


def _attach_light_saldi_snapshot(light_db: dict, full_db: dict) -> None:
    """
    Inserisce ``light_saldi`` calcolato sul **database completo** (come Movimenti sul desktop).
    Il file light non contiene tutta la storia: i saldi non vanno ricostruiti solo dai movimenti nel sidecar.
    """
    if not (full_db.get("years") or []):
        return
    try:
        import main_app as _m
    except Exception:
        return
    try:
        snap = _m.compute_light_saldi_snapshot(full_db, today_iso=date.today().isoformat())
    except Exception:
        return
    if isinstance(snap, dict) and snap.get("rows"):
        light_db["light_saldi"] = snap


def _max_registration_number(db: dict) -> int:
    m = 0
    for y in db.get("years") or []:
        for r in y.get("records") or []:
            try:
                m = max(m, int(r.get("registration_number", 0) or 0))
            except (TypeError, ValueError):
                pass
    return m


def _collect_light_ids(db: dict) -> set[str]:
    s: set[str] = set()
    for y in db.get("years") or []:
        for r in y.get("records") or []:
            rid = str(r.get(LIGHT_RECORD_ID_KEY) or "").strip()
            if rid:
                s.add(rid)
    return s


def ensure_year_bucket_for_merge(db: dict, target_year: int) -> dict:
    years = db.setdefault("years", [])
    for y in years:
        if int(y.get("year", 0)) == int(target_year):
            return y
    if not years:
        raise ValueError("database senza anni")
    latest = max(years, key=lambda yy: int(yy["year"]))
    new_y = {
        "year": int(target_year),
        "accounts": copy.deepcopy(latest.get("accounts", [])),
        "categories": copy.deepcopy(latest.get("categories", [])),
        "records": [],
    }
    years.append(new_y)
    years.sort(key=lambda yy: int(yy["year"]))
    return new_y


def merge_light_new_records_into_main(main: dict, light: dict) -> int:
    """
    Aggiunge a ``main`` le registrazioni di ``light`` che hanno ``conti_light_record_id``
    non ancora presente in ``main``.
    """
    existing = _collect_light_ids(main)
    next_reg = _max_registration_number(main) + 1
    added = 0
    for yl in light.get("years") or []:
        ynum = int(yl.get("year", 0))
        for rec in yl.get("records") or []:
            rid = str(rec.get(LIGHT_RECORD_ID_KEY) or "").strip()
            if not rid or rid in existing:
                continue
            rec_copy = copy.deepcopy(rec)
            yb = ensure_year_bucket_for_merge(main, ynum)
            recs = yb.setdefault("records", [])
            next_si = max((int(r.get("source_index", 0) or 0) for r in recs), default=0) + 1
            rec_copy["source_index"] = next_si
            rec_copy["legacy_registration_number"] = next_si
            rec_copy["legacy_registration_key"] = f"APP:conti_light:{ynum}:{rid}"
            rec_copy["registration_number"] = next_reg
            next_reg += 1
            recs.append(rec_copy)
            existing.add(rid)
            added += 1
    return added


def _record_without_ios_supersedes_for_main_write(rec: dict) -> dict:
    out = copy.deepcopy(rec)
    for k in (
        LIGHT_EDIT_SUPERSEDES_YEAR,
        LIGHT_EDIT_SUPERSEDES_LEGACY,
        LIGHT_EDIT_SUPERSEDES_SI,
    ):
        out.pop(k, None)
    return out


def _copy_account_verification_fields(existing: dict, merged: dict) -> None:
    for k in _ACCOUNT_VERIFICATION_FIELD_KEYS:
        if k in existing:
            merged[k] = existing[k]


def _light_incoming_record_merged_with_main_verification(existing_in_main: dict, incoming: dict) -> dict:
    merged = copy.deepcopy(incoming)
    _copy_account_verification_fields(existing_in_main, merged)
    return merged


def _records_equal_for_light_merge(a: dict, b: dict) -> bool:
    """True se i due record sono equivalenti per il merge light → main."""
    return json.dumps(a, sort_keys=True, ensure_ascii=True) == json.dumps(
        b, sort_keys=True, ensure_ascii=True
    )


def _apply_light_record_update_if_changed(
    main: dict,
    *,
    year_index: int,
    record_index: int,
    incoming: dict,
) -> bool:
    """Sostituisce la riga solo se il merge modifica il contenuto. Ritorna True se applicato."""
    years = list(main.get("years") or [])
    yd = dict(years[year_index])
    recs = list(yd.get("records") or [])
    prev_main = recs[record_index]
    merged = _light_incoming_record_merged_with_main_verification(prev_main, incoming)
    if _records_equal_for_light_merge(prev_main, merged):
        return False
    recs[record_index] = merged
    yd["records"] = recs
    years[year_index] = yd
    main["years"] = years
    return True


def _find_in_main_index_by_conti_light_id(main: dict, conti_id: str) -> tuple[int, int] | None:
    cid = str(conti_id or "").strip()
    if not cid:
        return None
    for yi, yd in enumerate(main.get("years") or []):
        for ri, r in enumerate(yd.get("records") or []):
            if str(r.get(LIGHT_RECORD_ID_KEY) or "").strip() == cid:
                return yi, ri
    return None


def _find_in_main_index_by_year_and_legacy(main: dict, year: int, legacy_key: str) -> tuple[int, int] | None:
    lk = str(legacy_key or "").strip()
    if not lk:
        return None
    for yi, yd in enumerate(main.get("years") or []):
        if int(yd.get("year", 0)) != int(year):
            continue
        for ri, r in enumerate(yd.get("records") or []):
            if str(r.get("legacy_registration_key") or "").strip() == lk:
                return yi, ri
    return None


def _remove_main_record_for_ios_supersede(
    main: dict,
    *,
    year: int,
    legacy_key: str,
    source_index: int,
) -> bool:
    lk = str(legacy_key or "").strip()
    years = main.get("years") or []
    yi = next((i for i, yd in enumerate(years) if int(yd.get("year", 0)) == int(year)), None)
    if yi is None:
        return False
    yd = years[yi]
    recs = list(yd.get("records") or [])
    if not recs:
        return False
    rj: int | None = None
    if lk:
        rj = next(
            (i for i, r in enumerate(recs) if str(r.get("legacy_registration_key") or "").strip() == lk),
            None,
        )
    if rj is None and source_index:
        rj = next(
            (i for i, r in enumerate(recs) if int(r.get("source_index", 0) or 0) == int(source_index)),
            None,
        )
    if rj is None:
        return False
    recs.pop(rj)
    yd = dict(yd)
    yd["records"] = recs
    years = list(years)
    years[yi] = yd
    main["years"] = years
    return True


def upsert_light_session_records_in_main(main: dict, light: dict) -> int:
    """
    Sostituisce o sposta in ``main`` le righe del light (per ``conti_light_record_id`` e/o
    ``legacy_registration_key`` nello stesso anno). Preserva i campi verifica conto già presenti sul main.
    """
    flat: list[dict] = []
    for yl in light.get("years") or []:
        for rec in yl.get("records") or []:
            if isinstance(rec, dict):
                flat.append(rec)
    updated = 0
    for rec0 in flat:
        if rec0.get(LIGHT_EDIT_SUPERSEDES_YEAR) is None:
            continue
        try:
            y_s = int(rec0.get(LIGHT_EDIT_SUPERSEDES_YEAR, 0) or 0)
        except (TypeError, ValueError):
            y_s = 0
        k_s = str(rec0.get(LIGHT_EDIT_SUPERSEDES_LEGACY) or "").strip()
        try:
            si_s = int(rec0.get(LIGHT_EDIT_SUPERSEDES_SI, 0) or 0)
        except (TypeError, ValueError):
            si_s = 0
        if y_s and _remove_main_record_for_ios_supersede(
            main, year=y_s, legacy_key=k_s, source_index=si_s
        ):
            updated += 1
    for rec0 in flat:
        rec_l = _record_without_ios_supersedes_for_main_write(rec0)
        rid = str(rec_l.get(LIGHT_RECORD_ID_KEY) or "").strip()
        if not rid:
            # Copie del sidecar già presenti nel completo (senza intervento iOS): non upsert.
            continue
        try:
            y_new = int(rec_l.get("year", 0) or 0)
        except (TypeError, ValueError):
            continue
        if y_new <= 0:
            continue
        legacy = str(rec_l.get("legacy_registration_key") or "").strip()
        found: tuple[int, int] | None = _find_in_main_index_by_conti_light_id(main, rid)
        if found is None and legacy:
            found = _find_in_main_index_by_year_and_legacy(main, y_new, legacy)
        years = main.get("years") or []
        if found is not None:
            fyi, fri = found
            y_old = int(years[fyi].get("year", 0))
            if y_old == y_new:
                if _apply_light_record_update_if_changed(
                    main, year_index=fyi, record_index=fri, incoming=rec_l
                ):
                    updated += 1
            else:
                yd_old = dict(years[fyi])
                recs_old = list(yd_old.get("records") or [])
                removed = recs_old[fri]
                recs_old.pop(fri)
                yd_old["records"] = recs_old
                years = list(years)
                years[fyi] = yd_old
                main["years"] = years
                ensure_year_bucket_for_merge(main, y_new)
                years = main.get("years") or []
                yi_n = next(i for i, yd in enumerate(years) if int(yd.get("year", 0)) == y_new)
                yd_n = dict(years[yi_n])
                recs_n = list(yd_n.get("records") or [])
                merged_incoming = _light_incoming_record_merged_with_main_verification(
                    removed, rec_l
                )
                applied = False
                if rid:
                    j = next(
                        (
                            i
                            for i, r in enumerate(recs_n)
                            if str(r.get(LIGHT_RECORD_ID_KEY) or "").strip() == rid
                        ),
                        None,
                    )
                    if j is not None:
                        prev_nj = recs_n[j]
                        merged_nj = _light_incoming_record_merged_with_main_verification(
                            prev_nj, rec_l
                        )
                        if not _records_equal_for_light_merge(prev_nj, merged_nj):
                            recs_n[j] = merged_nj
                            applied = True
                    else:
                        recs_n.append(merged_incoming)
                        applied = True
                else:
                    recs_n.append(merged_incoming)
                    applied = True
                if applied:
                    yd_n["records"] = recs_n
                    years = list(years)
                    years[yi_n] = yd_n
                    main["years"] = years
                    updated += 1
    return updated


def merge_light_sidecar_into_main(main: dict, light: dict) -> tuple[int, int]:
    """Fonde sidecar light in ``main``. Ritorna ``(nuove_righe, righe_aggiornate)``."""
    n_up = upsert_light_session_records_in_main(main, light)
    n_new = merge_light_new_records_into_main(main, light)
    return n_new, n_up


def write_light_enc_sidecar(db: dict, primary_enc: Path, key_path: Path) -> None:
    """Scrive ``<stem>_light.enc`` nella stessa cartella di ``primary_enc``."""
    if Fernet is None:
        return
    if not key_path.is_file():
        return
    light_db = build_light_database(db)
    key = key_path.read_bytes()
    token = Fernet(key).encrypt(
        json.dumps(light_db, ensure_ascii=True, indent=2).encode("utf-8")
    )
    out = light_enc_path_for_primary(primary_enc)
    _atomic_write_bytes(out, token)


def load_light_enc_if_present(primary_enc: Path, key_path: Path) -> dict | None:
    """Carica il sidecar light accanto al file principale, se esiste."""
    if Fernet is None:
        return None
    if not key_path.is_file():
        return None
    p = light_enc_path_for_primary(primary_enc)
    if not p.is_file():
        return None
    try:
        fernet = Fernet(key_path.read_bytes())
        raw = fernet.decrypt(p.read_bytes())
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def merge_light_sidecar_at_startup(
    db: dict,
    primary_enc: Path,
    key_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
    ui_pump: Callable[[], object] | None = None,
) -> tuple[int, int]:
    """Se esiste il sidecar, fonde le registrazioni light nel DB già caricato.

    Ritorna ``(nuove_righe, righe_aggiornate)``.
    """
    p = light_enc_path_for_primary(primary_enc)
    if not p.is_file():
        return 0, 0
    if progress is not None:
        progress("Attesa aggiornamento file Conti light (Dropbox)…")
    try:
        import cloud_sync_wait

        cloud_sync_wait.wait_for_paths_stable_if_cloud(
            [p, key_path],
            ui_parent=None,
            ui_pump=ui_pump,
            light_sidecar=True,
        )
    except Exception:
        pass
    if progress is not None:
        progress("Integrazione dati da Conti light…")
    light = load_light_enc_if_present(primary_enc, key_path)
    if not light:
        return 0, 0
    return merge_light_sidecar_into_main(db, light)
