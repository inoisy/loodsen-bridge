#!/usr/bin/env bash
# После проверки шлюза: креды Grafana, токен Sentry и cookie сессий Grafana с сервера — удалить.
# Копии у владельца: Grafana — связка ключей Мака (grafana-stage-company), Sentry — новый токен там же
# (sentry-company); старый токен Sentry отозвать в UI (User settings → Auth Tokens).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "нужен root"; exit 1; }
for f in /etc/grafana-agents/creds /etc/sentry-agents/token /var/lib/grafana-agents/*.cookies; do
  [[ -f "$f" ]] && shred -u "$f" && echo "удалён $f"
done
rmdir /etc/grafana-agents /etc/sentry-agents /var/lib/grafana-agents 2>/dev/null || true
# Проверка: ни файлов кредов, ни похожих на них строк
grep -rlIE 'GRAFANA_PASSWORD|sntry[su]_[A-Za-z0-9]' /etc /home/agents 2>/dev/null | grep -v '^/home/agents/multica_workspaces/' || echo "grep: секретов Grafana/Sentry нет"
