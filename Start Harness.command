#!/bin/sh
# Double-click on macOS: starts the task board of this copy. Keep this window open while you work.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Harness needs Python 3.9 or newer. Install it, then double-click Start Harness again."
  printf "Press Enter to close this window. "
  read -r _
  exit 1
fi
sh .harness/bin/harness task board
code=$?
if [ "$code" -ne 0 ] && [ "$code" -ne 130 ]; then
  printf "The board stopped with an error. Press Enter to close this window. "
  read -r _
fi
exit "$code"
