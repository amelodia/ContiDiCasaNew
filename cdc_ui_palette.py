"""Palette colori interfaccia «Conti di casa»: gruppi per scheda Opzioni e id stabili.

Gli identificatori token (chiavi stringa) sono l'ancora per future preferenze utente salvate nel DB:
la mappa ``_base_palette_map()`` legge costanti già definite in ``main_app`` / ``security_auth``;
colori dichiarati solo dentro ``build_ui`` arrivano tramite ``extras``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

# (titolo gruppo, [(token_id, etichetta leggibile italiano), ...])
PALETTE_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Sfondi pagine",
        [
            ("bg_page_primary", "Sfondo principale della finestra e delle schede dopo l’accesso"),
            ("bg_opzioni_scroll_canvas", "Area scroll della scheda Opzioni"),
        ],
    ),
    (
        "Griglia Movimenti",
        [
            ("grid_stripe0", "Righe dispari della griglia"),
            ("grid_stripe1", "Righe pari della griglia"),
            ("grid_heading_bg", "Intestazioni colonne (sfondo)"),
            ("fg_grid_primary", "Testo intestazioni colonne della griglia"),
            ("fg_mov_search_caption", "Testo illustrativo della selezione sopra la griglia"),
            ("grid_tree_selection_bg", "Riga selezionata (sfondo Treeview)"),
            ("grid_tree_selection_fg", "Riga selezionata (testo Treeview)"),
        ],
    ),
    (
        "Importi (visualizzazione)",
        [
            ("amount_positive", "Importi positivi (verde)"),
            ("amount_negative", "Importi negativi (rosso scuro)"),
        ],
    ),
    (
        "Campi modulo e filtri (scheda Movimenti)",
        [
            ("field_bg_moduli", "Sfondo campi di digitazione elenco ricerca"),
            ("fg_filter_label", "Testo delle etichette filtro"),
            ("fg_filter_entry", "Testo dentro i campi filtro"),
        ],
    ),
    (
        "Movimenti — pulsanti scelta filtri (tab chip)",
        [
            ("mov_filter_tab_btn_bg", "Chip non selezionato"),
            ("mov_filter_tab_btn_hover_bg", "Chip — passaggio mouse"),
            ("mov_filter_tab_btn_active_bg", "Chip — opzione attiva"),
            ("mov_filter_tab_btn_fg", "Testo sui chip"),
        ],
    ),
    (
        "Calendario nei filtri Movimenti",
        [
            ("cal_cell_bg", "Celle giorno normali"),
            ("cal_selected_bg", "Giorno selezionato"),
            ("cal_disabled_bg", "Date non selezionabili (sfondo)"),
            ("cal_disabled_label_fg", "Date non disponibili (testo grigio)"),
        ],
    ),
    (
        "Finestra login e barra schede pagine",
        [
            ("login_window_bg", "Sfondo della finestra di accesso"),
            (
                "tipo_btn_bg",
                "Barra tab in alto (Movimenti, Nuove registrazioni, …) — stato normale; «Accedi» / «Nuova utenza» / «Esci» sono altrove",
            ),
            ("tipo_btn_hover_bg", "Stessa barra — passaggio mouse"),
            ("tipo_btn_active_bg", "Stessa barra — scheda attiva"),
            ("tipo_btn_fg", "Testo sulla barra tab"),
            ("tipo_btn_ring", "Contorno pulsanti tab"),
            ("tipo_btn_ring_focus", "Contorno focus tab"),
            ("tipo_field_bg", "Campi sulla finestra di login (email/password)"),
        ],
    ),
    (
        "Movimenti — pulsanti e messaggi correzione",
        [
            ("mov_btn_print_search_bg", "Rosso «Stampa ricerca» / correzione Movimenti / «Conferma immissione» / conferme periodiche"),
            ("mov_btn_print_search_hover_bg", "Hover dei suddetti"),
            ("mov_btn_espandi_bg", "«Espandi ricerca»"),
            ("mov_btn_espandi_hover_bg", "«Espandi ricerca» hover"),
            ("mov_btn_cerca_bg", "«Cerca»"),
            ("mov_btn_cerca_hover_bg", "«Cerca» hover"),
            (
                "mov_pulisci_accedi_bg",
                "«Pulisci filtri» (Movimenti), «Accedi» (login), «Cancella valori» (Nuova registrazione e Periodiche)",
            ),
            ("mov_pulisci_accedi_hover_bg", "Passaggio mouse su quei pulsanti"),
        ],
    ),
    (
        "Pulsanti e link — blu (Aggrega categorie, Modifica, «Nuova utenza», Verifica, Opzioni…)",
        [
            ("ui_action_blue_bg", "Sfondo normale (collegamenti Opzioni e altri pulsanti blu elencati nel titolo del gruppo)"),
            ("ui_action_blue_hover_bg", "Passaggio mouse"),
        ],
    ),
    (
        "Pulsanti e link — rosso (Opzioni, Elimina in Verifica e Periodiche)",
        [
            ("ui_action_red_bg", "Sfondo normale"),
            ("ui_action_red_hover_bg", "Passaggio mouse"),
        ],
    ),
    (
        "Messaggi errore — barre correzione",
        [
            ("correction_error_fg", "Testo rosso errore (Movimenti e Verifica «non verificate»)"),
        ],
    ),
    (
        "Verifica — griglia importi",
        [
            ("ver_grid_amount_pos_fg", "Importo positivo nella griglia"),
            ("ver_grid_amount_neg_fg", "Importo negativo nella griglia"),
            ("ver_grid_amount_zero_fg", "Importo zero / neutro nella griglia"),
        ],
    ),
    (
        "Verifica — azioni registrazioni sospese",
        [
            ("ver_btn_pending_new_bg", "Nuovo / aggiungi"),
            ("ver_btn_pending_clear_bg", "Deseleziona righe"),
        ],
    ),
    (
        "Verifica — pulsanti piede",
        [
            ("ver_footer_print_bg", "Stampa…"),
            ("ver_footer_cycle_bg", "Cambia / ciclo"),
            ("ver_footer_close_bg", "Chiudi verifica"),
        ],
    ),
]

_all_tokens_in_groups: frozenset[str] = frozenset(
    t for _, rows in PALETTE_GROUPS for t, _ in rows
)


def _base_palette_map() -> dict[str, str]:
    import security_auth as sa

    import main_app as m

    return {
        "bg_page_primary": m.MOVIMENTI_PAGE_BG,
        "bg_opzioni_scroll_canvas": m.OPZIONI_SCROLL_CANVAS_BG,
        "grid_stripe0": m.CDC_GRID_STRIPE0_BG,
        "grid_stripe1": m.CDC_GRID_STRIPE1_BG,
        "grid_heading_bg": m.CDC_GRID_HEADING_BG,
        "fg_grid_primary": m.UI_FG_GRID_PRIMARY,
        "fg_mov_search_caption": m.UI_FG_MOV_SEARCH_CAPTION,
        "grid_tree_selection_bg": m.CDC_GRID_TREEVIEW_SEL_BG,
        "grid_tree_selection_fg": m.CDC_GRID_TREEVIEW_SEL_FG,
        "amount_positive": m.COLOR_AMOUNT_POS,
        "amount_negative": m.COLOR_AMOUNT_NEG,
        "field_bg_moduli": m.CDC_ENTRY_FIELD_BG,
        "fg_filter_label": m.UI_FG_FILTER_LABEL,
        "fg_filter_entry": m.UI_FG_FILTER_ENTRY,
        "mov_filter_tab_btn_bg": m.MOV_FILTER_TAB_BTN_BG,
        "mov_filter_tab_btn_hover_bg": m.MOV_FILTER_TAB_BTN_HOVER_BG,
        "mov_filter_tab_btn_active_bg": m.MOV_FILTER_TAB_BTN_ACTIVE_BG,
        "mov_filter_tab_btn_fg": m.MOV_FILTER_TAB_BTN_FG,
        "cal_cell_bg": m.CDC_CAL_CELL_BG,
        "cal_selected_bg": m.CDC_CAL_SELECTED_BG,
        "cal_disabled_bg": m.CDC_CAL_DISABLED_BG,
        "cal_disabled_label_fg": m.CDC_CAL_DISABLED_LABEL_FG,
        "login_window_bg": sa.CDC_LOGIN_WIN_BG,
        "tipo_btn_bg": sa.CDC_TIPO_TASTI_BTN_BG,
        "tipo_btn_hover_bg": sa.CDC_TIPO_TASTI_BTN_HOVER_BG,
        "tipo_btn_active_bg": sa.CDC_TIPO_TASTI_BTN_ACTIVE_BG,
        "tipo_btn_fg": sa.CDC_TIPO_TASTI_BTN_FG,
        "tipo_btn_ring": sa.CDC_TIPO_TASTI_BTN_RING,
        "tipo_btn_ring_focus": sa.CDC_TIPO_TASTI_BTN_RING_FOCUS,
        "tipo_field_bg": sa.CDC_TIPO_TASTI_FIELD_BG,
    }


_base_cache: dict[str, str] | None = None


def _effective_base_map() -> dict[str, str]:
    global _base_cache
    if _base_cache is None:
        _base_cache = _base_palette_map()
    return _base_cache


def get_base_palette_map_copy() -> dict[str, str]:
    """Copia della mappa colori base (senza override utente)."""
    return dict(_effective_base_map())


def invalidate_base_palette_cache() -> None:
    """Dopo aver modificato le costanti modulo su cui si basa ``_base_palette_map()``."""
    global _base_cache
    _base_cache = None


ALL_UI_COLOR_TOKEN_IDS: tuple[str, ...] = tuple(sorted(_all_tokens_in_groups))


def resolve_palette_color(token: str, extras: dict[str, str]) -> str:
    if token in extras:
        return extras[token]
    base = _effective_base_map()
    return base[token]


def iter_palette_slots(
    *,
    extras: dict[str, str],
    resolver: Callable[[str], str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """[(group_title, token, label, hex), ...] nell'ordine di ``PALETTE_GROUPS``."""
    if resolver is None:

        def _res(t: str) -> str:
            return resolve_palette_color(t, extras)

        resolver = _res

    rows: list[tuple[str, str, str, str]] = []
    for gtitle, slots in PALETTE_GROUPS:
        for token, lab in slots:
            rows.append((gtitle, token, lab, resolver(token)))
    return rows


def assert_extras_defined_for_dynamic_tokens(extras: dict[str, str]) -> None:
    """Il dict ``extras`` deve elencare esattamente tutti i token che non sono nel map base."""
    base = frozenset(_effective_base_map())
    dyn = frozenset(t for t in _all_tokens_in_groups if t not in base)
    got = frozenset(extras)
    if got != dyn:
        raise RuntimeError(
            "cdc_ui_palette: la mappa extras non coincide coi token dinamici nella palette:\n"
            f"  mancanti → {sorted(dyn - got)}\n"
            f"  eccedenti → {sorted(got - dyn)}"
        )


def pack_opzioni_color_palette_section(
    parent: tk.Misc,
    *,
    extras: dict[str, str],
    title_font: tuple,
    section_bg: str,
    get_resolved_hex: Callable[[str], str],
    on_color_commit: Callable[[str, str | None], None],
) -> None:
    """Inserisce in ``parent`` (ttk.Frame scrollabile Opzioni) la palette leggibile dall'utente.

    ``get_resolved_hex(token)`` restituisce il colore effettivo (override incluso).
    ``on_color_commit(token, hex_norm | None)``: ``None`` = ripristina il default codice;
    stringa ``#rrggbb`` = salva override e applica tema.
    """
    assert_extras_defined_for_dynamic_tokens(extras)

    lf = ttk.LabelFrame(parent, padding=(10, 8))
    lf.configure(labelwidget=ttk.Label(lf, text="Palette colori interfaccia", font=title_font))
    lf.pack(fill=tk.X, padx=(28, 10), pady=(0, 14))

    intro = (
        "Ogni riga mostra un colore dell’interfaccia: puoi digitare un nuovo HEX (o incollare), "
        "poi «Applica» per vederlo subito nell’area indicata. «Default codice» rimuove la tua "
        "personalizzazione per quel solo parametro. I valori restano nel database cifrato quando salvi."
    )
    ttk.Label(lf, text=intro, wraplength=760, justify=tk.LEFT).pack(fill=tk.X, anchor="w", pady=(0, 10))

    from cdc_round_color_wheel import pack_round_color_wheel_for_opzioni

    pack_round_color_wheel_for_opzioni(lf, section_bg=section_bg, title_font=title_font)

    body = tk.Frame(lf, bg=section_bg, highlightthickness=0)
    body.pack(fill=tk.X, expand=False)

    sw_w, sw_h = 44, 22

    _swatch_rect: dict[str, tuple[tk.Canvas, int]] = {}
    hex_vars: dict[str, tk.StringVar] = {}

    def _repaint_swatch(token: str) -> None:
        pair = _swatch_rect.get(token)
        if not pair:
            return
        cnv, rid = pair
        try:
            cnv.itemconfigure(rid, fill=get_resolved_hex(token))
        except tk.TclError:
            pass

    def _refresh_row(token: str) -> None:
        if token in hex_vars:
            hex_vars[token].set(get_resolved_hex(token))
        _repaint_swatch(token)

    def _commit_apply(token: str) -> None:
        from cdc_ui_theme import normalize_hex_color

        raw = (hex_vars[token].get() or "").strip()
        n = normalize_hex_color(raw)
        if n is None:
            messagebox.showerror(
                "HEX non valido",
                "Inserisci un colore esadecimale come #a1b2c3 (6 cifre dopo #).",
                parent=lf,
            )
            _refresh_row(token)
            return
        on_color_commit(token, n)
        _refresh_row(token)

    def _commit_default(token: str) -> None:
        on_color_commit(token, None)
        _refresh_row(token)

    current_group: str | None = None
    group_frame: tk.Frame | None = None

    for gtitle, token, lab, _ in iter_palette_slots(
        extras=extras, resolver=get_resolved_hex
    ):
        if gtitle != current_group:
            current_group = gtitle
            group_frame = tk.Frame(body, bg=section_bg, highlightthickness=0)
            group_frame.pack(fill=tk.X, pady=(0, 8))
            tk.Label(
                group_frame,
                text=gtitle,
                font=("TkDefaultFont", 11, "bold"),
                bg=section_bg,
                fg="#1a3a52",
                anchor="w",
            ).pack(fill=tk.X, anchor="w")

        assert group_frame is not None
        row = tk.Frame(group_frame, bg=section_bg, highlightthickness=0)
        row.pack(fill=tk.X, pady=(0, 4))

        cnv = tk.Canvas(
            row,
            width=sw_w,
            height=sw_h,
            highlightthickness=1,
            highlightbackground="#999999",
            bd=0,
            bg=section_bg,
        )
        cnv.pack(side=tk.LEFT, padx=(0, 8), pady=1, anchor=tk.N)
        hx = get_resolved_hex(token)
        rid = cnv.create_rectangle(1, 1, sw_w - 1, sw_h - 1, outline="", fill=hx)
        _swatch_rect[token] = (cnv, rid)

        right = tk.Frame(row, bg=section_bg, highlightthickness=0)
        right.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(right, text=lab, anchor="w", bg=section_bg, fg="#111111").pack(
            fill=tk.X, anchor="w"
        )
        edit_row = tk.Frame(right, bg=section_bg, highlightthickness=0)
        edit_row.pack(fill=tk.X, pady=(2, 0))
        hv = tk.StringVar(value=hx)
        hex_vars[token] = hv
        ent = ttk.Entry(edit_row, textvariable=hv, width=11, font=("Courier New", 11))
        ent.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(edit_row, text="Applica", width=9, command=lambda t=token: _commit_apply(t)).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(edit_row, text="Default codice", command=lambda t=token: _commit_default(t)).pack(
            side=tk.LEFT
        )
        tk.Label(
            right,
            text=token,
            anchor="w",
            font=("TkFixedFont", 8),
            bg=section_bg,
            fg="#667788",
        ).pack(fill=tk.X, anchor="w", pady=(1, 0))

    foot = tk.Frame(lf, bg=section_bg, highlightthickness=0)
    foot.pack(fill=tk.X, pady=(10, 0))
    tk.Label(
        foot,
        text="Nota: i chip dei filtri Movimenti (modalità ricerca, preset date, ecc.) hanno token dedicati "
        "nel gruppo «Movimenti — pulsanti scelta filtri». La barra tab delle pagine in alto usa il gruppo "
        "«Finestra login e barra schede pagine» (tipo tasti). I pulsanti d’azione sotto i campi nella finestra di "
        "login (Accedi, Nuova utenza, Esci) seguono i token nel gruppo «Movimenti — pulsanti e messaggi correzione» "
        "(Accedi/Cancella valori), «Pulsanti e link — blu» (Nuova utenza) e «— rosso» / stampa ricerca (Esci).",
        font=("TkDefaultFont", 9),
        fg="#555555",
        bg=section_bg,
        wraplength=760,
        justify=tk.LEFT,
    ).pack(anchor="w")


__all__ = [
    "ALL_UI_COLOR_TOKEN_IDS",
    "PALETTE_GROUPS",
    "get_base_palette_map_copy",
    "invalidate_base_palette_cache",
    "pack_opzioni_color_palette_section",
    "resolve_palette_color",
]
