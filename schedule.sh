#!/bin/sh
# Install / remove the scheduled jobs (macOS launchd). Never run by Claude without an explicit request (CLAUDE.md).
#   ./schedule.sh install     morning summary Mon–Fri 08:30 (morning_job.py: a window with today's macro events,
#                             upcoming earnings of my stocks, positions to review, missing diary days) + evening job
#                             Mon–Fri 22:45 (daily_job.py: evening report, signal diary, picture of the portfolio)
#   ./schedule.sh remove
#   ./schedule.sh run         run the evening job now (same environment as the schedule)
#   ./schedule.sh status      show whether the jobs are installed and the end of their logs
# Phase 8B, MARKET-ONLY job (public market data only, never portafoglio/), separate label: it never installs, replaces or
# removes the two jobs above, and install/remove above never touch it.
#   ./schedule.sh install-market   evening market-only job Mon–Fri 23:00 local time (daily_job.py --market-only)
#   ./schedule.sh remove-market    removes ONLY the market-only job
#   ./schedule.sh status-market    installed or not, effective schedule and arguments read back from launchd, last runs
# If the Mac is asleep at the scheduled time, macOS runs the job when it wakes up; if it is off, that run is skipped.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
AGENTS="$HOME/Library/LaunchAgents"
MORNING="com.nasdaq100.signals"         # 08:30 morning summary (same label as before, so a new install replaces the old report)
EVENING="com.nasdaq100.daily"           # 22:45 evening job
MARKET="com.nasdaq100.market"           # 23:00 market-only evening job (phase 8B)
MARKET_H=23; MARKET_M=0

plist() {   # label, script, hour, minute [, log name, extra argument]
  TIMES=""
  for d in 1 2 3 4 5; do
    TIMES="$TIMES<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>$3</integer><key>Minute</key><integer>$4</integer></dict>"
  done
  LOG="${5:-${2%.py}}"
  EXTRA=""
  [ -n "$6" ] && EXTRA="<string>$6</string>"
  cat > "$AGENTS/$1.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$DIR/$2</string>$EXTRA</array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>StartCalendarInterval</key><array>$TIMES</array>
  <key>StandardOutPath</key><string>$DIR/reports/logs/$LOG.log</string>
  <key>StandardErrorPath</key><string>$DIR/reports/logs/$LOG.err</string>
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
  install-market)
    [ -x "$PY" ] || { echo "Missing $PY: run ./run.sh once first to create the .venv"; exit 1; }
    mkdir -p "$DIR/reports/logs" "$AGENTS"
    plist "$MARKET" daily_job.py "$MARKET_H" "$MARKET_M" daily_job_market --market-only
    echo "Installed: $MARKET Mon–Fri $(printf %02d:%02d "$MARKET_H" "$MARKET_M") ($(date +%Z)), daily_job.py --market-only"
    echo "Not touched: $MORNING and $EVENING"
    ;;
  remove-market)
    launchctl bootout "gui/$(id -u)/$MARKET" 2>/dev/null || true
    rm -f "$AGENTS/$MARKET.plist"
    echo "Removed $MARKET (not touched: $MORNING and $EVENING)"
    ;;
  status-market)
    if launchctl print "gui/$(id -u)/$MARKET" >/dev/null 2>&1; then
      echo "$MARKET: installed"
      echo "--- effective schedule and arguments (from launchd)"
      launchctl print "gui/$(id -u)/$MARKET" | grep -E "Weekday|Hour|Minute|arguments|--market-only|daily_job|state|last exit" || true
    else
      echo "$MARKET: NOT installed"
    fi
    [ -f "$AGENTS/$MARKET.plist" ] && { echo "--- $AGENTS/$MARKET.plist"; plutil -p "$AGENTS/$MARKET.plist" | grep -E "Label|market-only|Hour|Minute|Weekday" ; }
    if launchctl print "gui/$(id -u)/$EVENING" >/dev/null 2>&1; then
      echo "Note: $EVENING (full evening job, 22:45) is installed too: the public part would run twice (harmless, the diaries are idempotent)."
    fi
    for f in daily_job_market; do
      [ -f "$DIR/reports/logs/$f.log" ] && { echo "--- reports/logs/$f.log (last lines)"; tail -n 8 "$DIR/reports/logs/$f.log"; }
      [ -s "$DIR/reports/logs/$f.err" ] && { echo "--- reports/logs/$f.err (last lines)"; tail -n 8 "$DIR/reports/logs/$f.err"; }
    done
    "$PY" -c "import job_status as j; r=j.last('market-only'); print('--- last market-only run:', 'none' if not r else (r['startedAt'], 'completed' if r.get('completed') else 'NOT completed', r.get('finishedAt')))" 2>/dev/null || true
    true
    ;;
  *) echo "usage: $0 install|remove|run|status|install-market|remove-market|status-market"; exit 1 ;;
esac
