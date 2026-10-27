# Как держать мост в рабочую сеть для агентов multica

Агенты multica живут на сервере <VPS>, а у сервера нет доступа во внутреннюю сеть Лоции.
Чтобы агенты могли работать, сотрудники держат с рабочих машин обратный SSH-туннель («мост»). Через
него сервер ходит в Сферу, Keycloak `sso2`, git01 и dev-контур `*.<dev-domain>`. Мост могут держать
несколько человек одновременно, сервер сам выбирает живой. Если твоя машина уснула, ничего не ломается,
пока мост есть у кого-то ещё.

Что нужно от тебя: рабочий VPN Лоции включён, туннель запущен. Туннель только **слушает** на сервере
порты твоего слота. Шелла на сервере нет, твою машину сервер не видит, ходит только к четырём адресам
ниже.

## 1. Ключ

Если ключа ещё нет:

```bash
ssh-keygen -t ed25519 -N "" -C "multica-bridge@<имя>" -f ~/.ssh/id_ed25519_multica_bridge
```

Публичную половину (`.pub`) отдай тому, у кого root на сервере агентов. Он заведёт тебе слот и пришлёт команду туннеля
с твоими портами (`bridge-mux client <имя> --format windows|plist|systemd`).

## 2. Проверить руками

Включи VPN и запусти присланную команду `ssh -N … bridge@<VPS>`. Тишина в консоли — это норма,
так и должно быть. Ошибки бывают такие:

- `Permission denied (publickey)` — слот ещё не заведён или ключ не тот (`-i` указывает на другой файл);
- `remote port forwarding failed for listen port …` — порты не твоего слота; возьми команду заново;
- выходит сразу без ошибки — посмотри `ssh -v …`.

владелец на сервере видит, жив ли твой слот: `bridge-mux status` (`sphere:ok`).

## 3. Автозапуск

**Windows** (встроенный OpenSSH, PowerShell):

1. Присланный скрипт сохрани в `%USERPROFILE%\multica-bridge.ps1`.
2. Один раз в PowerShell — задача при входе в систему, без окна, перезапуск сам:
   ```powershell
   $a = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$env:USERPROFILE\multica-bridge.ps1`""
   $t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
   $s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
   Register-ScheduledTask -TaskName "multica-bridge" -Action $a -Trigger $t -Settings $s
   Start-ScheduledTask -TaskName "multica-bridge"
   ```
3. Выключить: `Unregister-ScheduledTask -TaskName multica-bridge -Confirm:$false`.

**macOS:** присланный plist положи в `~/Library/LaunchAgents/com.company.multica-bridge.plist`, затем
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.company.multica-bridge.plist`.
Лог — `/tmp/multica-bridge.log`. Выключить: `launchctl bootout gui/$(id -u)/com.company.multica-bridge`.

**Linux:** присланный юнит положи в `~/.config/systemd/user/multica-bridge.service`, затем
`systemctl --user enable --now multica-bridge && loginctl enable-linger`.

## Что это даёт и чем не грозит

- Туннель видит только сервер агентов, и только на 127.0.0.1. Чужие клиенты в него не попадут.
- По туннелю идут только соединения к `<sphere-host>:443`, `<sso-host>:443`,
  `<git01-host>:22`, `<internal-ip>:443`. TLS сквозной, расшифровать трафик сервер не может.
- Агенты ходят в Сферу только на чтение (шлюз `sphere-gw`), в git01 — под своим deploy key.
