#!/bin/bash
set -eu
cd "$(dirname "$(readlink -f "$0")")/.."
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 was not found."
    read -r
    exit 1
fi
python3 deck/deck_setup.py
echo
read -rp "Press Enter to close..."
