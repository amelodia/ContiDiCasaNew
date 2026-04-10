#!/usr/bin/env python3
"""
ImportLegacy for Conti di Casa.

Reads legacy yearly archives from VB6 `.aco` files and produces
a single JSON database for the new app.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


EURO_CONVERSION_RATE = Decimal("1936.27")
RECORD_LEN = 121
ANNULLATA_PREFIX = "registrazione annullata"

# New app input constraints
MIN_AMOUNT_EUR = Decimal("-999999999.99")
MAX_AMOUNT_EUR = Decimal("999999999.99")
MAX_CATEGORY_NAME_LEN = 20
MAX_CATEGORY_NOTE_LEN = 100
MAX_ACCOUNT_NAME_LEN = 16
# Limite pratico sul numero di voci (nuova app / scheda Categorie e conti).
MAX_CATEGORIES_COUNT = 100
MAX_ACCOUNTS_COUNT = 20
MAX_RECORD_NOTE_LEN = 100
MAX_CHEQUE_LEN = 12  # es. «Periodica» nelle registrazioni periodiche

_AMOUNT_RE = re.compile(r"[+-]?\d[\d\.]*([,\.]\d+)?")


@dataclass
class LegacyRecord:
    year: int
    source_folder: str
    source_file: str
    source_index: int
    legacy_registration_number: int
    legacy_registration_key: str
    date_iso: str
    category_code: str
    category_name: str | None
    category_note: str | None
    account_primary_code: str
    account_primary_flags: str
    account_primary_with_flags: str
    account_primary_name: str | None
    account_secondary_code: str
    account_secondary_flags: str
    account_secondary_with_flags: str
    account_secondary_name: str | None
    amount_eur: str
    amount_lire_original: str | None
    note: str
    cheque: str
    raw_flags: str
    is_cancelled: bool
    source_currency: str
    display_currency: str
    display_amount: str
    raw_record: str


def normalize_euro_input(value: str) -> Decimal:
    """
    Parse user input amount for the new app.
    Both '.' and ',' are accepted as decimal separators.
    """
    s = value.strip().replace(" ", "")
    if not s:
        raise ValueError("Importo vuoto")
    # Accept both separators in input and normalize to decimal dot.
    s = s.replace(",", ".")
    if s.count(".") > 1:
        parts = s.split(".")
        s = "".join(parts[:-1]) + "." + parts[-1]
    amount = Decimal(s)
    if amount < MIN_AMOUNT_EUR or amount > MAX_AMOUNT_EUR:
        raise ValueError(f"Importo fuori limiti: {amount}")
    return amount.quantize(Decimal("0.01"))


def format_euro_it(value: Decimal) -> str:
    """
    Format euro amount using Italian style: thousands dot, decimals comma.
    """
    sign = "-" if value < 0 else ""
    v = abs(value).quantize(Decimal("0.01"))
    integer_part, decimal_part = f"{v:.2f}".split(".")
    grouped = f"{int(integer_part):,}".replace(",", ".")
    return f"{sign}{grouped},{decimal_part}"


def clip_text(value: str, max_len: int) -> str:
    return value[:max_len]


def parse_aco_list(path: Path) -> list[str]:
    """Parse list files like *.cat.aco and *.coc.aco."""
    lines = path.read_text(encoding="latin-1", errors="ignore").splitlines()
    if not lines:
        return []
    items: list[str] = []
    for line in lines[1:]:
        clean = line.strip().strip('"').strip()
        if not clean or clean == "\x1a":
            continue
        clean = clean.replace("\x1a", "").strip()
        if clean:
            items.append(clean)
    return items


def parse_amount(value: str) -> Decimal:
    clean = value.strip().replace("E", "").replace("L", "")
    if not clean.strip():
        return Decimal("0")
    match = _AMOUNT_RE.search(clean)
    if not match:
        raise ValueError(f"Importo non valido: {value!r}")
    clean = match.group(0).replace(".", "").replace(",", ".")
    try:
        return Decimal(clean)
    except InvalidOperation as exc:
        raise ValueError(f"Importo non valido: {value!r}") from exc


def format_money(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.001"))
    return f"{quantized:.3f}"


def format_date_yyyymmdd(raw: str) -> str:
    d = raw.strip()
    if len(d) != 8 or not d.isdigit():
        raise ValueError(f"Data non valida nel record: {raw!r}")
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def parse_dat_records(
    path: Path,
    year: int,
    categories: list[str],
    accounts: list[str],
    category_notes_from_2026: list[str],
) -> list[LegacyRecord]:
    content = path.read_text(encoding="latin-1", errors="ignore")
    total = len(content) // RECORD_LEN
    out: list[LegacyRecord] = []
    for idx in range(total):
        record = content[idx * RECORD_LEN : (idx + 1) * RECORD_LEN]
        if len(record) < RECORD_LEN:
            continue

        raw_date = record[0:8]
        _lire_slot = record[8:23]  # non importato: solo euro
        importo_euro_raw = record[23:37]
        categoria_raw = record[37:39]
        conto1_raw = record[39:40]
        ver1 = record[40:41]
        ver2 = record[41:42]
        conto2_raw = record[42:43]
        ver3 = record[43:44]
        ver4 = record[44:45]
        assegno_raw = record[45:52]
        nota_raw = record[52:121]

        note = nota_raw.strip()
        is_cancelled = note.lower().startswith(ANNULLATA_PREFIX)
        flags = f"{ver1}{ver2}{ver3}{ver4}"
        primary_flags = f"{ver1}{ver2}".replace(" ", "")
        secondary_flags = f"{ver3}{ver4}".replace(" ", "")

        cat_code_raw = categoria_raw.strip()
        # Conti90: le prime 8 registrazioni del dat sono dotazioni; il campo categoria in quegli slot può essere errato.
        if year == 1990 and idx < 8:
            cat_int = 0
        elif not cat_code_raw.isdigit():
            continue
        else:
            cat_int = int(cat_code_raw)
        if cat_int == 0 and year != 1990:
            continue
        cat_idx = cat_int
        if cat_idx < 0 or cat_idx >= len(categories):
            continue

        # In Conti90 le prime dotazioni possono avere data/importo euro non conformi al resto del dat.
        rs = raw_date.strip()
        if not rs or not rs.isdigit() or len(rs) != 8:
            if year == 1990 and cat_int == 0:
                date_iso = "1990-01-01"
            else:
                continue
        else:
            try:
                date_iso = format_date_yyyymmdd(raw_date)
            except ValueError:
                if year == 1990 and cat_int == 0:
                    date_iso = "1990-01-01"
                else:
                    continue

        try:
            amount_eur = parse_amount(importo_euro_raw)
        except ValueError:
            if year == 1990 and cat_int == 0:
                amount_eur = Decimal("0")
            else:
                continue

        category_name = clip_text(categories[cat_idx], MAX_CATEGORY_NAME_LEN)
        cat_code = str(cat_int)
        # Note *not.aco: slot 0 = Dotazione (non abbinato); codice categoria k>=1 usa slot k.
        category_note = None
        if (
            cat_idx > 0
            and cat_idx < len(category_notes_from_2026)
            and str(category_notes_from_2026[cat_idx] or "").strip()
        ):
            category_note = clip_text(str(category_notes_from_2026[cat_idx]), MAX_CATEGORY_NOTE_LEN)

        acc1_code = conto1_raw.strip()
        acc1_idx = int(acc1_code) if acc1_code.isdigit() else 0
        account_primary_name = (
            clip_text(accounts[acc1_idx - 1], MAX_ACCOUNT_NAME_LEN) if 1 <= acc1_idx <= len(accounts) else None
        )

        acc2_code = conto2_raw.strip()
        acc2_idx = int(acc2_code) if acc2_code.isdigit() else 0
        account_secondary_name = (
            clip_text(accounts[acc2_idx - 1], MAX_ACCOUNT_NAME_LEN) if 1 <= acc2_idx <= len(accounts) else None
        )

        source_currency = "EUR"
        display_currency = "EUR"
        display_amount = format_money(amount_eur)

        out.append(
            LegacyRecord(
                year=year,
                source_folder=path.parent.name,
                source_file=path.name,
                source_index=idx + 1,
                legacy_registration_number=idx + 1,
                legacy_registration_key=f"{path.parent.name}:{path.name}:{idx + 1}",
                date_iso=date_iso,
                category_code=cat_code,
                category_name=category_name,
                category_note=category_note,
                account_primary_code=acc1_code,
                account_primary_flags=primary_flags,
                account_primary_with_flags=f"{acc1_code}{primary_flags}" if acc1_code else "",
                account_primary_name=account_primary_name,
                account_secondary_code=acc2_code,
                account_secondary_flags=secondary_flags,
                account_secondary_with_flags=f"{acc2_code}{secondary_flags}" if acc2_code else "",
                account_secondary_name=account_secondary_name,
                amount_eur=format_money(amount_eur),
                amount_lire_original=None,
                note=clip_text(note, MAX_RECORD_NOTE_LEN),
                cheque=clip_text(assegno_raw.strip(), MAX_CHEQUE_LEN),
                raw_flags=flags,
                is_cancelled=is_cancelled,
                source_currency=source_currency,
                display_currency=display_currency,
                display_amount=display_amount,
                raw_record=record,
            )
        )
    return out


def guess_year_from_folder(folder_name: str) -> int:
    """
    Conti90 → 1990, Conti26 → 2026. Accetta anche cartelle tipo Conti1990 / Conti2026 (4 cifre).
    """
    fn = folder_name.strip()
    m4 = re.fullmatch(r"Conti(\d{4})", fn, flags=re.IGNORECASE)
    if m4:
        y = int(m4.group(1))
        if 1900 <= y <= 2100:
            return y
    m2 = re.fullmatch(r"Conti(\d{2})", fn, flags=re.IGNORECASE)
    if m2:
        yy = int(m2.group(1))
        return 1900 + yy if yy >= 90 else 2000 + yy
    raise ValueError(f"Impossibile dedurre l'anno da: {folder_name!r}")


def find_single_file(folder: Path, pattern: str) -> Path:
    candidates = sorted(folder.glob(pattern))
    if len(candidates) != 1:
        raise FileNotFoundError(f"Atteso 1 file {pattern} in {folder}, trovati {len(candidates)}")
    return candidates[0]


# *sld.aco (es. Conti26): prima riga = indicatore valuta (E/L), da ignorare per i numeri;
# a seguire esattamente 8 saldi assoluti in euro, conto 1 = Cassa … conto 8.
SLD_LEGACY_ACCOUNT_SLOTS = 8


def parse_sld_balances(folder: Path, n_accounts: int) -> dict[str, object] | None:
    """
    Legge *sld.aco: prima riga valuta (E/L) da trascurare come dato numerico, poi 8 saldi
    assoluti per i primi 8 conti (Cassa = primo). Estende con zeri se il piano ha più conti.
    """
    candidates = sorted(folder.glob("*sld.aco"))
    if len(candidates) != 1:
        return None
    lines = [ln.strip().strip('"') for ln in candidates[0].read_text(encoding="latin-1", errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    first_parts = lines[0].split()
    valuta = (first_parts[0].upper()[:1] if first_parts else "E")
    if valuta not in ("E", "L"):
        valuta = "E"
    nums: list[Decimal] = []

    def _push_token(t: str) -> None:
        nonlocal nums
        if len(nums) >= SLD_LEGACY_ACCOUNT_SLOTS:
            return
        t = t.strip()
        if not t:
            return
        clean = t.replace(".", "").replace(",", ".") if "," in t else t
        try:
            nums.append(Decimal(clean))
        except InvalidOperation:
            nums.append(Decimal("0"))

    if first_parts and first_parts[0].upper() in ("E", "L"):
        for part in first_parts[1:]:
            if len(nums) >= SLD_LEGACY_ACCOUNT_SLOTS:
                break
            _push_token(part)
    for line in lines[1:]:
        if len(nums) >= SLD_LEGACY_ACCOUNT_SLOTS:
            break
        for part in line.split():
            if len(nums) >= SLD_LEGACY_ACCOUNT_SLOTS:
                break
            _push_token(part)
    while len(nums) < SLD_LEGACY_ACCOUNT_SLOTS:
        nums.append(Decimal("0"))
    nums = nums[:SLD_LEGACY_ACCOUNT_SLOTS]
    amounts: list[str] = []
    for i in range(max(n_accounts, 1)):
        if i < len(nums):
            amounts.append(str(nums[i]))
        else:
            amounts.append("0")
    return {
        "source_file": candidates[0].name,
        "valuta": valuta,
        "amounts": amounts,
    }


def _clean_not_aco_line(line: str) -> str:
    return line.strip().strip('"').replace("\x1a", "").strip()


def parse_category_notes_for_n_categories(folder: Path, n_categories: int) -> list[str]:
    """
    *not.aco: di solito **nessun titolo**; **non** c’è riga per la Dotazione (codice 0).

    La **prima riga** del file va sulla **Girata** (codice 1), la seconda sul codice 2, ecc.
    Tipico: 51 categorie in *cat.aco (0…50) e **50 righe** in *not.aco → out[1]=riga0, …, out[50]=riga49.

    Opzionale: una sola riga titolo in più (come *cat.aco) se len(file) == n_categories + 1.
    """
    notes_files = sorted(folder.glob("*not.aco"))
    if not notes_files or n_categories <= 0:
        return []
    raw_lines = notes_files[0].read_text(encoding="latin-1", errors="ignore").splitlines()
    slots = [_clean_not_aco_line(ln) for ln in raw_lines]
    if not slots:
        return [""] * n_categories
    if len(slots) == n_categories + 1:
        slots = slots[1:]
    # Al massimo (n_categories - 1) righe utili (codici 1…N-1)
    n_note_lines = max(0, n_categories - 1)
    if len(slots) > n_note_lines:
        slots = slots[:n_note_lines]

    out = [""] * n_categories
    out[0] = ""
    for k in range(1, n_categories):
        fi = k - 1
        if fi < len(slots) and str(slots[fi] or "").strip():
            out[k] = clip_text(str(slots[fi]), MAX_CATEGORY_NOTE_LEN)
    return out


def load_year(
    folder: Path,
    *,
    category_notes_2026: list[str],
    legacy_saldi_for_year: dict | None,
    category_notes_source_filename: str | None,
) -> dict:
    year = guess_year_from_folder(folder.name)
    cat_file = find_single_file(folder, "*cat.aco")
    coc_file = find_single_file(folder, "*coc.aco")
    dat_file = find_single_file(folder, "*dat.aco")
    not_candidates = sorted(folder.glob("*not.aco"))

    categories = parse_aco_list(cat_file)
    accounts = parse_aco_list(coc_file)
    records = parse_dat_records(
        dat_file, year, categories, accounts, category_notes_2026
    )

    return {
        "year": year,
        "folder": folder.name,
        "source_files": {
            "dat": dat_file.name,
            "cat": cat_file.name,
            "coc": coc_file.name,
            "not": category_notes_source_filename
            or (not_candidates[0].name if not_candidates else None),
            "sld": (legacy_saldi_for_year or {}).get("source_file")
            if isinstance(legacy_saldi_for_year, dict)
            else None,
        },
        "legacy_saldi": legacy_saldi_for_year,
        "categories": [
            {
                "code": str(i - 1),
                "name": clip_text(name, MAX_CATEGORY_NAME_LEN),
                "note": (
                    None
                    if (i - 1) == 0
                    else (
                        clip_text(category_notes_2026[i - 1], MAX_CATEGORY_NOTE_LEN)
                        if (i - 1) < len(category_notes_2026)
                        and str(category_notes_2026[i - 1] or "").strip()
                        else None
                    )
                ),
            }
            for i, name in enumerate(categories, start=1)
        ],
        "accounts": [
            {"code": str(i), "name": clip_text(name, MAX_ACCOUNT_NAME_LEN)}
            for i, name in enumerate(accounts, start=1)
        ],
        "records": [asdict(r) for r in records],
    }


def iter_year_folders(root: Path) -> Iterable[Path]:
    """Cartelle annuali: Conti90, Conti26, oppure Conti1990, Conti2026, …"""
    seen: set[Path] = set()
    for pattern in ("Conti????", "Conti??"):
        for path in sorted(root.glob(pattern)):
            if not path.is_dir():
                continue
            key = path.resolve()
            if key in seen:
                continue
            try:
                guess_year_from_folder(path.name)
            except ValueError:
                continue
            seen.add(key)
            yield path


def build_unified_database(cdc_root: Path) -> dict:
    def _folder_year_key(p: Path) -> tuple[int, str]:
        try:
            return (guess_year_from_folder(p.name), p.name)
        except ValueError:
            return (99999, p.name)

    folders = sorted(iter_year_folders(cdc_root), key=_folder_year_key)
    folder_2026: Path | None = None
    for folder in folders:
        try:
            if guess_year_from_folder(folder.name) == 2026:
                folder_2026 = folder
                break
        except ValueError:
            continue

    category_notes_2026: list[str] = []
    not_name_2026: str | None = None
    legacy_saldi_2026: dict | None = None
    if folder_2026 is not None:
        nn = sorted(folder_2026.glob("*not.aco"))
        not_name_2026 = nn[0].name if nn else None
        try:
            cat_26 = find_single_file(folder_2026, "*cat.aco")
            n_cat_26 = len(parse_aco_list(cat_26))
            category_notes_2026 = parse_category_notes_for_n_categories(folder_2026, n_cat_26)
        except FileNotFoundError:
            category_notes_2026 = []
        try:
            coc_26 = find_single_file(folder_2026, "*coc.aco")
            accounts_26 = parse_aco_list(coc_26)
            legacy_saldi_2026 = parse_sld_balances(folder_2026, len(accounts_26))
        except FileNotFoundError:
            legacy_saldi_2026 = None

    years_data: list[dict] = []
    skipped_years: list[dict[str, str]] = []
    for folder in folders:
        try:
            y = guess_year_from_folder(folder.name)
            saldi = legacy_saldi_2026 if y == 2026 else None
            years_data.append(
                load_year(
                    folder,
                    category_notes_2026=category_notes_2026,
                    legacy_saldi_for_year=saldi,
                    category_notes_source_filename=not_name_2026,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            skipped_years.append({"folder": folder.name, "reason": str(exc)})
    all_records = [record for year_data in years_data for record in year_data["records"]]
    girata_missing_second: list[dict[str, str | int]] = []
    for rec in all_records:
        cat_code = str(rec.get("category_code", "")).strip()
        cat_name_u = (rec.get("category_name") or "").upper()
        is_girata = cat_code == "1" or "GIRATA.CONTO/CONTO" in cat_name_u or "GIRATA CONTO/CONTO" in cat_name_u
        if is_girata:
            if not (rec.get("account_primary_code") and rec.get("account_secondary_code")):
                girata_missing_second.append(
                    {
                        "year": rec["year"],
                        "source_folder": rec["source_folder"],
                        "source_index": rec["source_index"],
                        "date_iso": rec["date_iso"],
                        "category_name": rec.get("category_name") or "",
                    }
                )
    return {
        "generated_at": date.today().isoformat(),
        "source": str(cdc_root),
        "schema_version": 1,
        "exchange_rate_lira_eur": str(EURO_CONVERSION_RATE),
        "years_imported": [y["year"] for y in years_data],
        "years_skipped": skipped_years,
        "years": years_data,
        "records_total": len(all_records),
        "records_active": sum(1 for r in all_records if not r["is_cancelled"]),
        "records_cancelled": sum(1 for r in all_records if r["is_cancelled"]),
        "girata_checks": {
            "total_girata_records": sum(
                1
                for r in all_records
                if str(r.get("category_code", "")).strip() == "1"
                or "GIRATA.CONTO/CONTO" in (r.get("category_name") or "").upper()
                or "GIRATA CONTO/CONTO" in (r.get("category_name") or "").upper()
            ),
            "missing_second_account_count": len(girata_missing_second),
            "missing_second_account_samples": girata_missing_second[:20],
        },
    }


def run_import_legacy(cdc_root: Path | str, output: Path | str) -> dict:
    """
    Public entrypoint for integrating ImportLegacy into the main app.

    Returns a summary dict and writes the unified JSON output.
    """
    cdc_root_path = Path(cdc_root)
    output_path = Path(output)

    db = build_unified_database(cdc_root_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(db, ensure_ascii=True, indent=2), encoding="utf-8")

    return {
        "years": len(db["years"]),
        "records_total": db["records_total"],
        "records_active": db["records_active"],
        "records_cancelled": db["records_cancelled"],
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa archivio legacy Conti di Casa")
    parser.add_argument(
        "--cdc-root",
        type=Path,
        default=Path("/Users/macand/Library/CloudStorage/Dropbox/CdC"),
        help="Cartella che contiene i database annuali Conti??",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("legacy_import/unified_legacy_import.json"),
        help="Percorso file JSON di output",
    )
    args = parser.parse_args()

    result = run_import_legacy(args.cdc_root, args.output)
    print(
        f"Import completato: anni={result['years']}, "
        f"record_totali={result['records_total']}, "
        f"attivi={result['records_active']}, "
        f"annullati={result['records_cancelled']}"
    )
    print(f"Output: {result['output']}")


if __name__ == "__main__":
    main()
