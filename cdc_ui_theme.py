"""Preferenze colore UI: override nel DB cifrato, normalizzazione HEX, risoluzione token."""

from __future__ import annotations

import re
from typing import Callable

_OVERRIDES_KEY = "_ui_color_overrides"

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


_LEGACY_UI_BLUE_BG = (
    "mov_btn_agg_cat_bg",
    "mov_btn_modifica_reg_bg",
    "mov_btn_ripristina_layout_bg",
    "mov_btn_pulisci_filtri_bg",
    "ver_btn_pending_edit_bg",
    "ver_btn_modifica_nonver_bg",
    "opz_action_blue_bg",
)
_LEGACY_UI_BLUE_HOVER = (
    "mov_btn_agg_cat_hover_bg",
    "mov_btn_ripristina_layout_hover_bg",
    "mov_btn_pulisci_filtri_hover_bg",
    "opz_action_blue_hover_bg",
)
_LEGACY_UI_RED_BG = ("opz_action_red_bg", "ver_btn_pending_delete_bg")
_LEGACY_UI_RED_HOVER = ("opz_action_red_hover_bg",)
_LEGACY_CORRECTION_ERROR_FG = ("mov_correction_error_fg", "ver_correction_error_fg")


def migrate_ui_color_token_consolidation(db: dict) -> bool:
    """Unifica in pochi token i colori già equivalenti nella palette (blu/rosso azione, testo errore).

    Copia il primo override valido tra le chiavi legacy nel token canonico se mancante,
    poi rimuove le chiavi legacy da ``_ui_color_overrides``.
    """
    migrate_ensure_ui_color_overrides(db)
    raw = db.get(_OVERRIDES_KEY)
    if not isinstance(raw, dict):
        return False
    o: dict[str, str] = dict(raw)
    changed = False

    def _absorb_canonical(canon: str, legacies: tuple[str, ...]) -> None:
        nonlocal changed
        canon_val = None
        if canon in o:
            canon_val = normalize_hex_color(o[canon])
            if canon_val is None:
                del o[canon]
                changed = True
        if canon_val is None:
            picked = None
            for leg in legacies:
                if leg not in o:
                    continue
                n = normalize_hex_color(o[leg])
                if n is not None:
                    picked = n
                    break
            if picked is not None:
                o[canon] = picked
                changed = True
        for leg in legacies:
            if leg in o:
                del o[leg]
                changed = True

    _absorb_canonical("ui_action_blue_bg", _LEGACY_UI_BLUE_BG)
    _absorb_canonical("ui_action_blue_hover_bg", _LEGACY_UI_BLUE_HOVER)
    _absorb_canonical("ui_action_red_bg", _LEGACY_UI_RED_BG)
    _absorb_canonical("ui_action_red_hover_bg", _LEGACY_UI_RED_HOVER)
    _absorb_canonical("correction_error_fg", _LEGACY_CORRECTION_ERROR_FG)

    if changed:
        db[_OVERRIDES_KEY] = o
    return changed


def migrate_ensure_ui_color_overrides(db: dict) -> bool:
    """Garantisce ``db['_ui_color_overrides']``: mappa ``token`` → ``#rrggbb``."""
    k = _OVERRIDES_KEY
    if k not in db or not isinstance(db.get(k), dict):
        db[k] = {}
        return True
    # Ripulisci chiavi non stringa / valori non hex
    clean: dict[str, str] = {}
    raw = db[k]
    assert isinstance(raw, dict)
    changed = False
    for t, v in raw.items():
        if not isinstance(t, str) or not isinstance(v, str):
            changed = True
            continue
        n = normalize_hex_color(v)
        if n is None:
            changed = True
            continue
        clean[t.strip()] = n
    if clean != raw:
        db[k] = clean
        changed = True
    return changed


def normalize_hex_color(s: str) -> str | None:
    """Restituisce ``#rrggbb`` minuscolo o None."""
    t = (s or "").strip().lower().replace(" ", "")
    if not t.startswith("#"):
        t = "#" + t
    if not _HEX_RE.match(t):
        return None
    return t.lower()


def resolved_hex(
    token: str,
    *,
    base: dict[str, str],
    extras: dict[str, str],
    overrides: dict[str, str],
) -> str:
    """Colore effettivo per il token (override se presente e valido)."""
    o = overrides.get(token)
    if o is not None:
        n = normalize_hex_color(o)
        if n is not None:
            return n
    if token in extras:
        return extras[token]
    return base[token]


def merge_overrides(overrides: dict[str, str], token: str, value: str | None) -> dict[str, str]:
    """Copia mutabile: ``value`` None rimuove la chiave."""
    out = dict(overrides)
    if value is None:
        out.pop(token, None)
    else:
        out[token] = value
    return out


def make_resolver(
    *,
    base: dict[str, str],
    extras: dict[str, str],
    get_overrides: Callable[[], dict[str, str]],
) -> Callable[[str], str]:
    def _r(token: str) -> str:
        return resolved_hex(token, base=base, extras=extras, overrides=get_overrides())

    return _r


__all__ = [
    "migrate_ui_color_token_consolidation",
    "migrate_ensure_ui_color_overrides",
    "normalize_hex_color",
    "resolved_hex",
    "merge_overrides",
    "make_resolver",
    "_OVERRIDES_KEY",
]
