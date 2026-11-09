# Мост в рабочую сеть (Сфера, Keycloak, git01, dev-контур) — с 27.10.2026

Сервер в сеть Лоции сам не ходит. Мост держат сотрудники с включённым VPN: каждый — ssh-туннель
в свой слот портов. `bridge-mux` отдаёт соединение первому живому мосту. Мостов может быть сколько угодно.

Подробно: /usr/local/share/doc/bridge-mux/README.md (устройство, откат),
/usr/local/share/doc/bridge-mux/CONNECT.md (памятка человеку: ключ, проверка, автозапуск Windows/macOS/Linux).
Код: <private-repo>, каталог bridge/.

## Сейчас

    bridge-mux status          # слоты, кто живой, через кого идёт каждый сервис
    bridge-mux user list
    journalctl -u bridge-mux -n 50

Слоты: 1 ilya (пока legacy: старый туннель на 18443, только Сфера), 2 evgeniy (Мак), 3 tatva (Windows).

## сотруднику — перейти со старого туннеля на слот (тогда пойдут ещё kc, git01, dev)

Старый туннель (`-R 127.0.0.1:18443 -R 192.168.200.1:18443`, ключ `sphere-bridge-current-mac`)
работает и сейчас, но только для Сферы. Перевод:

1. На сервере: `bridge-mux client ilya --format plist --key '~/.ssh/<ключ моста>'`
   (Linux — `--format systemd`, Windows — `--format windows`). Ключ тот же, новый не нужен.
2. На машине сотрудника: заменить старый туннель выданным (macOS — `launchctl bootout` старого агента,
   новый plist в ~/Library/LaunchAgents, `launchctl bootstrap gui/$(id -u) …`).
3. На сервере: `bridge-mux user legacy ilya off` — ключ переедет на порты слота 1.
4. Проверка: `bridge-mux status` → у ilya `sphere:ok kc:ok git01:ok dev:ok` (при включённом VPN).

Порядок 2 → 3 важен только для минимального простоя: пока legacy не снят, новый туннель
отбивается («remote port forwarding failed»), после снятия — старый. Оба переподключаются сами.

## Новый человек

    cat > /tmp/<имя>.pub                                   # его публичный ключ
    bridge-mux user add <имя> /tmp/<имя>.pub
    bridge-mux client <имя> --format windows|plist|systemd # отдать ему вместе с CONNECT.md

Убрать: `bridge-mux user rm <имя>`. Руками `/var/lib/bridge/.ssh/authorized_keys` не править —
его собирает bridge-mux из /etc/bridge-mux.json.

## Не работает

- `bridge-mux status` везде «—» — ни у кого не включён VPN Лоции или все спят. Работа копится в очередях.
- Человек пишет «Permission denied» — нет его ключа (`user list`); «remote port forwarding failed» —
  у него команда не своего слота, выдать заново `client`.
- Откат на старую схему одного моста — README.md, раздел «Установка и откат».
