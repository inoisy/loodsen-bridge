#!/usr/bin/env bash
# Установка bridge-mux на сервер агентов. С Мака:
#   scp -q -r bridge root@<VPS>:/tmp/ && ssh root@<VPS> bash /tmp/bridge/install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
SRC=$(cd "$(dirname "$0")" && pwd)
python3 -I -m py_compile "$SRC/bridge-mux"
install -o root -g root -m 755 "$SRC/bridge-mux" /usr/local/bin/bridge-mux
install -o root -g root -m 644 "$SRC/bridge-mux.service" /etc/systemd/system/bridge-mux.service
install -o root -g root -m 644 "$SRC/vps/60-bridge.conf" /etc/ssh/sshd_config.d/60-bridge.conf
sshd -t
[[ -f /etc/bridge-mux.json ]] || { echo '{"users": []}' > /etc/bridge-mux.json; chmod 644 /etc/bridge-mux.json; }
systemctl daemon-reload
systemctl reload ssh
systemctl enable bridge-mux
systemctl restart bridge-mux
sleep 2; systemctl --no-pager -n 20 status bridge-mux | tail -n 12
