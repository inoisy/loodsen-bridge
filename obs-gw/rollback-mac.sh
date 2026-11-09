#!/usr/bin/env bash
# Откат на Маке: мост без форварда obs (последний бэкап plist), obs-gw-mac выключен.
set -eu
LA=~/Library/LaunchAgents; U=gui/$(id -u)
B=$(ls -t $LA/com.example.sphere-bridge.plist.bak-*-obs 2>/dev/null | head -1)
[ -n "$B" ] && cp -p "$B" $LA/com.example.sphere-bridge.plist && { launchctl bootout $U/com.example.sphere-bridge 2>/dev/null; sleep 1; launchctl bootstrap $U $LA/com.example.sphere-bridge.plist; }
launchctl bootout $U/com.example.obs-gw 2>/dev/null || true
rm -f $LA/com.example.obs-gw.plist
echo "Мак откатан (plist моста: ${B:-без изменений})"
