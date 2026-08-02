"""Palette rotonda (tono/saturazione) + luminosità e visualizzazione HEX per la scheda Opzioni."""

from __future__ import annotations

import colorsys
import math
import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageTk

# Dimensione lato immagine ruota (pixel). Dispari → centro intero.
_WHEEL_SIZE = 257
_WHEEL_RADIUS = (_WHEEL_SIZE - 1) // 2
_WHEEL_CENTER = _WHEEL_SIZE // 2


def _parse_backdrop_rgb(backdrop: str) -> tuple[int, int, int]:
    s = (backdrop or "").strip()
    if len(s) == 7 and s.startswith("#"):
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    return (240, 240, 240)


def _build_saturation_disk(*, backdrop: str) -> Image.Image:
    """Disco H–S a luminosità massima (V=1); fuori dal cerchio: colore di sfondo."""
    bd = _parse_backdrop_rgb(backdrop)
    img = Image.new("RGB", (_WHEEL_SIZE, _WHEEL_SIZE), bd)
    pix = img.load()
    cx = cy = _WHEEL_CENTER
    rmax = float(_WHEEL_RADIUS)
    for y in range(_WHEEL_SIZE):
        for x in range(_WHEEL_SIZE):
            dx = float(x - cx)
            dy = float(y - cy)
            d = math.hypot(dx, dy)
            if d > rmax + 1e-6:
                continue
            if d < 1e-9:
                h = 0.0
                s_val = 0.0
            else:
                h = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
                s_val = min(1.0, d / rmax)
            rf, gf, bf = colorsys.hsv_to_rgb(h, s_val, 1.0)
            pix[x, y] = (
                max(0, min(255, int(round(rf * 255.0)))),
                max(0, min(255, int(round(gf * 255.0)))),
                max(0, min(255, int(round(bf * 255.0)))),
            )
    return img


def _hsv_from_disk_xy(dx: float, dy: float) -> tuple[float, float]:
    """Distanza dal centro → saturazione; angolo → tono [0,1)."""
    rmax = float(_WHEEL_RADIUS)
    d_raw = math.hypot(dx, dy)
    if d_raw <= 1e-9:
        return 0.0, 0.0
    if d_raw > rmax:
        f = rmax / d_raw
        dx *= f
        dy *= f
        d_raw = rmax
    h = (math.degrees(math.atan2(dy, dx)) % 360.0) / 360.0
    s = min(1.0, d_raw / rmax)
    return h, s


def _disk_xy_from_hsv(hue: float, sat: float) -> tuple[float, float]:
    rmax = float(_WHEEL_RADIUS)
    hue = hue % 1.0
    sat = max(0.0, min(1.0, sat))
    rad = 2.0 * math.pi * hue
    d = sat * rmax
    return d * math.cos(rad), d * math.sin(rad)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


class RoundHsvWheelPicker(tk.Frame):
    """Tk.Frame con canvas circolare, slider luminosità, anteprima e campo HEX."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        backdrop_hex: str,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, bg=backdrop_hex, highlightthickness=0)
        self._backdrop = backdrop_hex
        self._on_change_cb = on_change

        self._hue = 0.55
        self._sat = 0.72
        self._val = 0.92

        self._disk_img_pil = _build_saturation_disk(backdrop=self._backdrop)
        self._photo = ImageTk.PhotoImage(self._disk_img_pil, master=master)

        main = tk.Frame(self, bg=self._backdrop, highlightthickness=0)
        main.pack(fill=tk.X)

        wheel_col = tk.Frame(main, bg=self._backdrop, highlightthickness=0)
        wheel_col.pack(side=tk.LEFT, padx=(0, 14))
        tk.Label(
            wheel_col,
            text="Tono e saturazione (clic nella ruota)",
            bg=self._backdrop,
            fg="#333333",
            font=("TkDefaultFont", 9),
            anchor="w",
        ).pack(anchor="w", pady=(0, 2))
        self._cnv = tk.Canvas(
            wheel_col,
            width=_WHEEL_SIZE,
            height=_WHEEL_SIZE,
            highlightthickness=1,
            highlightbackground="#888888",
            bd=0,
            bg=self._backdrop,
        )
        self._cnv.pack()
        self._cnv.create_image(_WHEEL_CENTER, _WHEEL_CENTER, image=self._photo)
        self._cnv.bind("<Button-1>", self._pick_from_event)
        self._cnv.bind("<B1-Motion>", self._pick_from_event)

        sliders = tk.Frame(main, bg=self._backdrop, highlightthickness=0)
        sliders.pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(sliders, text="Luminosità", bg=self._backdrop, fg="#333333").pack(pady=(0, 4))
        self._v_scale = tk.Scale(
            sliders,
            orient=tk.VERTICAL,
            from_=100,
            to=0,
            length=min(240, _WHEEL_SIZE + 12),
            showvalue=False,
            resolution=1,
            highlightthickness=0,
            bg=self._backdrop,
            troughcolor=self._backdrop,
            command=self._on_v_scale_change,
        )
        self._v_scale.pack()
        self._v_scale.set(int(round(self._val * 100.0)))

        right = tk.Frame(main, bg=self._backdrop, highlightthickness=0)
        right.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(right, text="Anteprima e HEX", bg=self._backdrop, fg="#333333", anchor="w").pack(
            anchor="w", pady=(28, 4)
        )

        pv = tk.Frame(right, bg=self._backdrop)
        pv.pack(fill=tk.X, pady=(0, 6))
        self._prev = tk.Canvas(
            pv,
            width=76,
            height=40,
            highlightthickness=1,
            highlightbackground="#666666",
            bd=0,
            bg=self._backdrop,
        )
        self._prev.pack(side=tk.LEFT, padx=(0, 10))
        self._prev_rect = self._prev.create_rectangle(1, 1, 75, 39, outline="", fill="#000000")

        self._hex_var = tk.StringVar(value="#000000")
        hex_row = tk.Frame(right, bg=self._backdrop)
        hex_row.pack(fill=tk.X, pady=(0, 6))
        tk.Label(hex_row, text="HEX", bg=self._backdrop, font=("TkDefaultFont", 9, "bold")).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        self._ent = ttk.Entry(hex_row, textvariable=self._hex_var, width=12, font=("TkFixedFont", 13))
        self._ent.pack(side=tk.LEFT)
        self._ent.bind("<FocusOut>", self._on_hex_entry_commit)
        self._ent.bind("<Return>", self._on_hex_entry_commit)

        btns = tk.Frame(right, bg=self._backdrop)
        btns.pack(fill=tk.X)
        cp = tk.Button(btns, text="Copia negli appunti", command=self._copy_hex, padx=8, pady=3)
        cp.pack(fill=tk.X, pady=(0, 4))
        naive = tk.Button(
            btns,
            text="Apri selettore di sistema…",
            command=self._native_picker,
            padx=8,
            pady=3,
        )
        naive.pack(fill=tk.X)

        tk.Label(
            right,
            text=(
                "Trascina il puntatore sulla ruota: verso il bordo aumenta il colore;"
                " al centro più vicino al bianco. Scorri la luminosità per scurire fino al nero.\n"
                "Puoi anche scrivere o incollare un codice nella casella HEX (formato #RRGGBB, lettere maiuscole o minuscole).\n"
                "«Copia negli appunti» trasferisce sempre un #RRGGBB in minuscolo."
            ),
            fg="#555555",
            bg=self._backdrop,
            font=("TkDefaultFont", 8),
            wraplength=300,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(10, 0))

        self._refresh_outputs()

    def _on_v_scale_change(self, raw: object) -> None:
        try:
            self._val = float(int(str(raw))) / 100.0
        except (TypeError, ValueError):
            self._val = 1.0
        self._refresh_outputs()

    def _current_rgb(self) -> tuple[int, int, int]:
        rf, gf, bf = colorsys.hsv_to_rgb(self._hue % 1.0, max(0.0, min(1.0, self._sat)), self._val)
        return (
            max(0, min(255, int(round(rf * 255.0)))),
            max(0, min(255, int(round(gf * 255.0)))),
            max(0, min(255, int(round(bf * 255.0)))),
        )

    def _on_hex_entry_commit(self, _event: tk.Event | None = None) -> str | None:
        raw = (self._hex_var.get() or "").strip().lower().replace(" ", "")
        if not raw.startswith("#"):
            raw = "#" + raw
        ok = False
        if len(raw) == 7:
            try:
                int(raw[1:], 16)
                ok = True
            except ValueError:
                ok = False
        if not ok:
            self._hex_var.set(_rgb_to_hex(*self._current_rgb()))
            return "break"
        self._apply_from_hex(raw)
        return "break"

    def _pick_from_event(self, event: tk.Event) -> None:
        dx = float(event.x - _WHEEL_CENTER)
        dy = float(event.y - _WHEEL_CENTER)
        self._hue, self._sat = _hsv_from_disk_xy(dx, dy)
        self._refresh_outputs()

    def _marker_coords(self) -> tuple[float, float]:
        udx, udy = _disk_xy_from_hsv(self._hue, self._sat)
        return _WHEEL_CENTER + udx, _WHEEL_CENTER + udy

    def _draw_marker(self) -> None:
        self._cnv.delete("marker")
        mx, my = self._marker_coords()
        r = 6
        self._cnv.create_oval(
            mx - r - 1,
            my - r - 1,
            mx + r + 1,
            my + r + 1,
            outline="#222222",
            width=1,
            tags="marker",
        )
        self._cnv.create_oval(
            mx - r,
            my - r,
            mx + r,
            my + r,
            outline="#ffffff",
            width=2,
            tags="marker",
        )

    def _refresh_outputs(self) -> None:
        r, g, b = self._current_rgb()
        hx = _rgb_to_hex(r, g, b)
        self._hex_var.set(hx)
        try:
            self._prev.itemconfigure(self._prev_rect, fill=hx)
        except tk.TclError:
            pass
        self._draw_marker()
        if self._on_change_cb is not None:
            try:
                self._on_change_cb(hx)
            except Exception:
                pass

    def _copy_hex(self) -> None:
        h = (self._hex_var.get() or "").strip().lower().replace(" ", "")
        if not h.startswith("#"):
            h = "#" + h
        if len(h) != 7:
            return
        try:
            int(h[1:], 16)
        except ValueError:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(h)
        except tk.TclError:
            pass

    def _native_picker(self) -> None:
        try:
            from tkinter import colorchooser
        except ImportError:
            return
        init = (self._hex_var.get() or "").strip()
        if not (len(init) == 7 and init.startswith("#")):
            init = "#808080"
        try:
            res = colorchooser.askcolor(color=init, title="Colore", parent=self.winfo_toplevel())
        except Exception:
            return
        if res and res[1]:
            hx = str(res[1]).lower()
            if len(hx) == 7 and hx.startswith("#"):
                self._apply_from_hex(hx)

    def _apply_from_hex(self, hx: str) -> None:
        hx = (hx or "").strip().lower().replace(" ", "")
        if not hx.startswith("#"):
            hx = "#" + hx
        if len(hx) != 7:
            return
        try:
            r = int(hx[1:3], 16)
            g = int(hx[3:5], 16)
            b = int(hx[5:7], 16)
        except (ValueError, IndexError):
            return
        fr, fg, fb = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(fr, fg, fb)
        self._hue = h % 1.0
        self._sat = max(0.0, min(1.0, s))
        self._val = max(0.0, min(1.0, v))
        try:
            self._v_scale.set(int(round(self._val * 100.0)))
        except tk.TclError:
            pass
        self._refresh_outputs()


def pack_round_color_wheel_for_opzioni(
    parent: tk.Misc,
    *,
    section_bg: str,
    title_font: tuple,
) -> None:
    """Inserisce un blocco collassabile sotto ``parent`` (tipicamente ``ttk.LabelFrame`` Opzioni)."""
    sub = ttk.LabelFrame(parent, padding=(10, 8))
    sub.configure(
        labelwidget=ttk.Label(sub, text="Palette rotonda e codice esadecimale", font=title_font)
    )
    sub.pack(fill=tk.X, pady=(0, 12))
    inner = tk.Frame(sub, bg=section_bg, highlightthickness=0)
    inner.pack(fill=tk.X)
    picker = RoundHsvWheelPicker(inner, backdrop_hex=section_bg)
    picker.pack(fill=tk.X)


__all__ = [
    "RoundHsvWheelPicker",
    "pack_round_color_wheel_for_opzioni",
]
