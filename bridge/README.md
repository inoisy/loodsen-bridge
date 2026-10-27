# bridge-mux — мосты в рабочую сеть от нескольких сотрудников

Сервер агентов (<VPS>) в рабочую сеть Лоции сам не ходит. Сфера, Keycloak `sso2`, git01 и
dev-контур `*.<dev-domain>` доступны ему только через обратные SSH-туннели с машин сотрудников, которые
сидят под рабочим VPN. До 27.10.2026 слот был один: туннель держал один человек на постоянных портах,
и второй мог только выбить первого. Когда тот уходил офлайн, мостов не было ни у кого.

Теперь у каждого сотрудника свой **слот**. `bridge-mux` слушает постоянные адреса и отдаёт каждое
соединение первому живому слоту по приоритету. Мост держат двое — уснул один, работает второй.

```
клиенты сервера ──► 127.0.0.1:18543 ┐                       ┌─► 127.0.0.1:20143 ─ssh -R─► сотрудник 1 ─VPN─► <sphere-host>:443
(sphere-gw, git,    192.168.200.1:… ├─ bridge-mux ─ живой? ─┤
 NAT kc/dev, time)  127.0.0.1:18422 ┘                       └─► 127.0.0.1:20243 ─ssh -R─► сотрудник 2 ─VPN─► …
```

## Порты

Слот N, сервис со смещением K → `127.0.0.1:(20000 + 100·N + K)`.

| сервис | K | постоянный адрес на сервере | цель туннеля у сотрудника |
|---|---|---|---|
| `sphere` | 43 | `127.0.0.1:18543`, `192.168.200.1:18543` (`sphere-gw`) | `<sphere-host>:443` |
| `kc` | 44 | `127.0.0.1:18444`, `192.168.200.1:18444` | `<sso-host>:443` |
| `git01` | 22 | `127.0.0.1:18422` | `<git01-host>:22` |
| `dev` | 50 | `192.168.200.1:18450` | `<internal-ip>:443` |
| `time` | 47 | `127.0.0.1:18447` | `127.0.0.1:18490`: `time-gw-mac`, есть только у владельца |

Постоянные адреса `kc`, `git01`, `dev` и `time` не изменились, поэтому `ssh_config` для git01,
`kc-bridge-nat` и `dev-bridge-nat` не трогали. У Сферы bridge-mux слушает `18543`: на этот порт ходит
`sphere-gw` (по умолчанию `SPHERE_UPSTREAM`), а `18443` оставлен старому клиенту.

**Старый клиент (`legacy`).** Человек, который ещё не перешёл на команду слота, держит
`-R 127.0.0.1:18443 -R 192.168.200.1:18443` → Сфера. Ждать, пока он её поменяет, не нужно:
`bridge-mux user legacy <имя> on` пускает его ключ на эти адреса (только Сфера), и bridge-mux берёт
`18443` как ещё один слот. Он может быть только у одного человека. Когда тот поставит
`bridge-mux client <имя>`, выполни `bridge-mux user legacy <имя> off`, и человек вернётся на свой слот
со всеми сервисами. Для этого в `60-bridge.conf` стоит `GatewayPorts clientspecified`: без него sshd
вешает `192.168.200.1:18443` на loopback. Адреса по-прежнему режет `permitlisten`.

**Живость.** Раз в 20 с через туннель каждого слота идёт проба: TLS-рукопожатие для `sphere`/`kc`/`dev`,
SSH-баннер для `git01`, HTTP-ответ для `time`. Слот, у которого порт слушает, а машина спит, мёртв.
Соединение идёт сначала в живые слоты по приоритету, потом в остальные. sshd гасит сессию уснувшей
машины за ~45 с (`ClientAliveInterval 15` × 3), и слот освобождается для её же переподключения.

Приоритет задаёт порядок `users` в `/etc/bridge-mux.json`.

## Подключить сотрудника

Памятка для самого сотрудника — [CONNECT.md](CONNECT.md).

1. Сотрудник делает ключ и присылает **публичную** половину:
   ```bash
   ssh-keygen -t ed25519 -N '' -C "multica-bridge@<имя>" -f ~/.ssh/id_ed25519_multica_bridge
   cat ~/.ssh/id_ed25519_multica_bridge.pub
   ```
2. На сервере (root):
   ```bash
   cat > /tmp/<имя>.pub   # вставить ключ
   bridge-mux user add <имя> /tmp/<имя>.pub      # слот — следующий свободный; сервисы по умолчанию sphere,kc,git01,dev
   bridge-mux client <имя> --format plist  > /tmp/<имя>.plist     # macOS
   bridge-mux client <имя> --format systemd > /tmp/<имя>.service  # Linux
   bridge-mux client <имя> --format windows --key '~/.ssh/id_rsa' > /tmp/<имя>.ps1   # Windows
   ```
   `user add` сам пересобирает `/var/lib/bridge/.ssh/authorized_keys`. Ключ может слушать только порты
   своего слота и только на `127.0.0.1`. `bridge-mux` подхватывает новый конфиг сам, рестарт не нужен.
3. Сотрудник ставит то, что выдал `client`:
   - macOS: `~/Library/LaunchAgents/com.company.multica-bridge.plist`, затем
     `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.company.multica-bridge.plist`,
     лог — `/tmp/multica-bridge.log`;
   - Linux: `~/.config/systemd/user/multica-bridge.service`, затем
     `systemctl --user enable --now multica-bridge` (и `loginctl enable-linger`, чтобы жил без входа).
   Нужен рабочий VPN. Без него туннель поднимется, но слот будет мёртвым.
4. Проверка на сервере: `bridge-mux status`. У слота сотрудника стоит `ok`, у сервиса — `→ <имя>`.

Отключить сотрудника: `bridge-mux user rm <имя>`. Поменять приоритет: переставить элементы `users` в
`/etc/bridge-mux.json`. `bridge-mux` перечитывает конфиг на ходу, а ключи от порядка не зависят.

## Файлы

| Файл | Где живёт | Что делает |
|---|---|---|
| `bridge-mux`, `bridge-mux.service` | VPS, `/usr/local/bin`, `/etc/systemd/system` | слоты, раздача соединений живому мосту, `authorized_keys`, команда клиента |
| `vps/60-bridge.conf` | VPS, `/etc/ssh/sshd_config.d/` | пользователь `bridge` без шелла, только remote-forward, ClientAlive |
| `vps/60-git01-bridge.conf` | VPS, `/etc/ssh/ssh_config.d/` | `git@<git01>` → `127.0.0.1:18422` |
| `vps/kc-bridge-nat.service`, `vps/dev-bridge-nat.service` | VPS, `/etc/systemd/system/` | DNAT Keycloak и dev-контура на постоянные порты bridge-mux |
| `mac/com.example.sphere-bridge.plist` | Мак владельца, `~/Library/LaunchAgents` | туннель слота 2 (`evgeniy`) |
| `mac/com.example.time-gw.plist` | Мак владельца | запускает `time-gw/time-gw-mac` |
| `CONNECT.md` | — | памятка сотруднику, который держит мост |

Остальной код моста лежит в соседних каталогах: `sphere-gw/` (шлюз Сферы), `time-gw/` (шлюз Time),
`deploy-queue/` (очередь проливки). Устройство — `docs/ops.md`, раздел про мост.

**Публичная копия.** `bridge/export-public.sh <каталог>` собирает `sphere-gw/`, `time-gw/`,
`deploy-queue/` и `bridge/` в чистый каталог и заменяет внутренние адреса плейсхолдерами. Затем
ищет секреты и остатки внутренних имён: если найдёт хоть одно, останавливается. Публикация в
в публичный репозиторий — отдельным шагом.

## Установка и откат

```bash
scp -q -r bridge root@<VPS>:/tmp/ && ssh root@<VPS> bash /tmp/bridge/install.sh
cd bridge && python3 -m unittest test_bridge_mux
```

Журнал: `journalctl -u bridge-mux` (смена живости слотов и кому ушёл сервис).

Откат к одному слоту: `systemctl disable --now bridge-mux`, затем вернуть
`/var/lib/bridge/.ssh/authorized_keys.bak-20261027-mux` и
`/root/60-bridge.conf.bak-20261027-mux` → `/etc/ssh/sshd_config.d/60-bridge.conf`, выполнить
`systemctl reload ssh`. Клиент снова держит постоянные порты; бэкап plist Мака —
`~/Library/LaunchAgents/.com.example.sphere-bridge.plist.bak-20261027-mux`.
