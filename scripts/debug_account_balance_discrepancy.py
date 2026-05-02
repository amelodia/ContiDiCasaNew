#!/usr/bin/env python3
"""
Diagnosi del «saldo assoluto» (modello ibrido) per una colonna conto.

**«Saldo ibrido» (desktop Conti)** = saldo usato dalla pagina **Saldi** e dalla **Verifica** come «saldo assoluto»:
 parte dalla foto *sld.aco* dell’import (**non** dalla somma riga‑per‑riga), poi applica solo righe create in nuova app,
 compensate gli import annullati e le modifiche ai blocchi .dat ancora attivi, infine sulla colonna sostituisce col
 replay «senza gemello» se ci sono twin import (`hybrid_absolute_balances_for_saldi`).

Se la legacy costruisce il confronto estratto sulla **somma del libro**, con le stesse registrazioni possono comunque
differire quel che mostra desktop (baseline *sld*). La sezione «Replay libro vs ibrido alla data» mette a confronto i
due numeri sulla **stessa data** (`--asof`, es. giorno di chiusura estratto febbraio).

Cosa fa: ricompone il saldo ibrido nelle parti dopo l’import e, se si passa ``--asof``, confronta con il **replay**
solo-libro alla stessa data (stesso motore Movimenti, regole twin incluse).

Elenca inoltre le righe più utili della griglia Movimenti per controlli a occhio sul conto cercato.

Uso:

  python3 scripts/debug_account_balance_discrepancy.py "CC.PP.TT"

  python3 scripts/debug_account_balance_discrepancy.py 6

  python3 scripts/debug_account_balance_discrepancy.py "CC.PP.TT" \\
      --enc /percorso/conti_utente_xxx.enc --key /percorso/conti_di_casa.key

  python3 scripts/debug_account_balance_discrepancy.py "CC.PP.TT" --asof 28/02/2026

Se ``--asof`` non c’è, il confronto replay/ibrido «alla data» usa comunque **la data odierna** (più eventualmente una
seconda data se si passa ``--asof``).

Interpretazione veloce: se «coerenza interna» dice OK sulla colonna, la formula saldo ibrido coincide
su quelle componenti. Se **Replay libro − ibrido alla data** ≠ 0 sulla stessa data dell’estratto, la legacy che
somma il libro e il desktop che parte dal *sld* possono divergere anche con elenchi movimenti identici.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_workspace  # noqa: E402

import main_app as ma  # noqa: E402


def _norm(s: str) -> str:
    return " ".join((s or "").split()).casefold()


def resolve_enc_key(args: argparse.Namespace) -> tuple[list[Path], Path]:
    """Restituisce la lista delle copie `.enc` da provare (ordine come l’app) e la chiave."""
    if args.enc and args.key:
        enc = Path(args.enc).expanduser().resolve()
        return [enc], Path(args.key).expanduser().resolve()
    saved = data_workspace.load_saved_workspace_path()
    if saved is None:
        raise SystemExit(
            "Nessuna cartella dati configurata e mancano --enc / --key.\n"
            "Configurare data_workspace oppure passare percorsi espliciti."
        )
    data_workspace.set_data_workspace_root(saved)
    key_path = data_workspace.default_key_file()
    cands = data_workspace.primary_user_enc_files_sorted(saved)
    if not cands or not key_path.is_file():
        raise SystemExit(
            "Cartella dati senza file .enc o senza chiave .key nella posizione prevista.\n"
            "Usare --enc e --key con percorsi completi."
        )
    return cands, key_path


def load_encrypted_db_first_ok(enc_paths: list[Path], key_path: Path) -> tuple[dict, Path] | None:
    """
    Prova ogni `.enc` con la stessa chiave (come `_try_load_first_valid_user_db` all’avvio).
    Stampa messaggi chiari se fallisce tutto (cryptography assente, token non valido, JSON).
    """
    if getattr(ma, "Fernet", None) is None:
        print(
            "Impossibile decifrare: il modulo «cryptography» non è disponibile in questo Python.\n"
            "Installare nel venv/global usato dal comando, es.: python3 -m pip install cryptography",
            file=sys.stderr,
        )
        return None
    if not key_path.is_file():
        print(f"Manca il file chiave: {key_path}", file=sys.stderr)
        return None
    errs: list[str] = []
    for enc in enc_paths:
        if not enc.is_file():
            errs.append(f"  (manca) {enc}")
            continue
        try:
            db = ma.load_encrypted_db(enc, key_path)
        except Exception as exc:  # noqa: BLE001 — vogliamo elencare ogni fallback .enc provato
            el = exc.__class__.__name__
            if el == "InvalidToken":
                errs.append(f"  {enc.name}: chiave non compatibile col file (profilo/email diversa?).")
            elif isinstance(exc, (OSError, json.JSONDecodeError, ValueError, UnicodeDecodeError)):
                errs.append(f"  {enc.name}: dopo decifratura ({el}: {exc!r}).")
            else:
                errs.append(f"  {enc.name}: errore inatteso ({el}: {exc!r}).")
            continue
        if db is None:
            errs.append(f"  {enc.name}: caricamento vuoto (file o percorsi non validi lato helper).")
            continue
        if not isinstance(db, dict):
            errs.append(f"  {enc.name}: JSON non è un dizionario dopo decifratura.")
            continue
        return db, enc
    cfg = data_workspace.workspace_config_path()
    print(
        "Impossibile decifrare il database con questa chiave e questi `.enc`.\n"
        "Controllare che `conti_di_casa.key` e `conti_utente_<hash>.enc` siano dalla **stessa**\n"
        "cartella profilo dell’app (Opzioni) e sincronizzati; evitare file «light» (.enc `_light`).\n"
        f"Tentativo su {len(enc_paths)} file; cartella configurata vedi anche: {cfg}\n",
        file=sys.stderr,
    )
    for line in errs:
        print(line, file=sys.stderr)
    return None


def find_account(db: dict, needle: str) -> tuple[int, str, str] | None:
    yb = ma.latest_year_bucket(db)
    if not yb:
        return None
    accs = yb.get("accounts") or []
    nneedle = _norm(needle.strip())
    for i, a in enumerate(accs):
        nm = _norm(str(a.get("name", "") or ""))
        code = str(a.get("code", "") or "").strip()
        if nm == nneedle or code == needle.strip():
            return i, str(a.get("name", "") or ""), code
    for i, a in enumerate(accs):
        nm = _norm(str(a.get("name", "") or ""))
        code = str(a.get("code", "") or "").strip()
        if nneedle and (nneedle in nm or nm in nneedle):
            return i, str(a.get("name", "") or ""), code
    return None


def _codes_touch_record(rec: dict, chart_code_ref: str) -> bool:
    c1 = str(rec.get("account_primary_code", "") or "").strip()
    c2 = str(rec.get("account_secondary_code", "") or "").strip()
    return ma._account_codes_equal_for_records(c1, chart_code_ref) or (
        ma.is_giroconto_record(rec) and ma._account_codes_equal_for_records(c2, chart_code_ref)
    )


def _contrib_on_index(rec: dict, accounts: list[dict], n_accounts: int, idx: int) -> Decimal:
    v = ma._record_contribution_to_balance_vector(rec, accounts, n_accounts)
    if 0 <= idx < len(v):
        return v[idx]
    return Decimal("0")



def fmt_e(v: Decimal) -> str:
    return ma.format_euro_it(v)


def _parse_asof_cutoff(raw: str) -> str:
    iso = ma.parse_italian_ddmmyyyy_to_iso(raw.strip())
    if not iso:
        raise ValueError(raw)
    return iso[:10]


def _print_libro_vs_ibrido_panel(
    db: dict,
    *,
    idx: int,
    n_accounts: int,
    asof_iso: str,
    title_hint: str,
    snapshot_sld: bool,
) -> Decimal | None:
    ao = asof_iso[:10]
    try:
        date.fromisoformat(ao)
        it_d = ma.to_italian_date(ao)
        suffix_iso = f"  ({ao})"
    except Exception:
        it_d = ao
        suffix_iso = ""
    print(f"\n► Replay libro vs ibrido «alla data» ({title_hint})")
    print(f"  Data di taglio inclusiva: {it_d}{suffix_iso}")
    print(
        "  «Replay libro» = somma movimenti non annullati con data_iso ≤ soglia "
        "(stesso motore del replay nell’archivio, regole twin sulle colonne interessate)."
    )
    print(
        "  «Ibrido alla data» = come la riga **Saldi alla data** nel footer Movimenti "
        "(foto *sld* + correzioni, meno gli effetti con data dopo la soglia)."
    )

    rep_full = ma._ledger_replay_balances_for_latest_chart(db, cutoff_date_iso=ao)
    hy_dt = ma.hybrid_balances_saldo_in_data(db, asof_iso=ao)

    if rep_full is None or len(rep_full) != n_accounts:
        print("  ⚠️ Impossibile calcolare replay alla data.")
        return None
    if hy_dt is None or len(hy_dt) != n_accounts:
        print("  ⚠️ Impossibile calcolare ibrido alla data.")
        return None
    r_short = rep_full[idx]
    h_short = hy_dt[idx]
    gap = r_short - h_short
    print(f"  Replay libro (colonna), alla data ……… : {fmt_e(r_short)}")
    print(f"  Ibrido «alla data» (colonna) ……………… : {fmt_e(h_short)}")
    print(f"  Scarto replay − ibrido (colonna) ……… : {fmt_e(gap)}")
    if gap == Decimal("0"):
        print("  Coincidono sulla data: sulla colonna libro e definizione desktop «alla data» sono allineati.")
    elif not snapshot_sld:
        print("  Senza snapshot *sld* gli importi dovrebbero essere simili salvo rounding; controllare date vuote nei record.")
    else:
        print(
            "  Scarto diverso da zero: tipico quando la foto *sld* dell’import non coincide col totale libro "
            "(la legacy può essere allineata al libro, Verifica+saldi desktop alla base *sld*)."
        )
    return gap


def _print_libro_vs_ibrido_full_totals(db: dict, *, idx: int, n_accounts: int) -> Decimal | None:
    replay_inf = ma._ledger_replay_balances_for_latest_chart(db, cutoff_date_iso="9999-12-31")
    hy_abs = ma.hybrid_absolute_balances_for_saldi(db, today_cancel_cutoff_iso=date.today().isoformat()[:10])
    if replay_inf is None or hy_abs is None:
        return None
    if len(replay_inf) != n_accounts or len(hy_abs) != n_accounts:
        return None
    gi = replay_inf[idx] - hy_abs[idx]
    today_s = date.today().isoformat()[:10]
    print("\n► Replay libro vs ibrido assoluto (intero libro, una tantum)")
    print("  Tutte le registrazioni con date fino alla massima inclusa nel replay.")
    print("  Data massima inclusiva nel replay ……………… : 9999-12-31")
    print(f"  Replay libro ……………………………………… : {fmt_e(replay_inf[idx])}")
    print(f"  Ibrido assoluto oggì (today_cancel={today_s}) … : {fmt_e(hy_abs[idx])}")
    print(f"  Scarto replay pieno − ibrido assoluto ………… : {fmt_e(gi)}")
    return gi


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnosi ricomposizione saldo ibrido (colonna conto)")
    ap.add_argument("conto", help='Nome conto es. "CC.PP.TT" oppure codice colonna es. 6')
    ap.add_argument("--enc", help="Percorso file .enc principale")
    ap.add_argument("--key", help="Percorso file chiave .key")
    ap.add_argument(
        "--asof",
        metavar="GG/MM/AAAA",
        help="Aggiunge confronto replay/ibrido anche a questa data (es. chiusura estratto). Sempre incluso anche «oggi».",
    )
    args = ap.parse_args()

    try:
        enc_paths, key_p = resolve_enc_key(args)
    except SystemExit as e:
        print(str(e), file=sys.stderr)
        return 2
    loaded = load_encrypted_db_first_ok(enc_paths, key_p)
    if loaded is None:
        return 3
    db, enc_p = loaded

    hit = find_account(db, args.conto.strip())
    if hit is None:
        print(f"Conto non trovato per «{args.conto}». Controlla nome/codice.", file=sys.stderr)
        return 4
    idx, nome, codice_chart = hit
    yb = ma.latest_year_bucket(db)
    accounts = list((yb or {}).get("accounts") or [])
    n_accounts = len(accounts)

    today_iso = date.today().isoformat()[:10]
    asof_extra: str | None = None
    raw_asof = (args.asof or "").strip()
    if raw_asof:
        try:
            asof_extra = _parse_asof_cutoff(raw_asof)
        except ValueError:
            print(
                f"Data «{raw_asof}» non valida per --asof (formato gg/mm/aaaa atteso).",
                file=sys.stderr,
            )
            return 6
    la = ma.legacy_absolute_account_amounts(db, n_accounts)
    new_fx = ma.compute_new_records_effect(db)
    canc = ma.compute_cancelled_imported_records_balance_adjustment(db, cutoff_date_iso=today_iso)
    edit_adj = ma.compute_imported_active_records_edit_balance_adjustment(db)
    tk = ma.import_cancel_twin_balance_keys(db)
    aff: set[int] = set(ma._indices_touched_by_import_twin_actives(db, tk)) if tk else set()

    hyb_full = ma.hybrid_absolute_balances_for_saldi(db, today_cancel_cutoff_iso=today_iso)
    if hyb_full is None or len(hyb_full) != n_accounts:
        print("Errore calcolo vettori saldi.")
        return 5

    pre_h = Decimal("0")
    if la is not None:
        a0 = la[idx]
        a1 = new_fx[idx] if idx < len(new_fx) else Decimal("0")
        a2 = canc[idx] if idx < len(canc) else Decimal("0")
        a3 = edit_adj[idx] if idx < len(edit_adj) else Decimal("0")
        pre_h = a0 + a1 + a2 + a3

    hyb_val = hyb_full[idx]
    print("━" * 72)
    print(f"Diagnosi saldi — DB: {enc_p}")
    print(f"Conto: [{codice_chart}] «{nome}»  (colonna indice piano: {idx})")
    print(f"Data sistema (cutoff hybrid): {today_iso}")
    print("━" * 72)

    print("\n► Parti del saldo «ibrido» (come dalla pagina Saldi dopo import)")
    if la is None:
        print("  Nessuno snapshot *sld* legacy sul DB: il saldo a schermo viene dal replay dei movimenti")
        print("  (fallback interno, con le stesse regole «gemelli» del programma).")
        print(f"  saldo_ibrido_footer (colonna)          : {fmt_e(hyb_val)}")
    else:
        print(f"  da import (*sld* mappato per codice)     : {fmt_e(la[idx])}")
        print(f"  + solo righe create in nuova app         : {fmt_e(new_fx[idx] if idx < len(new_fx) else Decimal('0'))}")
        print(f"  + compensazione righe import annullate   : {fmt_e(canc[idx] if idx < len(canc) else Decimal('0'))}")
        print(f"  + correzione modifiche righe import      : {fmt_e(edit_adj[idx] if idx < len(edit_adj) else Decimal('0'))}")
        print(f"  = somma «prima sostituzione gemelli»    : {fmt_e(pre_h)}")
        twin_note = ""
        if idx in aff:
            twin_note = "  ← colonna soggetta a sostituzione «gemelli» import nella logica dell’app"
        print(f"  saldo mostrato a schermo (footer)       : {fmt_e(hyb_val)}{twin_note}")

    print("\n► Controllo interno sulla colonna selezionata")
    if la is None:
        print("  (Con *sld* assente il programma usa già solo il libro; qui non ci sono parti da ricongiungere.)")
    else:
        gap = hyb_val - pre_h
        if idx in aff and tk:
            _, _, rex = ma.compute_balances_from_2022_asof(
                db, cutoff_date_iso="9999-12-31", exclude_import_twin_actives=True
            )
            if 0 <= idx < len(rex):
                exp = rex[idx]
                print(
                    f"  Gemelli sulla colonna: il saldo a schermo va confrontato col replay senza gemello attivo,"
                    f" atteso sulla colonna ≈ {fmt_e(exp)} (scarto rispetto a somma parti: {fmt_e(gap)})."
                )
            else:
                print(f"  Scarto footer − somma (*sld*+correzioni) = {fmt_e(gap)}")
        elif gap == Decimal("0"):
            print("  La somma *sld* + correzioni coincide col saldo a schermo: coerenza interna OK sulla colonna.")
        else:
            print(
                f"  ⚠️ Scarto footer − somma (*sld*+correzioni) = {fmt_e(gap)} "
                "(imprevisto: andrebbe riportato come bug sulla formula gemelli/ibrido)."
            )
    twin_n = len(tk)
    print(f"\n► Gemelli import: {twin_n} identità chiave duplicate (annulla+attiva).")
    print(f"  Colonne tocchiate dalla sostituzione replay gemelli: {sorted(aff)!r}")
    print(f"  Questo conto in quell’insieme? {'sì' if idx in aff else 'no'}")

    _panels: list[tuple[str, str]] = []
    if asof_extra:
        _panels.append((asof_extra, "--asof"))
    _panels.append((today_iso, "oggi (data sistema)"))
    _seen_dates: set[str] = set()
    panel_gaps: list[Decimal] = []
    for ais, lbl in _panels:
        if ais in _seen_dates:
            continue
        _seen_dates.add(ais)
        gg = _print_libro_vs_ibrido_panel(
            db,
            idx=idx,
            n_accounts=n_accounts,
            asof_iso=ais,
            title_hint=lbl,
            snapshot_sld=la is not None,
        )
        if gg is not None:
            panel_gaps.append(gg)
    gap_full = _print_libro_vs_ibrido_full_totals(db, idx=idx, n_accounts=n_accounts)
    gap_invariant_explained = False
    if (
        gap_full is not None
        and len(panel_gaps) >= 2
        and len({g.quantize(Decimal("0.01")) for g in panel_gaps}) == 1
        and panel_gaps[0].quantize(Decimal("0.01")) == gap_full.quantize(Decimal("0.01"))
    ):
        gap_invariant_explained = True
        print("\n── Nota — scarto replay−ibrido invariante rispetto alla data di taglio ──")
        print(
            "  Lo stesso scarto alle date sopra e nel blocco «intero libro» indica che **non nasce**\n"
            "  dai movimenti dopo la prima data confrontata: su questa colonna replay libro e modello\n"
            "  ibrido (*sld* + correzioni) cambiano sempre **allo stesso modo** quando sposti la soglia.\n"
            "  È uno **sfasamento strutturale** tra «somma movimenti in archivio» e «footer Saldi desktop»,\n"
            "  da tenere separato dal confronto diretto coll’estratto bancario (+/−pochi euro)."
        )

    cod_ref = codice_chart

    # ── Dettaglio elenchi ───────────────────────────────────────────────

    def _iter_records() -> Iterable[dict]:
        for yd in db.get("years") or []:
            for rec in yd.get("records") or []:
                yield rec

    # A) Righe solo-app che toccano il conto
    print("\n── Righe CREATE in nuova app (senza blocchi .dat legacy) sul conto — max 120 ──")
    n_app_lines = 0
    net_app_col = Decimal("0")
    for rec in _iter_records():
        if rec.get("is_cancelled") or rec.get("is_virtuale_discharge"):
            continue
        if (rec.get("raw_record") or "").strip():
            continue
        if not _codes_touch_record(rec, cod_ref):
            continue
        q = _contrib_on_index(rec, accounts, n_accounts, idx)
        if q != Decimal("0"):
            net_app_col += q
        iso = str(rec.get("date_iso", "") or "")
        year = rec.get("year", "")
        n_app_lines += 1
        if n_app_lines <= 120:
            print(
                f"  anno={year}  data={iso}  importo={rec.get('amount_eur')}  "
                f"effetto_colonna={fmt_e(q)}  nota={(str(rec.get('note','') or ''))[:50]}"
            )
    if n_app_lines > 120:
        print(f"  … altre righe non mostrate ({n_app_lines} totali).")
    nf_col = new_fx[idx] if idx < len(new_fx) else Decimal("0")
    print(f"  Somma contributi elencati (non annullati): {fmt_e(net_app_col)}  |  nuovo_effetto_footer: {fmt_e(nf_col)}")

    # B) Righe IMPORT annullate (raw pieno) che toccano il conto
    print("\n── Righe IMPORT annullate (raw_record) sul conto — max 120 ──")
    n_can = 0
    cancel_net = Decimal("0")
    for rec in _iter_records():
        if not rec.get("is_cancelled"):
            continue
        raw = str(rec.get("raw_record") or "").strip()
        if not raw:
            continue
        if not _codes_touch_record(rec, cod_ref):
            continue
        amt_line = ma.to_decimal(rec.get("amount_eur", "0"))
        amount = -amt_line
        c1 = str(rec.get("account_primary_code", "") or "").strip()
        c2 = str(rec.get("account_secondary_code", "") or "").strip()
        c1_ix = ma.account_column_index_in_latest_chart(accounts, c1)
        c2_ix = ma.account_column_index_in_latest_chart(accounts, c2)
        eff = Decimal("0")
        if 0 <= c1_ix < n_accounts and c1_ix == idx:
            eff += amount
        if ma.is_giroconto_record(rec) and 0 <= c2_ix < n_accounts and c2_ix == idx:
            eff -= amount
        if eff == Decimal("0"):
            continue
        cancel_net += eff
        iso = str(rec.get("date_iso", "") or "")
        n_can += 1
        if n_can <= 120:
            print(
                f"  anno={rec.get('year')}  data={iso}  importo_registro={amt_line}  "
                f"effetto_correction_colonna={fmt_e(eff)}"
            )
    if n_can > 120:
        print(f"  … altre righe ({n_can} totali).")
    cn_col = canc[idx] if idx < len(canc) else Decimal("0")
    print(f"  Somma effetti sopra stimata sulla colonna: {fmt_e(cancel_net)}  |  footer canc[idx]: {fmt_e(cn_col)}")

    # C) Righe import modificate ancora attive — delta sulla colonna
    print("\n── Righe IMPORT ancora attive ma DIVERSO dal blocchetto originale sul conto — max 120 ──")
    n_ed = 0
    ed_net = Decimal("0")
    years_list = db.get("years") or []
    latest_calendar_y = max((int(y["year"]) for y in years_list), default=0)
    for yd in db.get("years") or []:
        y_host = int(yd.get("year", 0) or 0)
        if y_host > latest_calendar_y:
            continue
        for rec in yd.get("records") or []:
            if rec.get("is_cancelled") or rec.get("is_virtuale_discharge"):
                continue
            raw = str(rec.get("raw_record") or "").strip()
            if len(raw) < ma._LEGACY_DAT_RECORD_LEN:
                continue
            synth = ma._synthetic_record_from_legacy_dat_raw(raw, y_host)
            if synth is None:
                continue
            cur = ma._record_contribution_to_balance_vector(rec, accounts, n_accounts)
            orig = ma._record_contribution_to_balance_vector(synth, accounts, n_accounts)
            dvec = cur[idx] - orig[idx]
            if dvec == Decimal("0"):
                continue
            if not (
                ma._account_codes_equal_for_records(str(rec.get("account_primary_code", "")), cod_ref)
                or (
                    ma.is_giroconto_record(rec)
                    and ma._account_codes_equal_for_records(str(rec.get("account_secondary_code", "")), cod_ref)
                )
            ):
                continue
            n_ed += 1
            ed_net += dvec
            iso = str(rec.get("date_iso", "") or "")
            if n_ed <= 120:
                print(
                    f"  anno={y_host}  data={iso}  Δ sulla colonna={fmt_e(dvec)} "
                    f"  importo ora={rec.get('amount_eur')}  sintetico={synth.get('amount_eur')}"
                )
    if n_ed > 120:
        print(f"  … altre righe ({n_ed} totali).")
    e_col = edit_adj[idx] if idx < len(edit_adj) else Decimal("0")
    print(f"  Somma Δ elencati sulla colonna: {fmt_e(ed_net)}  |  footer edit_adj[idx]: {fmt_e(e_col)}")

    if gap_invariant_explained:
        print("\n── Nota (fine rapporto: estratto piccolo vs grande scarto libro−ibrido) ──")
        print(
            "  Sopra hai uno **sfasamento libro / modello desktop** costante sulla colonna; non cercarlo riga‑per‑riga\n"
            "  negli acquisti marzo–aprile. Un diverso problema «pochi euro» su **Verifica estratto PDF** va letto sulla\n"
            "  **stessa data dell’estratto** e sulla definizione saldo estratto ≠ somma libro completa sulla carta.\n"
        )
    else:
        print("\n── Nota (contesto quando il replay−ibrido *cambia* tra le date confrontate) ──")
        print(
            "  Se dopo una verifica “quadrata” a una certa data noti poi che lo **scarto replay−ibrido** non è più\n"
            "  uguale aprendo un secondo `--asof`, vale la pena controllare dalla data del primo cambiamento:\n"
            "  modifiche a import annullati, codici colonna, ecc. Possono essere scarti anche «piccoli» se non sono\n"
            "  sempre la stessa cifra al variare delle date."
        )

    print("\nFine rapporto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
