#!/usr/bin/env bash
# Шлюз наблюдаемости на сервере агентов. С Мака (из корня stt-agents):
#   tar czf - obs-gw grafana sentry bridge | ssh root@<VPS> 'rm -rf /tmp/obs && mkdir /tmp/obs && tar xzf - -C /tmp/obs && bash /tmp/obs/obs-gw/install-vps.sh'
# Что делает: obs-gw (systemd, User=obs-gw, :18482), сервис obs в bridge-mux (:18448 → слот владельца 20248),
# обёртки grafana/sentry без кредов. Секреты не трогает — их убирает remove-secrets.sh после проверки.
# Откат — /var/backups/obs-gw.<время>/rollback.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
SRC=$(cd "$(dirname "$0")/.." && pwd)
B=/var/backups/obs-gw.$(date -u +%Y%m%dT%H%M%SZ); install -d -m 700 "$B"
for f in /usr/local/bin/grafana /usr/local/bin/sentry /usr/local/bin/bridge-mux /etc/bridge-mux.json /var/lib/bridge/.ssh/authorized_keys; do
  cp -a "$f" "$B/$(echo "$f" | tr / _)"
done
cat > "$B/rollback.sh" <<RB
#!/usr/bin/env bash
# Откат obs-gw: обёртки и bridge-mux как были, шлюз остановлен. На Маке — obs-gw/rollback-mac.sh.
set -eu
systemctl disable --now obs-gw 2>/dev/null || true
rm -f /etc/systemd/system/obs-gw.service /usr/local/bin/obs-gw; systemctl daemon-reload
for f in /usr/local/bin/grafana /usr/local/bin/sentry /usr/local/bin/bridge-mux /etc/bridge-mux.json /var/lib/bridge/.ssh/authorized_keys; do
  cp -a "$B/\$(echo "\$f" | tr / _)" "\$f"
done
systemctl restart bridge-mux
echo "откат сделан; секреты, если удалены, кладёт владелец заново (/etc/grafana-agents/creds, /etc/sentry-agents/token)"
RB
chmod 700 "$B/rollback.sh"

for f in obs-gw/obs-gw grafana/grafana sentry/sentry bridge/bridge-mux; do python3 -I -m py_compile "$SRC/$f"; done
id obs-gw >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin obs-gw
install -o root -g root -m 755 "$SRC/obs-gw/obs-gw" /usr/local/bin/obs-gw
install -o root -g root -m 644 "$SRC/obs-gw/obs-gw.service" /etc/systemd/system/obs-gw.service
install -o root -g root -m 755 "$SRC/grafana/grafana" /usr/local/bin/grafana
install -o root -g root -m 755 "$SRC/sentry/sentry" /usr/local/bin/sentry
install -o root -g root -m 755 "$SRC/bridge/bridge-mux" /usr/local/bin/bridge-mux
install -o root -g root -m 644 "$SRC/bridge/README.md" /usr/local/share/doc/bridge-mux/README.md
bridge-mux user services evgeniy sphere,kc,git01,dev,time,obs   # пересобирает authorized_keys: +permitlisten 127.0.0.1:20248
systemctl daemon-reload
systemctl enable --now obs-gw
systemctl restart bridge-mux     # новый постоянный адрес 127.0.0.1:18448; рвёт только идущие через мост соединения
sleep 3
systemctl is-active obs-gw bridge-mux
bridge-mux status
echo "бэкап и откат: $B/rollback.sh"
