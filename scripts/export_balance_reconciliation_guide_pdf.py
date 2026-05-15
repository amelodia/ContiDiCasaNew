#!/usr/bin/env python3
"""
Genera un PDF di appunti: saldo ibrido vs banca, scostamenti, strumento diagnostico proposto.

Uso:
  python3 scripts/export_balance_reconciliation_guide_pdf.py
  python3 scripts/export_balance_reconciliation_guide_pdf.py -o /percorso/documento.pdf
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pdf_safe_text(value: object) -> str:
    """Allinea a main_app._pdf_safe_text: Helvetica core ~ Latin-1."""
    s = str(value if value is not None else "")
    s = (
        s.replace("€", "EUR")
        .replace("–", "-")
        .replace("—", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
    )
    try:
        s.encode("latin-1")
    except UnicodeEncodeError:
        s = s.encode("latin-1", errors="replace").decode("latin-1")
    return s


def _paragraphs() -> list[str]:
    """Blocchi di testo con righe gia' corte per multi_cell."""
    return [
        "Conti di casa - Appunti su scarto saldo ibrido vs banca e strumento diagnostico proposto",
        f"Data generazione: {date.today().isoformat()}",
        "",
        "1. Modello del saldo assoluto (ibrido) nell'app desktop",
        "Il footer Saldi non e' la somma diretta di tutti i movimenti. Vale: saldo ibrido = valore memorizzato da "
        "legacy_saldi (foto *sld.aco nel bucket di riferimento, mappato per codice conto) + effetto delle sole righe "
        "create in app (+app) + compensazione annulli import (raw_record annullati) + correzioni su righe import "
        "ancora attive ma diverse dal blocco .dat (+edit), con eccezione gemelli import (twin) sostituita dal replay.",
        "",
        "2. Identita' algebrica sullo scarto (esempio CC.PP.TT)",
        "Sia L il *sld* in DB per il conto, M la somma dei correttivi (+app + annulli + edit), B il saldo banca ritenuto "
        "corretto oggi. In app: ibrido = L + M. La banca implica movimento netto reale (B - L). Se M supera (B - L) "
        "di S euro, allora ibrido supera B della stessa cifra S. Es.: L=2930.10, M=1889.22, ibrido=4819.32, B=4789.36 "
        "=> (B-L)=1859.26, M - (B-L) = 29.96 EUR = ibrido - B.",
        "",
        "3. Due sole famiglie di causa (indipendenti dalla verifica PDF)",
        "(A) Baseline *sld* per quel conto disallineata rispetto al saldo 'vero' alla stessa ancoraggio di import.",
        "(B) La pipeline dei correttivi somma S euro in piu' rispetto al flusso bancario reale condizionato a quella "
        "baseline (doppio conteggio, annullo che compensa un movimento mai entrato nel *sld*, ecc.).",
        "La verifica estratto PDF confronta saldo estratto + non verificate con lo stesso ibrido: non ricalcola *sld* ne' "
        "i correttivi. Quadrare la verifica non implica che l'ibrido coincida con la banca se il modello *sld*+patch e' "
        "sfasato.",
        "",
        "4. Aggiustamenti possibili",
        "Correzione rapida (solo numeri in footer): diminuire L per il conto di S (es. delta legacy -29.96 EUR) con lo "
        "script bump_legacy_saldo_one_account.py, con app chiusa - accettabile solo se si attributisce l'errore alla "
        "foto iniziale e non a un movimento errato.",
        "Correzione causale: individuare la/e registrazione/i o annulli che spiegano S confrontando contributi annulli e "
        "+app sul conto (audit manuale o elenchi da tool dedicato).",
        "",
        "5. Strumento diagnostico proposto (non ancora implementato come modulo unico)",
        "Un comando tipo: python3 scripts/...py --account-code 6 --bank-balance 4789,36 [--enc ...] [--key ...] che:",
        "- legge il DB cifrato e NON modifica nulla;",
        "- stampa saldo ibrido della colonna, saldo banca immesso, scarto ibrido-banca;",
        "- stampa la scomposizione L, +app, +annulli, +edit per quel solo conto;",
        "- indica esplicitamente il delta da applicare a legacy_saldi per annullare lo scarto senza toccare movimenti "
        "(opposto dello scarto sull'ibrido);",
        "- opzionale: elenco ordinato righe annullate import con effetto sulla colonna; elenco righe +app con effetto;",
        "Cosi' si ha in un colpo: obiettivo numerico, leva 'bump' esplicita, e materiale per audit se si rifiuta il bump.",
        "",
        "6. Cosa lo strumento NON farebbe",
        "Non sostituisce la verifica PDF. Non corregge automaticamente il DB. Non identifica da solo la 'causa morale' "
        "se S e' combinazione di piu' voci - resta l'interpretazione su annulli vs doppi movimenti.",
        "",
        "7. Flusso d'uso suggerito",
        "Chiudere l'app; eseguire il rapporto; leggere scarto e delta *sld* implicito; decidere bump vs ricerca riga; "
        "se bump, usare bump_legacy_saldo_one_account con stesso delta indicato dal rapporto.",
        "",
        "8. Appendice: rischi noti nella sola procedura di verifica conto corrente (PDF)",
        "Non risolvono i S EUR dell'ibrido se i movimenti sono gia' corretti, ma possono confondere il riepilogo:",
        "- Riepilogo che include per supplemento righe contate in sum_unverified ma con reg_n < ** fuori scope in "
        "ricerca abbinamenti => righe non verificabili in sessione ma presenti nella somma.",
        "- _ver_all_verified con scope di cutoff diverso dal riepilogo => messaggio 'completamente verificato' incoerente.",
        "- 'Riavvia ricerca' che auto-verifica un unico candidato senza vincolo PDF se la coda e' vuota => rischio "
        "asterisco sulla riga sbagliata a parita' importo.",
        "- Saldo estratto letto come stringa con Decimal() senza normalize_euro_input in alcuni percorsi.",
        "- Estrazione PDF: filtro data su coda, euristica segno/saldo finale - se errati, coda o saldo proposto non "
        "coincidono con il foglio cartaceo.",
        "",
        "Fine documento.",
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description="Esporta guida PDF saldo ibrido / banca")
    ap.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "documentazione_scarto_saldo_ibrido_banca.pdf",
        help="Percorso file PDF in uscita",
    )
    args = ap.parse_args()

    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError:
        print("Installare fpdf2: python3 -m pip install -r requirements.txt", flush=True)
        return 2

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 10)

    w = pdf.w - pdf.l_margin - pdf.r_margin
    for block in _paragraphs():
        t = _pdf_safe_text(block)
        if not t.strip():
            pdf.ln(4)
            continue
        # Titolo prima riga in grassetto se inizia con numero sezione
        if len(t) > 2 and t[0].isdigit() and t[1] in ". ":
            pdf.set_font("Helvetica", "B", 11)
            pdf.multi_cell(w, 5.5, t)
            pdf.set_font("Helvetica", "", 10)
        else:
            pdf.multi_cell(w, 5.5, t)
        pdf.ln(1)

    out = args.output.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    print(f"Scritto: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
