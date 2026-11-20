#!/bin/sh
# Double-click on macOS: starts the task board of this copy in the background, with a small start window; this Terminal window is hidden meanwhile and closed at the end (shown again when the start failed). The board keeps running; stop it with the button on its pages.
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
# The start window hid this Terminal window; close it once this script has ended (a running script would make Terminal ask first).
if [ "$TERM_PROGRAM" = "Apple_Terminal" ] && tty=$(tty 2>/dev/null); then
  nohup osascript -e "delay 0.5" -e "tell application \"Terminal\"" -e "repeat with w in windows" -e "if tty of selected tab of w is \"$tty\" then close w" -e "end repeat" -e "end tell" >/dev/null 2>&1 &
fi
