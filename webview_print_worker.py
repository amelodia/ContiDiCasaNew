#!/usr/bin/env python3
"""
Sottoprocesso Windows: apre un file HTML locale in pywebview (Edge WebView2)
e invoca window.print() per mostrare la finestra di stampa del sistema.

Avvio: python webview_print_worker.py <path_assoluto_file.html>
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    html_path = Path(sys.argv[1]).resolve()
    if not html_path.is_file():
        return 3
    url = html_path.as_uri()

    try:
        import webview
    except ImportError:
        return 4

    window_holder: list = []

    def on_loaded() -> None:
        try:
            w = window_holder[0]
            w.evaluate_js("setTimeout(function(){ window.print(); }, 400);")
        except Exception:
            pass

    try:
        window = webview.create_window("Stampa saldi", url, on_top=True)
        window_holder.append(window)
        window.events.loaded += on_loaded
        webview.start()
    finally:
        try:
            html_path.unlink(missing_ok=True)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
