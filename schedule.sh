#!/bin/sh
# Install / remove the scheduled jobs (macOS launchd). Never run by Claude without an explicit request (CLAUDE.md).
#   ./schedule.sh install     morning summary Mon–Fri 08:30 (morning_job.py: a window with today's macro events,
#                             upcoming earnings of my stocks, positions to review, missing diary days) + evening job
#                             Mon–Fri 22:45 (daily_job.py: evening report, signal diary, picture of the portfolio)
#   ./schedule.sh remove
#   ./schedule.sh run         run the evening job now (same environment as the schedule)
#   ./schedule.sh status      show whether the jobs are installed and the end of their logs
# If the Mac is asleep at the scheduled time, macOS runs the job when it wakes up; if it is off, that run is skipped.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
MORNING="com.nasdaq100.signals"         # 08:30 morning summary (same label as before, so a new install replaces the old report)
EVENING="com.nasdaq100.daily"           # 22:45 evening job

plist() {   # label, script, hour, minute
  TIMES=""
  for d in 1 2 3 4 5; do
    TIMES="$TIMES<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$3</integer><key>Minute</key><integer>$4</integer></dict>"
  done
  EXTRA=""
  cat > "$AGENTS/$1.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/$2</string>$EXTRA</array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><array>$TIMES</array>
  <key>StandardOutPath</key><string>$DIR/reports/logs/${2%.py}.log</string>
  <key>StandardErrorPath</key><string>$DIR/reports/logs/${2%.py}.err</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONWARNINGS</key><string>ignore</string><key>LANG</key><string>en_US.UTF-8</string></dict>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$1.plist"
}

case "$1" in
  install)
    [ -x "$PY" ] || { echo "Missing $PY: run ./run.sh once first to create the .venv"; exit 1; }
    mkdir -p "$DIR/reports/logs" "$AGENTS"
    plist "$MORNING" morning_job.py 8 30
    plist "$EVENING" daily_job.py 22 45
    echo "Installed: $MORNING Mon–Fri 08:30, $EVENING Mon–Fri 22:45 ($(date +%Z))"
    ;;
  remove)
    for l in "$MORNING" "$EVENING"; do launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true; rm -f "$AGENTS/$l.plist"; done
    echo "Removed $MORNING and $EVENING"
    ;;
  run)
    launchctl kickstart -p "gui/$(id -u)/$EVENING"
    ;;
  status)
    for l in "$MORNING" "$EVENING"; do
      if launchctl print "gui/$(id -u)/$l" >/dev/null 2>&1; then echo "$l: installed"; else echo "$l: NOT installed"; fi
    done
    for f in morning_job daily_job; do
      [ -f "$DIR/reports/logs/$f.log" ] && { echo "--- reports/logs/$f.log (last lines)"; tail -n 5 "$DIR/reports/logs/$f.log"; }
      [ -s "$DIR/reports/logs/$f.err" ] && { echo "--- reports/logs/$f.err (last lines)"; tail -n 5 "$DIR/reports/logs/$f.err"; }
    done
    true
    ;;
  *) echo "usage: $0 install|remove|run|status"; exit 1 ;;
esac
