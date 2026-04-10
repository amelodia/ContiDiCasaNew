"""
Sidecar cifrato per l'app iOS light: ``*_light.enc`` nella stessa cartella del file ``.enc`` completo.

- Il desktop, dopo ogni salvataggio del DB completo, rigenera il file light con solo le
  registrazioni nella finestra mobile (ultimi 365 giorni + date future), più metadati
  completi (profilo, categorie/conti per anno incluso).
- All'avvio il desktop importa dal file light le righe create sul telefono, riconosciute
  dal campo ``conti_light_record_id`` (UUID), e le fonde nel DB principale.
- Il JSON light include ``light_saldi`` (saldi assoluti + alla data di oggi) calcolati sul **DB completo**,
  così l'app iOS non ricostruisce i saldi dai soli movimenti nella finestra mobile.

L'app light usa la stessa **cartella dati** scelta sul desktop: ``.key``, ``conti_utente_<hash>.enc`` e
``conti_utente_<hash>_light.enc`` affiancati. Per ogni nuova registrazione sul telefono,
impostare ``conti_light_record_id`` a un UUID nuovo prima di salvare.
"""
from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover
    Fernet = None

# Chiave record creata dall'app light (non usata dal desktop per inserimenti normali)
LIGHT_RECORD_ID_KEY = "conti_light_record_id"


def light_enc_path_for_primary(primary_enc: Path) -> Path:
    """Es. ``…/conti_utente_<hash>.enc`` → ``…/conti_utente_<hash>_light.enc`` nella stessa cartella."""
    return primary_enc.parent / f"{primary_enc.stem}_light.enc"


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
        ly, names, amts_abs = _m.compute_balances_from_2022(full_db)
        _, _, amts_today = _m.compute_balances_from_2022_asof(
            full_db, cutoff_date_iso=date.today().isoformat()
        )
    except Exception:
        return
    rows: list[dict] = []
    for i, name in enumerate(names):
        rows.append(
            {
                "account_code": str(i + 1),
                "account_name": str(name or "").strip(),
                "saldo_assoluto": str(amts_abs[i]),
                "saldo_alla_data": str(amts_today[i]),
            }
        )
    light_db["light_saldi"] = {
        "snapshot_date_iso": date.today().isoformat(),
        "year_basis": int(ly),
        "rows": rows,
    }


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
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(token)


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
) -> int:
    """Se esiste il sidecar, fonde le registrazioni light nel DB già caricato. Ritorna il numero di righe aggiunte."""
    light = load_light_enc_if_present(primary_enc, key_path)
    if not light:
        return 0
    return merge_light_new_records_into_main(db, light)
