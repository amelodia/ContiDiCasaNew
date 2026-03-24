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
MAX_RECORD_NOTE_LEN = 100
MAX_CHEQUE_LEN = 8

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


def parse_dat_records(path: Path, year: int, categories: list[str], accounts: list[str]) -> list[LegacyRecord]:
    content = path.read_text(encoding="latin-1", errors="ignore")
    total = len(content) // RECORD_LEN
    out: list[LegacyRecord] = []
    category_notes = parse_category_notes(path.parent)
    for idx in range(total):
        record = content[idx * RECORD_LEN : (idx + 1) * RECORD_LEN]
        if len(record) < RECORD_LEN:
            continue

        raw_date = record[0:8]
        importo_lire_raw = record[8:23]
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

        # Some legacy slots are placeholders for cancelled records.
        if not raw_date.strip() or not raw_date.strip().isdigit():
            continue
        date_iso = format_date_yyyymmdd(raw_date)
        amount_eur = parse_amount(importo_euro_raw)
        amount_lire = parse_amount(importo_lire_raw.replace("E", "").replace("L", ""))

        cat_code = categoria_raw.strip()
        cat_idx = int(cat_code) if cat_code.isdigit() else -1
        category_name = clip_text(categories[cat_idx], MAX_CATEGORY_NAME_LEN) if 0 <= cat_idx < len(categories) else None
        category_note = (
            clip_text(category_notes[cat_idx], MAX_CATEGORY_NOTE_LEN)
            if 0 <= cat_idx < len(category_notes)
            else None
        )

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

        source_currency = "LIRE" if year <= 2001 else "EUR"
        if source_currency == "LIRE":
            display_currency = "LIRE"
            display_amount = format_money(amount_lire)
        else:
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
                amount_lire_original=format_money(amount_lire) if year <= 2001 else None,
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
    suffix = folder_name[-2:]
    if not suffix.isdigit():
        raise ValueError(f"Impossibile dedurre l'anno da: {folder_name}")
    yy = int(suffix)
    return 1900 + yy if yy >= 90 else 2000 + yy


def find_single_file(folder: Path, pattern: str) -> Path:
    candidates = sorted(folder.glob(pattern))
    if len(candidates) != 1:
        raise FileNotFoundError(f"Atteso 1 file {pattern} in {folder}, trovati {len(candidates)}")
    return candidates[0]


def parse_sld_balances(folder: Path, n_accounts: int) -> dict[str, object] | None:
    """
    Legge *sld.aco come fa il programma legacy: prima riga valuta (L/E), poi N saldi.
    Autoritativo per i saldi di chiusura anno (include effetto Dotazione iniziale).
    """
    candidates = sorted(folder.glob("*sld.aco"))
    if len(candidates) != 1:
        return None
    lines = [ln.strip().strip('"') for ln in candidates[0].read_text(encoding="latin-1", errors="ignore").splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    valuta = lines[0].upper()[:1]
    raw_amounts = lines[1 : 1 + n_accounts]
    if len(raw_amounts) < n_accounts:
        return None
    amounts: list[str] = []
    for raw in raw_amounts:
        clean = raw.replace(".", "").replace(",", ".") if "," in raw else raw
        try:
            dec = Decimal(clean)
        except InvalidOperation:
            dec = Decimal("0")
        amounts.append(str(dec))
    return {
        "source_file": candidates[0].name,
        "valuta": valuta,
        "amounts": amounts,
    }


def parse_category_notes(folder: Path) -> list[str]:
    notes_files = sorted(folder.glob("*not.aco"))
    if not notes_files:
        return []
    lines = notes_files[0].read_text(encoding="latin-1", errors="ignore").splitlines()
    notes: list[str] = []
    for line in lines:
        clean = line.strip().strip('"').replace("\x1a", "").strip()
        if clean:
            notes.append(clean)
    return notes


def load_year(folder: Path) -> dict:
    year = guess_year_from_folder(folder.name)
    cat_file = find_single_file(folder, "*cat.aco")
    coc_file = find_single_file(folder, "*coc.aco")
    dat_file = find_single_file(folder, "*dat.aco")
    not_candidates = sorted(folder.glob("*not.aco"))

    categories = parse_aco_list(cat_file)
    accounts = parse_aco_list(coc_file)
    records = parse_dat_records(dat_file, year, categories, accounts)
    category_notes = parse_category_notes(folder)
    legacy_saldi = parse_sld_balances(folder, len(accounts))

    return {
        "year": year,
        "folder": folder.name,
        "source_files": {
            "dat": dat_file.name,
            "cat": cat_file.name,
            "coc": coc_file.name,
            "not": not_candidates[0].name if not_candidates else None,
            "sld": legacy_saldi["source_file"] if legacy_saldi else None,
        },
        "legacy_saldi": legacy_saldi,
        "categories": [
            {
                "code": str(i - 1),
                "name": clip_text(name, MAX_CATEGORY_NAME_LEN),
                "note": clip_text(category_notes[i - 1], MAX_CATEGORY_NOTE_LEN)
                if i - 1 < len(category_notes)
                else None,
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
    for path in sorted(root.glob("Conti??")):
        if path.is_dir():
            yield path


def build_unified_database(cdc_root: Path) -> dict:
    years_data: list[dict] = []
    skipped_years: list[dict[str, str]] = []
    for folder in iter_year_folders(cdc_root):
        try:
            years_data.append(load_year(folder))
        except FileNotFoundError as exc:
            skipped_years.append({"folder": folder.name, "reason": str(exc)})
    all_records = [record for year_data in years_data for record in year_data["records"]]
    girata_missing_second: list[dict[str, str | int]] = []
    for rec in all_records:
        cat_name = (rec.get("category_name") or "").upper()
        if "GIRATA.CONTO/CONTO" in cat_name or "GIRATA CONTO/CONTO" in cat_name:
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
                if "GIRATA.CONTO/CONTO" in (r.get("category_name") or "").upper()
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
        default=Path("data/unified_legacy_import.json"),
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
