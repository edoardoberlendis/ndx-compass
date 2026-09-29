#!/bin/sh
# Install / remove the twice-daily report job (macOS launchd).
#   ./schedule.sh install     runs signals.py Mon–Fri at 08:30 (pre-market) and 22:30 (after the US close), local time
#   ./schedule.sh remove
#   ./schedule.sh run         trigger the job now (same environment as the schedule)
# On weekends and US market holidays (market_calendar.py) signals.py exits without writing a report.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.nasdaq100.signals"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="$DIR/.venv/bin/python"

case "$1" in
  install)
    [ -x "$PY" ] || { echo "Missing $PY: run ./run.sh once first to create the .venv"; exit 1; }
    mkdir -p "$DIR/reports/logs"
    TIMES=""
    for d in 1 2 3 4 5; do
      for hm in "8 30" "22 30"; do
        set -- $hm
        TIMES="$TIMES<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$1</integer><key>Minute</key><integer>$2</integer></dict>"
      done
    done
    cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/signals.py</string><string>--notify</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><array>$TIMES</array>
  <key>StandardOutPath</key><string>$DIR/reports/logs/signals.log</string>
  <key>StandardErrorPath</key><string>$DIR/reports/logs/signals.err</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONWARNINGS</key><string>ignore</string><key>LANG</key><string>en_US.UTF-8</string></dict>
</dict></plist>
PL
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "Installed $LABEL: Mon–Fri 08:30 and 22:30 ($(date +%Z))"
    ;;
  remove)
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL"
    ;;
  run)
    launchctl kickstart -p "gui/$(id -u)/$LABEL"
    ;;
  *) echo "usage: $0 install|remove|run"; exit 1 ;;
esac
