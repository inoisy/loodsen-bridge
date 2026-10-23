# Мост Мак → сервер агентов

Один ssh-туннель с Мака (`com.example.sphere-bridge`) пробрасывает на VPS Сферу, Keycloak, git01 и dev-контур Лоции. Сервер ходит туда через `127.0.0.1:<порт>` и `192.168.200.1:<порт>`; Мак спит — моста нет, работа ждёт в очередях.

| Файл | Где живёт | Что делает |
|---|---|---|
| `mac/com.example.sphere-bridge.plist` | Мак, `~/Library/LaunchAgents` | `ssh -N -R …` на сервер под пользователем `bridge` |
| `mac/com.example.time-gw.plist` | Мак, `~/Library/LaunchAgents` | запускает `time-gw/time-gw-mac` |
| `vps/60-bridge.conf` | VPS, `/etc/ssh/sshd_config.d/` | пользователь `bridge` без шелла, только remote-forward |
| `vps/60-git01-bridge.conf` | VPS, `/etc/ssh/ssh_config.d/` | `git@<git01>` → `127.0.0.1:18422` |
| `vps/kc-bridge-nat.service`, `vps/dev-bridge-nat.service` | VPS, `/etc/systemd/system/` | DNAT Keycloak и dev-контура на порты туннеля |

Остальной код моста — в соседних каталогах: `sphere-gw/` (шлюз Сферы), `time-gw/` (шлюз Time), `deploy-queue/` (очередь проливки). Устройство и откат — `docs/ops.md`, раздел про мост.

## Публичная копия

`bridge/export-public.sh <каталог>` собирает из монорепы `sphere-gw/`, `time-gw/`, `deploy-queue/` и `bridge/` в чистый каталог для публичного репозитория: заменяет внутренние адреса на плейсхолдеры, ищет секреты и остатки внутренних имён. Найдёт хоть одно — остановится. Публикация — отдельным шагом, руками.
