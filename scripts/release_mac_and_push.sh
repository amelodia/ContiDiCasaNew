#!/usr/bin/env bash
# Aggiorna git + build Mac + push (Windows CI su cursor/**).
# Uso:
#   bash scripts/release_mac_and_push.sh
#   bash scripts/release_mac_and_push.sh "04 08 26"
set -euo pipefail

DATA="${1:-$(date '+%d %m %y')}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Questo script va eseguito su Mac." >&2
  exit 1
fi

git checkout cursor/unify-1122

python3 scripts/bump_version_build.py

git add -u
git add \
  scripts/inspect_verification_regs.py \
  scripts/remediate_verification_floor_notes.py \
  tests/test_reanchor_double_star_account_change.py \
  tests/test_verification_double_star_chain.py \
  2>/dev/null || true
git reset HEAD -- .cursor/debug-*.log 2>/dev/null || true

git status -sb

if git diff --cached --quiet; then
  echo "Nessun file nuovo da commitare (ok se già committato)."
else
  git commit -m "versione x ${DATA} — Desktop Mac/Windows Conti di Casa."
fi

git push -u origin HEAD

bash scripts/build_macos_app.sh
codesign -s - --deep dist/ContiDiCasa.app

rm -rf /Applications/ContiDiCasa.app
cp -R dist/ContiDiCasa.app /Applications/

echo
echo "Mac OK: /Applications/ContiDiCasa.app"
echo "Windows: https://github.com/amelodia/cursorappmaccdc/actions"
echo "  → workflow Windows build → scarica zip e Setup.exe"
