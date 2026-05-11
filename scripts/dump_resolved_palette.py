#!/usr/bin/env python3
"""Estrae dal database cifrato la palette UI risolta (token → #rrggbb).

Serve ad allineare le costanti nel codice agli override attualmente salvati: eseguire
con il percorso del proprio ``.enc`` e della ``.key``, copiare i valori nelle
sezioni indicate in output (``main_app.py``, ``security_auth.py``, letterali in
``build_ui`` per i token «extras»), poi opzionalmente svuotare ``_ui_color_overrides``
nel DB se si vuole evitare doppia definizione.

Esempio::

    python3 scripts/dump_resolved_palette.py /percorso/conti_utente_xxx.enc /percorso/conti_utente_xxx.key
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _extras_defaults_synced_with_build_ui() -> dict[str, str]:
    """Stessi valori iniziali di ``_opz_palette_extras`` in ``main_app.build_ui``."""
    return {
        "ui_action_blue_bg": "#1565c0",
        "ui_action_blue_hover_bg": "#0d47a1",
        "ui_action_red_bg": "#b71c1c",
        "ui_action_red_hover_bg": "#7f0000",
        "correction_error_fg": "#b71c1c",
        "mov_btn_print_search_bg": "#c62828",
        "mov_btn_print_search_hover_bg": "#8e0000",
        "mov_btn_espandi_bg": "#00695c",
        "mov_btn_espandi_hover_bg": "#004d40",
        "mov_btn_cerca_bg": "#2e7d32",
        "mov_btn_cerca_hover_bg": "#1b5e20",
        "mov_btn_cerca_fg": "#ffffff",
        "mov_pulisci_accedi_bg": "#1565c0",
        "mov_pulisci_accedi_hover_bg": "#0d47a1",
        "ver_grid_amount_pos_fg": "#156716",
        "ver_grid_amount_neg_fg": "#b71c1c",
        "ver_grid_amount_zero_fg": "#424242",
        "ver_btn_pending_new_bg": "#2e7d32",
        "ver_btn_pending_clear_bg": "#616161",
        "ver_footer_print_bg": "#ff0000",
        "ver_footer_cycle_bg": "#ef6c00",
        "ver_footer_close_bg": "#c62828",
    }


def _base_attr_hints() -> dict[str, tuple[str, str]]:
    """token → (modulo, nome_costante)."""
    return {
        "bg_page_primary": ("main_app", "MOVIMENTI_PAGE_BG"),
        "bg_opzioni_scroll_canvas": ("main_app", "OPZIONI_SCROLL_CANVAS_BG"),
        "grid_stripe0": ("main_app", "CDC_GRID_STRIPE0_BG"),
        "grid_stripe1": ("main_app", "CDC_GRID_STRIPE1_BG"),
        "grid_heading_bg": ("main_app", "CDC_GRID_HEADING_BG"),
        "fg_grid_primary": ("main_app", "UI_FG_GRID_PRIMARY"),
        "fg_mov_search_caption": ("main_app", "UI_FG_MOV_SEARCH_CAPTION"),
        "grid_tree_selection_bg": ("main_app", "CDC_GRID_TREEVIEW_SEL_BG"),
        "grid_tree_selection_fg": ("main_app", "CDC_GRID_TREEVIEW_SEL_FG"),
        "amount_positive": ("main_app", "COLOR_AMOUNT_POS"),
        "amount_negative": ("main_app", "COLOR_AMOUNT_NEG"),
        "field_bg_moduli": ("main_app", "CDC_ENTRY_FIELD_BG"),
        "fg_filter_label": ("main_app", "UI_FG_FILTER_LABEL"),
        "fg_filter_entry": ("main_app", "UI_FG_FILTER_ENTRY"),
        "mov_filter_tab_btn_bg": ("main_app", "MOV_FILTER_TAB_BTN_BG"),
        "mov_filter_tab_btn_hover_bg": ("main_app", "MOV_FILTER_TAB_BTN_HOVER_BG"),
        "mov_filter_tab_btn_active_bg": ("main_app", "MOV_FILTER_TAB_BTN_ACTIVE_BG"),
        "mov_filter_tab_btn_fg": ("main_app", "MOV_FILTER_TAB_BTN_FG"),
        "cal_cell_bg": ("main_app", "CDC_CAL_CELL_BG"),
        "cal_selected_bg": ("main_app", "CDC_CAL_SELECTED_BG"),
        "cal_disabled_bg": ("main_app", "CDC_CAL_DISABLED_BG"),
        "cal_disabled_label_fg": ("main_app", "CDC_CAL_DISABLED_LABEL_FG"),
        "login_window_bg": ("security_auth", "CDC_LOGIN_WIN_BG"),
        "tipo_btn_bg": ("security_auth", "CDC_TIPO_TASTI_BTN_BG"),
        "tipo_btn_hover_bg": ("security_auth", "CDC_TIPO_TASTI_BTN_HOVER_BG"),
        "tipo_btn_active_bg": ("security_auth", "CDC_TIPO_TASTI_BTN_ACTIVE_BG"),
        "tipo_btn_fg": ("security_auth", "CDC_TIPO_TASTI_BTN_FG"),
        "tipo_btn_ring": ("security_auth", "CDC_TIPO_TASTI_BTN_RING"),
        "tipo_btn_ring_focus": ("security_auth", "CDC_TIPO_TASTI_BTN_RING_FOCUS"),
        "tipo_field_bg": ("security_auth", "CDC_TIPO_TASTI_FIELD_BG"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Dump palette risolta dal DB cifrato.")
    ap.add_argument("enc", type=Path, help="Percorso file .enc")
    ap.add_argument("key", type=Path, help="Percorso file .key")
    ap.add_argument("--json", action="store_true", help="Solo JSON su stdout")
    args = ap.parse_args()

    from main_app import load_encrypted_db

    import cdc_ui_palette as cup
    import cdc_ui_theme as cut

    cup.invalidate_base_palette_cache()
    db = load_encrypted_db(args.enc.expanduser().resolve(), args.key.expanduser().resolve())
    if not db:
        print("Impossibile decifrare o leggere il database.", file=sys.stderr)
        return 1

    cut.migrate_ensure_ui_color_overrides(db)
    cut.migrate_ui_color_token_consolidation(db)
    base = cup.get_base_palette_map_copy()
    extras = _extras_defaults_synced_with_build_ui()
    ovr = db.get(cut._OVERRIDES_KEY)
    overrides: dict[str, str] = {}
    if isinstance(ovr, dict):
        for k, v in ovr.items():
            if isinstance(k, str) and isinstance(v, str):
                nk = cut.normalize_hex_color(v)
                if nk is not None:
                    overrides[k.strip()] = nk

    resolved: dict[str, str] = {}
    for tid in cup.ALL_UI_COLOR_TOKEN_IDS:
        resolved[tid] = cut.resolved_hex(
            tid, base=base, extras=extras, overrides=overrides
        )

    if args.json:
        json.dump(resolved, sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    print("# Palette risolta (token → hex). Copiare nelle costanti indicate.\n")
    hints = _base_attr_hints()
    by_mod: dict[str, list[tuple[str, str, str]]] = {}
    extras_only: list[tuple[str, str]] = []
    for tid in sorted(resolved.keys()):
        h = resolved[tid]
        hi = hints.get(tid)
        if hi:
            mod, name = hi
            by_mod.setdefault(mod, []).append((name, h, tid))
        elif tid in extras:
            extras_only.append((tid, h))
        else:
            print(f"# {tid} = {h}  (token non mappato automaticamente)")

    for mod in ("main_app", "security_auth"):
        rows = by_mod.get(mod, [])
        if not rows:
            continue
        print(f"# --- {mod} ---")
        for name, h, tid in sorted(rows, key=lambda x: x[0]):
            print(f"# {tid}")
            print(f"{name} = {json.dumps(h)}")
        print()

    if extras_only:
        print("# --- main_app.build_ui (letterali _OPZ_* / _PRINT_* / _VER_* / _ESPANDI_* … e dict _opz_palette_extras) ---")
        # Nomi comodi per cercare nel sorgente
        _nick = {
            "ui_action_blue_bg": "_OPZ_BLUE",
            "ui_action_blue_hover_bg": "_OPZ_BLUE_ACTIVE",
            "correction_error_fg": "correction_error_fg (dict)",
            "mov_btn_print_search_bg": "_PRINT_RICERCA_RED",
            "mov_btn_print_search_hover_bg": "_PRINT_RICERCA_RED_ACTIVE",
            "mov_btn_espandi_bg": "_ESPANDI_ELENCO_BG",
            "mov_btn_espandi_hover_bg": "_ESPANDI_ELENCO_BG_ACT",
            "mov_btn_cerca_bg": "_CERCA_GREEN",
            "mov_btn_cerca_hover_bg": "_CERCA_GREEN_ACTIVE",
            "mov_btn_cerca_fg": "_CERCA_FG",
            "mov_pulisci_accedi_bg": "_MOV_PULISCI_ACCEDI_BG",
            "mov_pulisci_accedi_hover_bg": "_MOV_PULISCI_ACCEDI_HOVER_BG",
        }
        for tid, h in sorted(extras_only, key=lambda x: x[0]):
            hint = _nick.get(tid, tid)
            print(f"# {tid} → cerca `{hint}`")
            print(f"#   \"{tid}\": {json.dumps(h)},")
        print()

    print("# Override nel DB (dopo aver copiato nel codice, puoi svuotare _ui_color_overrides se preferisci):")
    print(json.dumps(overrides, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
