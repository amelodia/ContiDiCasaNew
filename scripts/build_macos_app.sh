#!/usr/bin/env bash
# Crea dist/ContiDiCasa.app (macOS) con PyInstaller. Richiede Python 3 dal venv o da PATH.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Questo script è pensato per macOS (Darwin)." >&2
  exit 1
fi

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/.venv/bin/activate"
fi

python3 -c "import PyInstaller" 2>/dev/null || {
  echo "Installo PyInstaller nel Python corrente…" >&2
  python3 -m pip install --upgrade pip
  python3 -m pip install "pyinstaller>=6.0"
}

python3 -m pip install -r "$ROOT/requirements.txt"

python3 "$ROOT/scripts/bump_version_build.py"

rm -rf "$ROOT/build" "$ROOT/dist/ContiDiCasa" "$ROOT/dist/ContiDiCasa.app"

mkdir -p "$ROOT/build"
export PYINSTALLER_CONFIG_DIR="$ROOT/build/pyinstaller-cache"
export MPLCONFIGDIR="$ROOT/build/matplotlib-cache"
mkdir -p "$PYINSTALLER_CONFIG_DIR" "$MPLCONFIGDIR"
if ! python3 "$ROOT/scripts/build_euro_icns.py" "$ROOT/build/ContiDiCasa.icns"; then
  echo "Avviso: generazione .icns non riuscita; il bundle userà l'icona predefinita." >&2
fi

python3 -m PyInstaller --noconfirm "$ROOT/ContiDiCasa.spec"

echo >&2
echo "Fatto: $ROOT/dist/ContiDiCasa.app" >&2
echo "Primo avvio: tasto ctrl su icona → Apri (Gatekeeper non firmato), oppure: codesign -s - --deep dist/ContiDiCasa.app" >&2
