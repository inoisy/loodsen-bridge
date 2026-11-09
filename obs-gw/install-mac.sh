#!/usr/bin/env bash
# Мак владельца: obs-gw-mac (launchd com.example.obs-gw) и форвард obs в мосту. Сначала install-vps.sh —
# без permitlisten 20248 мост с ExitOnForwardFailure не встанет. Откат — rollback-mac.sh.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); LA=~/Library/LaunchAgents; U=gui/$(id -u)
install -d ~/.local/libexec
install -m 755 "$HERE/obs-gw-mac" ~/.local/libexec/obs-gw-mac
install -m 644 "$HERE/../bridge/mac/com.example.obs-gw.plist" $LA/com.example.obs-gw.plist
launchctl bootout $U/com.example.obs-gw 2>/dev/null || true
launchctl bootstrap $U $LA/com.example.obs-gw.plist
sleep 1; curl -sf http://127.0.0.1:18491/health && echo " obs-gw-mac ok"
P=$LA/com.example.sphere-bridge.plist
if ! grep -q '127.0.0.1:20248:' $P; then
  cp -p $P $P.bak-$(date +%Y%m%d-%H%M%S)-obs
  /usr/bin/sed -i '' 's|    <string>bridge@<VPS></string>|    <string>-R</string><string>127.0.0.1:20248:127.0.0.1:18491</string>\
    <string>bridge@<VPS></string>|' $P
  plutil -lint $P
fi
# рестарт моста: Сфера, git01, dev, Time у сервера пропадают на несколько секунд.
# kickstart не перечитывает plist — только bootout + bootstrap.
launchctl bootout $U/com.example.sphere-bridge 2>/dev/null || true; sleep 1
launchctl bootstrap $U $P
sleep 5; tail -n 3 ~/Library/Logs/sphere-bridge.log
