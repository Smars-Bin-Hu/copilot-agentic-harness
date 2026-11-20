#!/bin/sh
# Double-click on macOS: starts the task board of this copy in the background. The board keeps running when this window is closed; stop it with the button on its pages.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Harness needs Python 3.9 or newer. Install it, then double-click Start Harness again."
  printf "Press Enter to close this window. "
  read -r _
  exit 1
fi
echo "Starting the harness board. On a slow computer this takes a little while: the browser opens when it is ready."
sh .harness/bin/harness task board --background --splash
code=$?
if [ "$code" -ne 0 ]; then
  printf "The board did not start. Press Enter to close this window. "
  read -r _
  exit "$code"
fi
echo "The board keeps running in the background. You can close this window."
