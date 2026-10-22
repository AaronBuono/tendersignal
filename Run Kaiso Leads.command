#!/bin/bash
# Double-click this file to refresh the Kaiso lead list. First run sets everything up (a few
# minutes); after that it takes as long as the registry lookups need.

cd "$(dirname "$0")/tender-cert-signal" || exit 1

pause() { echo; read -r -p "Press Enter to close this window..." _; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 isn't installed on this Mac."
  echo "Open Terminal, run:  xcode-select --install   — then double-click this file again."
  pause; exit 1
fi

# First-time setup (only repeats if the project's dependencies change).
if [ ! -x .venv/bin/tendersignal ] || [ pyproject.toml -nt .venv/.installed ]; then
  echo "Setting up (first run only)..."
  python3 -m venv .venv || { echo "Could not create the Python environment."; pause; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -e . || { echo "Install failed — check your internet connection."; pause; exit 1; }
  touch .venv/.installed
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created a settings file (tender-cert-signal/.env). Optional: add your Google Sheet details"
  echo "(see sheets/SETUP.md) and a free ABN Lookup GUID to filter out sole traders."
  echo
fi

./.venv/bin/tendersignal go
status=$?

if [ $status -eq 0 ] && [ -f leads.csv ]; then
  SHEET_VIEW_URL=$(grep -E '^SHEET_VIEW_URL=' .env 2>/dev/null | head -1 | cut -d= -f2-)
  if [ -n "$SHEET_VIEW_URL" ]; then open "$SHEET_VIEW_URL"; else open leads.csv; fi
fi
pause
exit $status
