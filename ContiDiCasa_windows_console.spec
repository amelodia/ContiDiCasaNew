# PyInstaller — build Windows di diagnostica (console visibile per errori).
# Uso: pyinstaller ContiDiCasa_windows_console.spec

import os

_spec_dir = os.path.dirname(os.path.abspath(SPEC))
_base_spec = os.path.join(_spec_dir, "ContiDiCasa_windows.spec")
with open(_base_spec, encoding="utf-8") as f:
    _code = f.read()
_code = _code.replace("console=False", "console=True", 1)
exec(compile(_code, _base_spec, "exec"))
