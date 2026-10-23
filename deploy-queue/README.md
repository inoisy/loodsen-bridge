# deploy-queue — очередь проливки агентов

git01 серверу агентов виден только через мост с Мака: ssh — пока Мак не спит и в VPN, API — никогда.
Агенты кладут работу в очередь на сервере; Мак разбирает её, когда отвечает.

| что | где |
|---|---|
| `deploy-queue` | сервер, `/usr/local/bin`, очередь `/var/lib/deploy-queue` (agents): `items/*.json`, зеркала веток `git/` |
| cron `*/5` `deploy-queue flush` | сервер, `/etc/cron.d/deploy-queue` — допуш веток, когда поднялся мост |
| `deploy-queue-mac` | Мак, копия в `~/.local/bin` (ставит `install.sh`; после правки скрипта — переустановить), launchd `com.example.deploy-queue` раз в 5 мин, лог `~/Library/Logs/deploy-queue.log` |
| `SKILL.md` | скилл multica `deploy-queue` — как агенту отдавать работу |

Виды элементов:

- `mr` — ветка агента (снимок в зеркале) пушится в git01, Мак открывает MR через `glab api`. Не сливает.
- `rp-prod` — сервис РП едет в прод без вопроса: ставит `rp-git01-sync` после пуша `main`; Мак сливает
  MR `main → dev`, `dev → prod`, жмёт ручной `deploy_prod`, ждёт успеха. Несколько `main` подряд — одна выкатка.

Состояния: `push` (ждёт моста) → `ready` (ждёт Мак) → `done` / `failed` (причина в `note`).

    deploy-queue list [--all]                  # сервер, от agents
    bash deploy-queue/test-deploy-queue.sh     # тест без сети
    bash deploy-queue/install.sh               # установка с Мака
    python3 -I deploy-queue/deploy-queue-mac   # разбор сейчас

Остановить: Мак — `launchctl bootout gui/$(id -u)/com.example.deploy-queue`; авто-прод РП — убрать
блок `deploy-queue` из `rp-git01-sync` (бэкап `rp-git01-sync.bak-20261021-dq`).
