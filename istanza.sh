#!/bin/zsh
# Istanza separata di Nasdaq-100 Monitor (Fase 9A): avvio in background, arresto, stato, verifica, backup.
# Non installa nessun servizio automatico e non tocca la dashboard personale (8100) né il job delle 23:00.
#
#   ./istanza.sh avvia    ~/NasdaqMonitor-istanze/utente2
#   ./istanza.sh ferma    ~/NasdaqMonitor-istanze/utente2
#   ./istanza.sh stato    ~/NasdaqMonitor-istanze/utente2
#   ./istanza.sh verifica ~/NasdaqMonitor-istanze/utente2
#   ./istanza.sh backup   ~/NasdaqMonitor-istanze/utente2 ~/Backup/utente2-$(date +%F).tar.gz
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
cmd="${1:-}"; dir="${2:-}"
[[ -n "$cmd" && -n "$dir" ]] || { echo "uso: $0 avvia|ferma|stato|verifica|backup CARTELLA [DESTINAZIONE]"; exit 2; }
dir="$(cd "$dir" && pwd -P)"
case "$cmd" in
  avvia)
    "$PY" "$HERE/instance.py" verifica "$dir"
    mkdir -p "$dir/logs"; chmod 700 "$dir/logs"
    nohup "$PY" "$HERE/instance.py" avvia "$dir" >>"$dir/logs/avvio.log" 2>&1 &
    sleep 3
    "$PY" "$HERE/instance.py" stato "$dir" ;;
  ferma|stato|verifica) "$PY" "$HERE/instance.py" "$cmd" "$dir" ;;
  backup) "$PY" "$HERE/instance.py" backup "$dir" "${3:?manca la destinazione del backup}" ;;
  *) echo "comando sconosciuto: $cmd"; exit 2 ;;
esac
