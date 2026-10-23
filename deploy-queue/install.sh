#!/bin/bash
# Установка очереди проливки. С Мака из корня stt-agents: bash deploy-queue/install.sh
# Сервер: CLI в /usr/local/bin, очередь /var/lib/deploy-queue (agents), допуш веток раз в 5 минут.
# Мак: скрипт копией в ~/.local/bin (не зависит от ветки, на которой стоит клон), launchd com.example.deploy-queue.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
VPS=root@<VPS>
scp -q "$here/deploy-queue" "$VPS:/tmp/deploy-queue"
ssh "$VPS" 'set -e
  install -m 755 /tmp/deploy-queue /usr/local/bin/deploy-queue && rm /tmp/deploy-queue
  install -d -o agents -g agents -m 755 /var/lib/deploy-queue
  printf "SHELL=/bin/bash\nMAILTO=\"\"\n*/5 * * * * agents /usr/local/bin/deploy-queue flush >/dev/null 2>&1\n" >/etc/cron.d/deploy-queue
  deploy-queue --help | head -3'
install -d ~/.local/bin
install -m 755 "$here/deploy-queue-mac" ~/.local/bin/deploy-queue-mac
plist=~/Library/LaunchAgents/com.example.deploy-queue.plist
cp "$here/com.example.deploy-queue.plist" "$plist"
launchctl bootout "gui/$(id -u)/com.example.deploy-queue" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "Мак: launchd com.example.deploy-queue, лог ~/Library/Logs/deploy-queue.log"
