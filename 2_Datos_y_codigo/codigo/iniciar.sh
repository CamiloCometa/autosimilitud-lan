#!/usr/bin/env bash
# Autosimilitud LAN - iniciador para Linux/macOS (doble clic o ./iniciar.sh)
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Preparando el programa por primera vez..."
  python3 -m venv .venv
fi
if [ ! -f .venv/.deps_ok ]; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
  touch .venv/.deps_ok
fi
exec .venv/bin/python app_gui.py
