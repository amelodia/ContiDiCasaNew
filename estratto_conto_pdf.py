"""
Estrazione movimenti da estratto conto in PDF (conto corrente o carta di credito, testo estraibile).

Usa righe con data operazione (contabile); unisce le righe di continuazione senza data iniziale.
Segno dell'importo: euristica sulla causale (entrate/uscite tipiche di estratti italiani).

Il modulo **non** è addestrabile con ML: usa regole e regex. Per adattare un nuovo istituto:
  - verificare che il PDF contenga testo selezionabile (non solo immagine);
  - impostare la variabile d'ambiente ``ESTRATTO_PDF_DEBUG=1`` e rileggere il PDF dalla Verifica: vengono creati
    file ``<nomefile>_pypdf_estratto_<modalità>.txt`` (accanto al PDF, o in ``/tmp`` se la cartella non è scrivibile);
    anche con estrazione vuota si ottiene un file segnaposto. Controllare il terminale: viene stampato il percorso usato.
  - eventuali estensioni si fanno aggiungendo normalizzazioni o regex in questo file.

Lettura diversificata: preambolo ignorato fino alla prima riga che sembra un movimento; date gg-mm-aa
o gg.mm.aa normalizzate a barre; righe spezzate; secondo passaggio layout; terzo passaggio unione pagine.

Alcuni PDF (es. estratti a colonne) espongono il testo con **uno spazio tra ogni carattere**; in quel caso
si collassano gli spazi sulla riga prima del riconoscimento. Le date possono comparire **attaccate**
(``05/01/202605/01/2026``); l'importo in colonna entrate può avere il simbolo **€** subito dopo le cifre.

**Estratti BCC (Roma):** se nella **parte iniziale** del testo (primi ~120.000 caratteri) compare l'intestazione
«BCC ROMA» (anche **senza spazio** tra BCC e ROMA, o con ROMA attaccata a «Banca» come ``BCC ROMABanca`` nel PDF),
si applica il parser dedicato: dopo «DOTAZIONE INIZIALE» o «SALDO INIZIALE» due date ``gg/mm/aa`` (anche **attaccate**
``gg/mm/aagg/mm/aa``; si usa solo la **prima** come data
operazione), due importi colonna **MOV.DARE** / **MOV.AVERE** (DARE → negativo, AVERE → positivo). Se nel testo c'è
**un solo** importo (l'altra colonna a zero spesso omessa), si assume **MOV.AVERE** (entrata) salvo etichette colonna
visibili prima della cifra (``MOV.DARE`` / ``MOV.AVERE``) e salvo causali (prelievo, addebito, commissioni…). Per i
**bonifici** con un solo importo: ``a/in favore di`` → uscita (DARE); ``a vs favore`` / ``SEPA DA`` / ``a vostro favore``
→ entrata (AVERE). La **nota** è il testo dopo gli importi sulla riga del
movimento, più le righe successive **fino** a quando non compare una nuova riga che **inizia** con la **doppia data**
(contabile e valuta, con o senza spazio, anche ``gg/mm/aagg/mm/aa``); le date che compaiono solo dentro la nota
restano parte della nota. Una riga con **una** data ``gg/mm/aa`` e almeno ``**``
prima dell'importo indica il **saldo finale** (la data può essere attaccata a lettere, es. ``B2C27/02/26``); il blocco può
stare sulla **stessa riga** dell'ultimo movimento; il resto del documento viene ignorato.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NamedTuple


def _expand_yy_to_yyyy(dd_mm_yy: str) -> str:
    """Normalizza gg/mm/(aa|aaaa) in gg/mm/aaaa."""
    parts = dd_mm_yy.strip().split("/")
    if len(parts) != 3:
        return dd_mm_yy
    d, m, y = parts
    if len(y) == 4 and y.isdigit():
        return f"{d}/{m}/{y}"
    if len(y) == 2 and y.isdigit():
        yi = int(y)
        full = 2000 + yi if yi <= 99 else int(y)
        y = str(full)
    return f"{d}/{m}/{y}"


_AMT_RE = re.compile(r"^((?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})\s*€?$")

# Anno a 4 cifre prima di 2: evita che in ``05/01/202605/01/2026`` il secondo blocco data
# mangi ``20`` come anno a 2 cifre lasciando ``2699,93`` come importo.
_DATE_Y = r"\d{2}/\d{2}/(?:\d{4}|\d{2})"
_AMT_CORE = r"(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"


def _sanitize_closing_line_for_amount_scan(s: str) -> str:
    """
    Evita che l'anno (es. ``/2026``) sia attaccato all'importo (``2026310,36``), interpretato come migliaia.

    In alcuni PDF la riga di saldo appare come ``... 31/03/2026310,36 €`` senza spazio tra data e importo;
    il regex importo italiano può allora leggere ``2.026.310,36`` o simile.
    """
    t = s
    # Anno su 4 cifre subito seguito da una cifra (importo incollato alla data)
    t = re.sub(r"(/20\d{2})(?=\d)", r"\1 ", t)
    t = re.sub(r"(/19\d{2})(?=\d)", r"\1 ", t)
    t = re.sub(r"(\.20\d{2})(?=\d)", r"\1 ", t)
    t = re.sub(r"(\.19\d{2})(?=\d)", r"\1 ", t)
    # Stesso problema senza slash davanti (testo spezzato o collassato male)
    t = re.sub(r"(?<![0-9./])(20\d{2})(?=\d{3},\d{2}\b)", r"\1 ", t)
    t = re.sub(r"(?<![0-9./])(19\d{2})(?=\d{3},\d{2}\b)", r"\1 ", t)
    # Date complete → spazi (dopo le separazioni sopra)
    t = re.sub(r"\b\d{2}/\d{2}/\d{4}\b", " ", t)
    t = re.sub(r"\b\d{2}/\d{2}/\d{2}\b", " ", t)
    t = re.sub(r"\b\d{2}\.\d{2}\.\d{4}\b", " ", t)
    return t


# Due date (operazione + valuta) poi importo e causale (spazi anche nulli tra le due date)
_RE_TWO_DATE = re.compile(
    "^(" + _DATE_Y + r")\s*(" + _DATE_Y + r")\s+(" + _AMT_CORE + r")\s*€?\s+(.*)$"
)
# Due date attaccate (dopo collasso spazi verticali): 05/01/202605/01/2026
_RE_TWO_DATE_COMPACT = re.compile(
    "^(" + _DATE_Y + ")(" + _DATE_Y + ")(" + _AMT_CORE + r")\s*€?(.*)$"
)
# Una sola data poi importo e causale
_RE_ONE_DATE = re.compile(
    "^(" + _DATE_Y + r")\s+(" + _AMT_CORE + r")\s*€?\s+(.*)$"
)
# Una data attaccata all'importo: 05/01/202699,93€...
_RE_ONE_DATE_COMPACT = re.compile("^(" + _DATE_Y + ")(" + _AMT_CORE + r")\s*€?(.*)$")

# Date con separatore - o . (comuni in estratti non Poste)
_RE_DATE_SEP = re.compile(r"\b(\d{2})[-.](\d{2})[-.](\d{2,4})\b")


def _parse_it_amount(s: str) -> Decimal | None:
    """Accetta importo italiano opz. con € finale (es. ``99,93€``)."""
    s = (s or "").strip()
    if not s:
        return None
    m = _AMT_RE.match(s)
    if not m:
        return None
    raw = m.group(1)
    try:
        return Decimal(raw.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _normalize_pdf_line(s: str) -> str:
    """Collassa spazi, tab, NBSP e altri spazi Unicode tipici dell'estrazione PDF."""
    t = (s or "").replace("\xa0", " ").replace("\u2009", " ").replace("\u202f", " ")
    t = t.replace("\t", " ")
    return " ".join(t.split()).strip()


def _line_looks_shattered(line: str) -> bool:
    """
    True se il PDF ha estratto il testo con uno spazio tra quasi ogni carattere (lettura per colonne).
    """
    s2 = line.replace("\n", " ").strip()
    if len(s2) < 14:
        return False
    nsp = sum(1 for c in s2 if c.isspace())
    if nsp == 0:
        return False
    if nsp / len(s2) < 0.22:
        return False
    nd = sum(1 for c in s2 if c.isdigit() or c in "/,€.-")
    if nd < min(10, max(6, len(s2) // 5)):
        return False
    return True


def _collapse_shattered_line(line: str) -> str:
    """Rimuove tutti gli spazi e a capo: ``0 5 / 0 1 / ...`` -> ``05/01/...``."""
    return re.sub(r"\s+", "", (line or "").replace("\n", " "))


def _compact_for_keyword(s: str) -> str:
    """Rimuove spazi per confronti su causali/intestazioni spezzate."""
    return re.sub(r"\s+", "", (s or "").upper())


def _normalize_date_separators(line: str) -> str:
    """Converte 12-01-26 / 12.01.2026 in 12/01/26 per allinearsi ai pattern esistenti."""

    def _sub(m: re.Match[str]) -> str:
        a, b, c = m.group(1), m.group(2), m.group(3)
        return f"{a}/{b}/{c}"

    return _RE_DATE_SEP.sub(_sub, line)


def _merge_broken_statement_lines(lines: list[str]) -> list[str]:
    """
    Unisce righe spezzate dall'estrattore (es. solo date su una riga, importo+causale sulla successiva).
    """
    out: list[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        # Riga che contiene solo le due date contabile/valuta
        if re.fullmatch(rf"{_DATE_Y}\s+{_DATE_Y}", cur) and nxt:
            out.append(_normalize_pdf_line(cur + " " + nxt))
            i += 2
            continue
        # Una sola data isolata (senza importo sulla stessa riga)
        if re.fullmatch(_DATE_Y, cur) and nxt:
            rest_first = nxt.lstrip()
            parts_n = rest_first.split()
            if parts_n and _parse_it_amount(parts_n[0]):
                out.append(_normalize_pdf_line(cur + " " + nxt))
                i += 2
                continue
        # ``SALDO`` / ``DOTAZIONE`` e capo, poi ``INIZIALE`` attaccato alle date (PDF spezza l'intestazione).
        cst, nst = cur.strip(), nxt.strip()
        if nst and re.match(r"(?i)^iniziale", nst):
            if re.fullmatch(r"(?i)saldo\.?", cst) or re.fullmatch(r"(?i)dotazione\.?", cst):
                out.append(_normalize_pdf_line(f"{cst} {nst}"))
                i += 2
                continue
            if re.search(r"(?i)\b(?:saldo|dotazione)\.?$", cst):
                out.append(_normalize_pdf_line(f"{cst} {nst}"))
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


def _prepare_statement_lines(text: str) -> list[str]:
    raw: list[str] = []
    for x in text.splitlines():
        x = _normalize_pdf_line(x)
        if not x or x.startswith("--"):
            continue
        x1 = x.replace("\n", " ")
        if _line_looks_shattered(x1):
            x = _collapse_shattered_line(x1)
        raw.append(x)
    merged = _merge_broken_statement_lines(raw)
    return [_normalize_date_separators(L) for L in merged]


def _bcc_note_bonifico_a_favore_di_terzi(desc: str) -> bool:
    """
    Bonifico disposto a favore di un beneficiario (uscita, colonna DARE): «a/in favore di …».
    Non confondere con «a vs favore» (entrata sul proprio conto).
    """
    u = " ".join((desc or "").split()).upper()
    ck = _compact_for_keyword(desc)
    if "BONIFICO" not in u:
        return False
    if "AFAVOREDI" in ck or "INFAVOREDI" in ck:
        return True
    if "A FAVORE DI" in u or "IN FAVORE DI" in u:
        return True
    return False


def _bcc_note_bonifico_in_entrata_favore(desc: str) -> bool:
    """
    Bonifico in entrata (AVERE): accredito SEPA, «a vs favore» / «a/vs favore» (anche con # davanti), ecc.
    """
    u = " ".join((desc or "").split()).upper()
    ck = _compact_for_keyword(desc)
    if "BONIFICO" not in u:
        return False
    if "BONIFICO SEPA DA" in u or "BONIFICOSEPADA" in ck:
        return True
    if "AVSFAVORE" in ck:
        return True
    if "VSFAVORE" in ck and "FAVOREDI" not in ck:
        return True
    if "VOSTRO FAVORE" in u or "A VOSTRO FAVORE" in u:
        return True
    return False


def _is_credit_description(desc: str) -> bool:
    """Entrate tipiche (conto o carta); il resto è trattato come uscita rispetto al saldo."""
    u = " ".join(desc.split()).upper()
    ck = _compact_for_keyword(desc)
    if "BONIFICO SEPA DA" in u or "BONIFICOSEPADA" in ck:
        return True
    if _bcc_note_bonifico_in_entrata_favore(desc):
        return True
    if _bcc_note_bonifico_a_favore_di_terzi(desc):
        return False
    if (
        "STIPENDIO" in u
        or "PENSIONE" in u
        or "EMOLUMENT" in u
        or "ACCREDITAMENTO" in u
        or "ACCREDITO" in u
        or "ACCREDITO" in ck
    ):
        return True
    if "CASHBACK" in u:
        return True
    if "VOSTRO FAVORE" in u or "A VOSTRO FAVORE" in u:
        return True
    if "ENTRATA" in u and "USCITA" not in u[:20]:
        return True
    if "RIMBORSO" in u or "STORNO" in u:
        return True
    return False


def _bcc_note_suggests_dare_outflow(note: str) -> bool:
    """Movimenti in uscita tipici (colonna DARE) quando l'estratto espone un solo importo in chiaro."""
    if not (note or "").strip():
        return False
    if _bcc_note_bonifico_in_entrata_favore(note):
        return False
    if _bcc_note_bonifico_a_favore_di_terzi(note):
        return True
    if _is_credit_description(note):
        return False
    u = " ".join(note.split()).upper()
    # Emolumenti / stipendi: colonna AVERE (entrata), anche se la nota contiene «disposizione» ecc.
    if "EMOLUMENT" in u:
        return False
    c = _compact_for_keyword(note)
    needles = (
        "PRELIEVO",
        "PAGAMENTO",
        "ADDEBITO",
        "ADEBITO",
        "COMMISSION",
        "COMMISSIONI",
        "SPESE",
        "BOLLO",
        "IMPOSTA",
        "IMPOSTE",
        "CANONE",
        "PAGAMENT",
        "CARTA",
        "DISPOSIZION",
        "ORDIN",
        "MAV ",
        "RID ",
        "CBILL",
        "PAGO PA",
        "PAGOPA",
    )
    if any(x in u for x in needles):
        return True
    if any(x.replace(" ", "") in c for x in ("ADDEBITO", "ADEBITO", "COMMISSIONI", "DISPOSIZIONE")):
        return True
    return False


def _skip_description(desc: str) -> bool:
    u = " ".join(desc.split()).upper()
    c = _compact_for_keyword(desc)
    if "SALDOINIZIALE" in c or "SALDO INIZIALE" in u or "SALDO INIZ." in u:
        return True
    if "TOTALUSCITE" in c or "TOTALENTRATE" in c or "TOTALE USCITE" in u or "TOTALE ENTRATE" in u:
        return True
    if "TOTALE AD" in u and "BIT" in u:
        return True
    if "TOTALE ACC" in u:
        return True
    if "SALDOFINALE" in c or "SALDO FINALE" in u:
        return True
    return False


def _line_is_summary_not_movement(line: str) -> bool:
    """Righe di riepilogo estratto (saldo iniziale, totali) da non trattare come movimenti."""
    u = " ".join(line.split()).upper()
    c = _compact_for_keyword(line)
    if "SALDOINIZIALE" in c or "SALDO INIZIALE" in u or "SALDO INIZ." in u:
        return True
    if "SALDO ALLA DATA DEL" in u and "INIZ" in u:
        return True
    if "SALDO CONTABILE" in u or "SALDOCONTABILE" in c:
        return True
    if "SALDO DISPONIBILE" in u or "SALDISPONIBILE" in c:
        return True
    if "TOTALENTRATE" in c or "TOTALUSCITE" in c or "TOTALE ENTRATE" in u or "TOTALE USCITE" in u:
        return True
    if "TOTALE AD" in u and "BIT" in u:
        return True
    if "TOTALE ACC" in u:
        return True
    return False


def _line_is_probable_table_header(line: str, *, max_note_len: int) -> bool:
    """Intestazione tabella (nomi colonna) senza movimento reale."""
    if _parse_movement_line(line, max_note_len=max_note_len):
        return False
    if not re.match(r"^\D", line) and not _line_looks_shattered(line.replace("\n", " ")):
        return False
    u = " ".join(line.split()).upper()
    ck = _compact_for_keyword(line)
    # Stessa riga: titoli colonna + ``SALDO INIZIALE`` / movimenti (PDF senza a capo; importi attaccati al testo).
    if "SALDO INIZIALE" in u or "DOTAZIONE INIZIALE" in u or "SALDOINIZIALE" in ck or "DOTAZIONEINIZIALE" in ck:
        return False
    if re.search(r"\d{2}/\d{2}/\d{2}\d{2}/\d{2}/\d{2}", "".join(line.split())):
        return False
    keys = ("DATA", "OPERAZION", "VALUT", "IMPORT", "DESCR", "CAUSAL", "MOVIM", "DARE", "AVERE")
    if sum(1 for k in keys if k in u or k in ck) < 2:
        return False
    parts = line.split()
    if any(_parse_it_amount(p) is not None for p in parts):
        return False
    return True


def _try_parse_saldo_finale_amount(line: str) -> Decimal | None:
    """Importo di chiusura sulla riga: cerca etichette tipo saldo finale / contabile / disponibile (anche compatte)."""
    x = line.replace("\n", " ")
    core = _collapse_shattered_line(x) if _line_looks_shattered(x) else x
    t = " ".join(core.split())
    u = t.upper()

    def _last_amt_in(s: str) -> Decimal | None:
        s2 = _sanitize_closing_line_for_amount_scan(s)
        last: Decimal | None = None
        for m in re.finditer(rf"({_AMT_CORE})\s*€?", s2):
            parsed = _parse_it_amount(m.group(1))
            if parsed is not None:
                last = parsed
        return last

    for kw in ("SALDO DISPONIBILE", "SALDO CONTABILE", "SALDO FINALE", "SALDO UTILE"):
        idx = u.find(kw)
        if idx >= 0:
            got = _last_amt_in(t[idx + len(kw) :])
            if got is not None:
                return got

    ck = _compact_for_keyword(t).upper()
    if "SALDOFINALE" in ck or "SALDOCONTABILE" in ck or "SALDISPONIBILE" in ck:
        idx = u.find("SALDO FINALE")
        if idx >= 0:
            got = _last_amt_in(t[idx + len("SALDO FINALE") :])
            if got is not None:
                return got
        idx2 = u.find("SALDO CONTABILE")
        if idx2 >= 0:
            got = _last_amt_in(t[idx2 + len("SALDO CONTABILE") :])
            if got is not None:
                return got
        idx3 = u.find("SALDO DISPONIBILE")
        if idx3 >= 0:
            got = _last_amt_in(t[idx3 + len("SALDO DISPONIBILE") :])
            if got is not None:
                return got
        return _last_amt_in(t)
    return None


def _note_looks_like_summary_row(note: str) -> bool:
    u = " ".join((note or "").split()).upper()
    c = _compact_for_keyword(note or "")
    if "SALDOINIZIALE" in c or "SALDO INIZIALE" in u or "TOTALE ENTRATE" in u or "TOTALE USCITE" in u:
        return True
    if "SALDOFINALE" in c or "SALDO FINALE" in u:
        return True
    if "SALDO CONTABILE" in u or "SALDOCONTABILE" in c:
        return True
    if "SALDO DISPONIBILE" in u or "SALDISPONIBILE" in c:
        return True
    return False


class EstrattoContoPdfExtract(NamedTuple):
    movements: list[dict[str, object]]
    closing_balance: Decimal | None


# --- BCC Roma: riconoscimento da intestazione; dotazione/saldo iniziale, DARE/AVERE, saldo data + asterischi ---

_RE_BCC_LINE_START_TWO_DATES = re.compile(
    rf"^(\d{{2}}/\d{{2}}/(?:\d{{4}}|\d{{2}}))\s+(\d{{2}}/\d{{2}}/(?:\d{{4}}|\d{{2}}))\b(.*)$"
)
# Due date attaccate con anno a **2** cifre (16 caratteri): evita ``02/02/2602`` come /aaaa errato.
_RE_BCC_LINE_START_TWO_DATES_COMPACT_YY = re.compile(r"^(\d{2}/\d{2}/\d{2})(\d{2}/\d{2}/\d{2})(.*)$")
# Due date attaccate con anno a 4 o 2 cifre: 05/01/202605/01/2026…
_RE_BCC_LINE_START_TWO_DATES_COMPACT = re.compile(
    rf"^(\d{{2}}/\d{{2}}/(?:\d{{4}}|\d{{2}}))(\d{{2}}/\d{{2}}/(?:\d{{4}}|\d{{2}}))(.*)$"
)
# Prossimo movimento sulla stessa riga: doppia data ``gg/mm/aagg/mm/aa`` (anche attaccata a cifre nella nota).
_BCC_INLINE_DD = r"\d{2}/\d{2}/\d{2}\d{2}/\d{2}/\d{2}"
_RE_BCC_INLINE_NEXT_DOUBLE_DATE = re.compile(
    rf"(?:(?<![0-9,/])({_BCC_INLINE_DD})|(?<=\d)({_BCC_INLINE_DD}))"
)


def _bcc_match_opening_two_dates(cand: str) -> re.Match | None:
    """All'inizio della riga (dopo eventuale prefisso già tolto): coppia data operazione + data valuta."""
    if not (cand or "").strip():
        return None
    s = cand.strip()
    for rx in (
        _RE_BCC_LINE_START_TWO_DATES,
        _RE_BCC_LINE_START_TWO_DATES_COMPACT_YY,
        _RE_BCC_LINE_START_TWO_DATES_COMPACT,
    ):
        m = rx.match(s)
        if m:
            return m
    return None


_BCC_HEADER_SCAN_CHARS = 120_000


def _looks_like_bcc_estratto(text: str) -> bool:
    """
    True se l'estratto è BCC Roma: in testata compare «BCC ROMA» (spazi opzionali tra BCC e ROMA; ROMA può essere
    attaccata alla parola successiva, es. «BCC ROMABanca», tipico dell'estrazione PDF senza spazio dopo ROMA).
    """
    head = (text or "")[:_BCC_HEADER_SCAN_CHARS]
    if re.search(r"(?i)BCC\s*ROMA", head):
        return True
    return "BCCROMA" in _compact_for_keyword(head)


def _bcc_line_starts_informazioni_clientela(line: str) -> bool:
    """Blocco informativo a fine estratto (non parte della nota dell'ultimo movimento)."""
    c = _compact_for_keyword((line or "").strip())
    return c.startswith("INFORMAZIONIALLACLIENTELA")


def _bcc_line_has_opening_balance_keyword(line: str) -> bool:
    """Riga di apertura movimenti (dotazione o saldo iniziale): non va scartata come solo riepilogo."""
    u = " ".join((line or "").split()).upper()
    c = _compact_for_keyword(line or "").upper()
    if "DOTAZIONEINIZIALE" in c or "DOTAZIONE INIZIALE" in u:
        return True
    if "SALDOINIZIALE" in c or "SALDO INIZIALE" in u or "SALDO INIZ." in u:
        return True
    return False


def _bcc_prepare_line_for_movement_parse(line: str) -> str:
    s = (line or "").strip()
    m = re.search(r"(?i)(?:DOTAZIONE|SALDO)\s+INIZIALE(?:\.\s*)?\s*(.*)$", s)
    if m:
        return m.group(1).strip()
    # Riga che inizia con INIZIALE subito seguito dalle date (capo tra «SALDO» e «INIZIALE» non ancora unito).
    m2 = re.match(r"(?i)^iniziale(?:\.\s*)?\s*(.*)$", s)
    if m2:
        rest = (m2.group(1) or "").strip()
        if rest[:1].isdigit():
            return rest
    return s


def _bcc_parse_saldo_finale_from_line(line: str) -> Decimal | None:
    # Non ``\\b`` prima della data: tra lettera e cifra (es. ``B2C27/02/26``) non c'è word boundary in Python.
    m = re.search(
        rf"(?<![0-9/])({_DATE_Y})\s*\*{{2,}}.*?(?<![0-9,])(?P<am>{_AMT_CORE})(?!\d)",
        (line or "").strip(),
        re.S,
    )
    if not m:
        return None
    return _parse_it_amount(m.group("am"))


_RE_BCC_SALDO_STARS_BLOCK = re.compile(
    rf"(?<![0-9/])({_DATE_Y})\s*\*{{2,}}.*?(?<![0-9,])({_AMT_CORE})(?!\d)",
    re.S,
)


def _bcc_pop_trailing_saldo_finale_suffix(line: str) -> tuple[str, Decimal | None]:
    """
    Rimuove dalla riga il **ultimo** suffisso plausibile ``data`` + ``**`` + importo (+ opz. etichetta saldo),
    tipico del PDF BCC quando saldo e ultimo movimento sono sulla stessa riga senza a capo.
    """
    s = (line or "").rstrip()
    if not s:
        return s, None
    best_start: int | None = None
    best_amt: Decimal | None = None
    for m in _RE_BCC_SALDO_STARS_BLOCK.finditer(s):
        amt = _parse_it_amount(m.group(2))
        if amt is None:
            continue
        tail = s[m.end() :].strip()
        if tail:
            tu = tail.upper()
            ck = _compact_for_keyword(tail)
            if (
                "SALDO FINALE" not in tu
                and "SALDOFINALE" not in ck
                and "SALDO CONTABILE" not in tu
                and "SALDOCONTABILE" not in ck
                and "SALDO DISPONIBILE" not in tu
                and "SALDISPONIBILE" not in ck
            ):
                continue
        # Con ``tail`` vuoto accettiamo ``data + ** + importo`` a fine riga (senza etichetta).
        best_start = m.start()
        best_amt = amt
    if best_start is None:
        return s, None
    return s[:best_start].rstrip(), best_amt


def _bcc_inline_double_date_followed_by_stars_not_movement(frag: str) -> bool:
    """True se ``frag`` inizia con ``gg/mm/aagg/mm/aa`` seguito da asterischi (blocco saldo, non nuovo movimento)."""
    t = (frag or "").strip()
    if len(t) < 16:
        return False
    if not re.match(rf"^{_BCC_INLINE_DD}", t):
        return False
    rest = t[16:].lstrip()
    return bool(rest.startswith("*"))


def _bcc_single_amount_column_label_hint(before_first_amount: str) -> str | None:
    """
    Nuovi PDF BCC: etichette colonna prima dell'importo (``MOV.DARE`` / ``MOV.AVERE`` senza spazi/significant).
    Se compaiono entrambe prima della cifra, nessun suggerimento (due importi attesi altrove).
    """
    h = _compact_for_keyword(before_first_amount or "").upper().replace(".", "").replace(",", "")
    if not h:
        return None
    i_d = h.find("MOVDARE")
    i_a = h.find("MOVAVERE")
    if i_d >= 0 and i_a >= 0:
        return None
    if i_d >= 0:
        return "dare"
    if i_a >= 0:
        return "avere"
    return None


def _bcc_index_first_movement_line(prepared: list[str], *, max_note_len: int) -> int | None:
    """Indice della prima riga che produce un movimento BCC, o None."""
    for i, raw in enumerate(prepared):
        raw_s = raw.strip()
        if not raw_s:
            continue
        if re.match(r"^Pag\.", raw_s, re.I):
            continue
        if _line_is_probable_table_header(raw, max_note_len=max_note_len):
            continue
        if _line_is_summary_not_movement(raw) and not _bcc_line_has_opening_balance_keyword(raw):
            continue
        cand = _bcc_prepare_line_for_movement_parse(raw)
        m = _bcc_match_opening_two_dates(cand)
        if not m:
            continue
        d1, d2, tail = m.group(1), m.group(2), m.group(3)
        mv, _rest = _bcc_build_movement_from_tail(d1, d2, tail, max_note_len=max_note_len)
        if mv:
            return i
    return None


def _bcc_build_movement_from_tail(
    d_oper: str,
    _d_valuta: str,
    tail: str,
    *,
    max_note_len: int,
) -> tuple[dict[str, object] | None, str | None]:
    """
    Dopo le due date: MOV.DARE / MOV.AVERE; un solo importo → di norma MOV.AVERE salvo causale da uscita.
    Se sulla stessa riga segue un altro movimento (doppia data attaccata), il secondo elemento è il suffisso da riparsare.
    """
    tail = (tail or "").strip()
    if not tail:
        return None, None
    # Prossima doppia data sulla stessa riga (altro movimento). Escludi ``gg/mm/aagg/mm/aa`` + ``**`` (saldo PDF).
    m_next: re.Match[str] | None = None
    search_from = 0
    while True:
        cand_m = _RE_BCC_INLINE_NEXT_DOUBLE_DATE.search(tail, search_from)
        if not cand_m:
            break
        frag = tail[cand_m.start() :]
        if _bcc_inline_double_date_followed_by_stars_not_movement(frag):
            search_from = cand_m.start() + 1
            continue
        m_next = cand_m
        break
    chunk = tail[: m_next.start()] if m_next else tail
    rest_out = tail[m_next.start() :].strip() if m_next else None
    # Non usare \b dopo le centesimali: in PDF spesso ``136,04PENSIONE`` senza spazio.
    ms = list(re.finditer(rf"(?<![0-9,])({_AMT_CORE})(?!\d)", chunk))
    if not ms:
        return None, rest_out
    first = _parse_it_amount(ms[0].group(1))
    first = first if first is not None else Decimal(0)
    dare = Decimal(0)
    avere = Decimal(0)
    end_note = ms[0].end()
    if len(ms) >= 2:
        dare = first
        av = _parse_it_amount(ms[1].group(1))
        avere = av if av is not None else Decimal(0)
        end_note = ms[1].end()
    note = chunk[end_note:].strip()[:max_note_len]
    if len(ms) >= 2:
        if dare and dare != 0:
            signed = -abs(dare)
        elif avere and avere != 0:
            signed = abs(avere)
        else:
            signed = Decimal(0)
    else:
        # Un solo importo: tipicamente MOV.AVERE (0,00 in DARE omesso); uscite riconoscibili → DARE.
        if first and first != 0:
            col_hint = _bcc_single_amount_column_label_hint(chunk[: ms[0].start()])
            if col_hint == "dare":
                signed = -abs(first)
            elif col_hint == "avere":
                signed = abs(first)
            elif _bcc_note_suggests_dare_outflow(note):
                signed = -abs(first)
            else:
                signed = abs(first)
        else:
            signed = Decimal(0)
    if signed == 0 and not note:
        return None, None
    booking = _expand_yy_to_yyyy(d_oper)
    return (
        {
            "booking": booking,
            "booking_date": booking,
            "amount": signed,
            "note": note,
        },
        rest_out,
    )


def _parse_statement_text_bcc(
    prepared: list[str], *, max_note_len: int
) -> tuple[list[dict[str, object]], Decimal | None]:
    """
    Parser estratti BCC Roma («BCC ROMA» in testata).

    Ogni movimento inizia in riga con la doppia data; la nota continua sulle righe seguenti fino al prossimo movimento
    (stessa riga che ricomincia con doppia data, event. dopo prefisso SALDO/DOTAZIONE INIZIALE sulla prima riga).
    """
    closing_balance: Decimal | None = None
    rows: list[dict[str, object]] = []

    bodies: list[str] = []
    saldo_suffix_amt: list[Decimal | None] = []
    for raw in prepared:
        body, cl_pop = _bcc_pop_trailing_saldo_finale_suffix(raw)
        bodies.append(body)
        saldo_suffix_amt.append(cl_pop)
        if cl_pop is not None:
            closing_balance = cl_pop

    # Il saldo finale (data + **) non va cercato prima del primo movimento: in testata compaiono righe
    # con data e asterischi che altrimenti imposterebbero trunc=0 e svuoterebbero ``work``.
    trunc = len(bodies)
    first_mi = _bcc_index_first_movement_line(bodies, max_note_len=max_note_len)
    if first_mi is not None:
        for i in range(first_mi + 1, len(bodies)):
            s_orig = prepared[i].strip()
            s_body = bodies[i].strip()
            if not s_orig:
                continue
            if saldo_suffix_amt[i] is not None and not s_body:
                closing_balance = saldo_suffix_amt[i]
                trunc = i
                break
            cl = _bcc_parse_saldo_finale_from_line(s_orig)
            if cl is not None:
                closing_balance = cl
                if not s_body:
                    trunc = i
                    break
    work = bodies[:trunc]

    for raw in work:
        raw_s = raw.strip()
        if not raw_s:
            continue
        if _bcc_line_starts_informazioni_clientela(raw):
            continue
        if re.match(r"^Pag\.", raw_s, re.I):
            continue
        if _line_is_probable_table_header(raw, max_note_len=max_note_len):
            continue
        if _line_is_summary_not_movement(raw) and not _bcc_line_has_opening_balance_keyword(raw):
            continue

        cand = _bcc_prepare_line_for_movement_parse(raw)
        # Continuazione nota (anche codici SDD numerici) attaccata alla doppia data del movimento successivo.
        if rows and cand:
            cs = cand.strip()
            m_embed = _RE_BCC_INLINE_NEXT_DOUBLE_DATE.search(cs)
            if m_embed and m_embed.start() > 0:
                pre = cs[: m_embed.start()].strip()
                if pre:
                    prev = rows[-1]
                    prev["note"] = (str(prev.get("note", "")) + " " + pre).strip()[:max_note_len]
                cand = cs[m_embed.start() :].strip()
        started_inline = False
        while cand:
            m = _bcc_match_opening_two_dates(cand)
            if not m:
                break
            d1, d2, tail = m.group(1), m.group(2), m.group(3)
            mv, rest = _bcc_build_movement_from_tail(d1, d2, tail, max_note_len=max_note_len)
            if not mv:
                break
            rows.append(mv)
            started_inline = True
            cand = (rest or "").strip()
        if started_inline:
            continue

        # Nota: righe senza doppia data iniziale restano parte del movimento precedente (fino al prossimo movimento).
        if rows:
            add = " ".join(raw.split())[:max_note_len]
            if add:
                prev = rows[-1]
                prev["note"] = (str(prev.get("note", "")) + " " + add).strip()[:max_note_len]

    rows = [r for r in rows if not _note_looks_like_summary_row(str(r.get("note", "")))]
    return rows, closing_balance


def _line_starts_like_new_movement(line: str, *, max_note_len: int) -> bool:
    """True se la riga sembra un nuovo movimento (anche se il parse completo fallisce)."""
    t = line.strip()
    if not t:
        return False
    x = t.replace("\n", " ")
    if _line_looks_shattered(x):
        t = _collapse_shattered_line(x)
    t = _normalize_date_separators(t)
    if _RE_TWO_DATE.match(t) or _RE_TWO_DATE_COMPACT.match(t):
        return True
    if _RE_ONE_DATE.match(t) or _RE_ONE_DATE_COMPACT.match(t):
        return True
    return False


def _should_append_continuation(line: str, *, max_note_len: int) -> bool:
    """Unisce righe successive alla nota (IBAN, riferimenti, testo spezzato) fino al prossimo movimento."""
    s = line.strip()
    if not s:
        return False
    if _parse_movement_line(s, max_note_len=max_note_len):
        return False
    if _line_starts_like_new_movement(s, max_note_len=max_note_len):
        return False
    lu = s.upper()
    c = _compact_for_keyword(s)
    if "SALDOFINALE" in c or "SALDOINIZIALE" in c or "SALDOCONTABILE" in c or "SALDISPONIBILE" in c:
        return False
    if "TOTALENTRATE" in c or "TOTALUSCITE" in c:
        return False
    if "TOTALE ENTRATE" in lu or "TOTALE USCITE" in lu or "SALDO FINALE" in lu or "SALDO INIZIALE" in lu:
        return False
    if "SALDO CONTABILE" in lu or "SALDO DISPONIBILE" in lu:
        return False
    if re.match(r"^Pag\.", s, re.I):
        return False
    if "POSTE.IT" in lu or ("PAG." in lu and "SEGUE" in lu):
        return False
    if re.match(r"^G\s+\d", s):
        return False
    return True


def _movement_row(
    d_oper: str,
    amt: Decimal,
    desc: str,
    *,
    max_note_len: int,
) -> dict[str, object]:
    desc = desc.strip()
    signed = amt if _is_credit_description(desc) else -amt
    note = " ".join(desc.split())[:max_note_len]
    booking_contabile = _expand_yy_to_yyyy(d_oper)
    return {
        "booking": booking_contabile,
        "booking_date": booking_contabile,
        "amount": signed,
        "note": note,
    }


def _parse_movement_line(line: str, *, max_note_len: int) -> dict[str, object] | None:
    """Interpreta una riga come movimento; None se non riconosciuta."""
    line = _normalize_pdf_line(line)
    x = line.replace("\n", " ")
    if _line_looks_shattered(x):
        line = _collapse_shattered_line(x)
    line = _normalize_date_separators(line)

    for regex in (_RE_TWO_DATE_COMPACT, _RE_TWO_DATE, _RE_ONE_DATE_COMPACT, _RE_ONE_DATE):
        m = regex.match(line)
        if not m:
            continue
        g = m.groups()
        if len(g) == 4:
            d1, _d2, ams, desc = g
        else:
            d1, ams, desc = g
        amt = _parse_it_amount(ams)
        if amt is None:
            continue
        if _skip_description(desc):
            continue
        return _movement_row(d1, amt, desc, max_note_len=max_note_len)

    return None


def _first_movement_line_index(prepared: list[str], *, max_note_len: int) -> int:
    """Indice della prima riga che interpretiamo come movimento (dopo preambolo / saldo iniziale)."""
    for i, line in enumerate(prepared):
        if _parse_movement_line(line, max_note_len=max_note_len) is not None:
            return i
    return 0


def _parse_statement_text(text: str, *, max_note_len: int) -> tuple[list[dict[str, object]], Decimal | None]:
    """Estrae movimenti e saldo finale da testo già letto dal PDF."""
    prepared = _prepare_statement_lines(text)
    joined = "\n".join(prepared)
    if _looks_like_bcc_estratto(joined):
        rows_bcc, cl_bcc = _parse_statement_text_bcc(prepared, max_note_len=max_note_len)
        if rows_bcc or cl_bcc is not None:
            return rows_bcc, cl_bcc

    closing_balance: Decimal | None = None

    for line in prepared:
        got = _try_parse_saldo_finale_amount(line)
        if got is not None:
            closing_balance = got

    start = _first_movement_line_index(prepared, max_note_len=max_note_len)
    rows: list[dict[str, object]] = []

    for line in prepared[start:]:
        if re.match(r"^Pag\.", line, re.I):
            continue
        if _line_is_summary_not_movement(line):
            continue
        uu = line.upper()
        ckln = _compact_for_keyword(line)
        if "SALDO FINALE" in uu or "SALDOFINALE" in ckln:
            continue
        if "SALDO CONTABILE" in uu or "SALDOCONTABILE" in ckln:
            continue
        if "SALDO DISPONIBILE" in uu or "SALDISPONIBILE" in ckln:
            continue
        if _line_is_probable_table_header(line, max_note_len=max_note_len):
            continue

        row = _parse_movement_line(line, max_note_len=max_note_len)
        if row is not None:
            rows.append(row)
            continue

        if rows and line and _should_append_continuation(line, max_note_len=max_note_len):
            prev = rows[-1]
            tail = str(prev.get("note", ""))
            xadd = line.replace("\n", " ")
            if _line_looks_shattered(xadd):
                add = _collapse_shattered_line(xadd)
            else:
                add = " ".join(line.split())
            if add:
                merged = (tail + " " + add).strip()[:max_note_len]
                prev["note"] = merged

    rows = [r for r in rows if not _note_looks_like_summary_row(str(r.get("note", "")))]
    return rows, closing_balance


def _extract_text_from_reader(reader: object, *, layout: bool, page_joiner: str) -> str:
    """``layout=True`` usa ``extraction_mode='layout'`` (pypdf ≥4) per colonne più allineate."""
    mode = "layout" if layout else "plain"
    chunks: list[str] = []
    for page in reader.pages:
        try:
            t = page.extract_text(extraction_mode=mode) or ""
        except TypeError:
            t = page.extract_text() or ""
        chunks.append(t)
    return page_joiner.join(chunks)


def _maybe_dump_debug_text(path: Path, label: str, text: str) -> None:
    if not os.environ.get("ESTRATTO_PDF_DEBUG", "").strip():
        return
    path = Path(path)
    cap = 800_000
    body = text if len(text) <= cap else text[:cap] + "\n\n[... troncato ...]"
    fname = f"{path.stem}_pypdf_estratto_{label}.txt"
    for out in (path.parent / fname, Path(tempfile.gettempdir()) / fname):
        try:
            out.write_text(body, encoding="utf-8", errors="replace")
            try:
                print(f"ESTRATTO_PDF_DEBUG: scritto {out.resolve()}", file=sys.stderr)
            except Exception:
                pass
            return
        except OSError:
            continue
    try:
        print(
            f"ESTRATTO_PDF_DEBUG: impossibile scrivere {fname} né accanto al PDF né in {tempfile.gettempdir()}",
            file=sys.stderr,
        )
    except Exception:
        pass


def extract_estratto_conto_movements_from_pdf(path: Path, *, max_note_len: int = 500) -> EstrattoContoPdfExtract:
    """
    Legge un PDF di estratto conto (banca o carta di credito): movimenti
    (data operazione, importi in formato italiano, causale) e, se presente in chiaro,
    l'importo del **saldo finale** indicato nell'estratto.

    Solleva ``ImportError`` se manca la libreria ``pypdf``.
    Solleva ``FileNotFoundError`` / ``ValueError`` se il file non è leggibile o non contiene testo utile.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ImportError(
            "Per leggere gli estratti PDF installa le dipendenze: python3 -m pip install -r requirements.txt "
            "(pacchetto pypdf)."
        ) from exc

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    reader = PdfReader(str(path))

    variants: list[tuple[str, bool, str]] = [
        ("plain", False, "\n"),
        ("layout", True, "\n"),
        ("plain_pages", False, "\n\n"),
        ("layout_pages", True, "\n\n"),
    ]

    rows: list[dict[str, object]] = []
    closing_balance: Decimal | None = None
    last_text = ""
    dbg = bool(os.environ.get("ESTRATTO_PDF_DEBUG", "").strip())

    for label, layout, joiner in variants:
        text = _extract_text_from_reader(reader, layout=layout, page_joiner=joiner)
        last_text = text
        if dbg:
            if text.strip():
                _maybe_dump_debug_text(path, label, text)
            else:
                _maybe_dump_debug_text(
                    path,
                    label,
                    f"[{label}] pypdf non ha estratto testo in questa modalità "
                    "(PDF solo immagine, protetto o pagine senza testo selezionabile).\n",
                )
        if not text.strip():
            continue
        rows, closing_balance = _parse_statement_text(text, max_note_len=max_note_len)
        if rows or closing_balance is not None:
            break

    if not rows and closing_balance is None and last_text.strip() and not dbg:
        _maybe_dump_debug_text(path, "last_failed", last_text)

    if not rows and closing_balance is None:
        raise ValueError(
            "Nessun movimento riconosciuto nel PDF (layout non supportato, testo non estraibile, "
            "oppure formato date/importi diverso da gg/mm/aa + importo italiano). "
            "Con ESTRATTO_PDF_DEBUG=1 e riprovare dalla Verifica: si creano file _pypdf_estratto_*.txt "
            "accanto al PDF o in /tmp, e sul terminale compare il percorso scritto."
        )
    return EstrattoContoPdfExtract(rows, closing_balance)
