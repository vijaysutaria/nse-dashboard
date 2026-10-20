#!/bin/zsh
# Control the NSE dashboard login service (launchd). It starts at login and restarts if it crashes.
# Usage: ./dashboard.sh start | stop | restart | status
LABEL="com.vijaysutaria.nse-dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TARGET="gui/$(id -u)/$LABEL"
URL="http://localhost:8501"

case "$1" in
  start)
    launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl kickstart "$TARGET"
    echo "Started at $URL (runs at every login)"
    ;;
  stop)
    launchctl bootout "$TARGET" 2>/dev/null && echo "Stopped (will start again at next login)" || echo "Not running"
    ;;
  restart)
    launchctl kickstart -k "$TARGET" && echo "Restarted at $URL"
    ;;
  status)
    if launchctl print "$TARGET" 2>/dev/null | grep -q "state = running"; then
      echo "Running at $URL"
    else
      echo "Not running"
    fi
    ;;
  *)
    echo "Usage: $0 start | stop | restart | status"; exit 1
    ;;
esac
