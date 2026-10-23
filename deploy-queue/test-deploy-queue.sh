#!/bin/bash
# Тест deploy-queue без сети: «git01» — локальные bare-репо, мост выключается подменой адреса.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
t=$(mktemp -d); trap 'rm -rf "$t"' EXIT
pass=0; failn=0
check() { if eval "$2"; then echo "ok   $1"; pass=$((pass+1)); else echo "FAIL $1"; failn=$((failn+1)); fi; }
dq() { python3 -I "$here/deploy-queue" "$@"; }
G=/usr/bin/git
export DQ_DIR=$t/q DQ_GIT=$G DQ_RP_REPO=$t/rp

mkdir -p "$t/git01/grp"; $G init -q --bare "$t/git01/grp/app.git"
$G init -q -b develop "$t/wt"; $G -C "$t/wt" config user.email t@t; $G -C "$t/wt" config user.name t
$G -C "$t/wt" remote add origin git@<git01-host>:grp/app.git
echo a >"$t/wt/a"; $G -C "$t/wt" add -A; $G -C "$t/wt" commit -qm init
$G -C "$t/wt" switch -qc feature/task-7/x; echo b >"$t/wt/b"; $G -C "$t/wt" add -A; $G -C "$t/wt" commit -qm b

# Моста нет: адрес никуда не ведёт.
export DQ_GIT01=$t/nowhere/{project}.git
out=$(dq add mr --repo "$t/wt" --branch feature/task-7/x --target develop --title "feat: x. T-7" --description "https://sphere/7")
check "без моста — ждёт пуша" '[[ $out == *" push "* ]]'
check "ветка в зеркале" '$G -C "$t/q/git/grp__app.git" rev-parse -q --verify refs/heads/feature/task-7/x >/dev/null'
rm -rf "$t/wt"   # каталог рана удалён — очередь живёт на зеркале
check "pull без моста — пусто" '[[ $(dq pull) == "[]" ]]'

export DQ_GIT01=$t/git01/{project}.git
pulled=$(dq pull)
check "мост есть — ветка в git01" '$G -C "$t/git01/grp/app.git" rev-parse -q --verify refs/heads/feature/task-7/x >/dev/null'
check "pull отдаёт MR" '[[ $(python3 -c "import json,sys;r=json.loads(sys.argv[1]);print(r[0][\"kind\"],r[0][\"target\"])" "$pulled") == "mr develop" ]]'
id=$(python3 -c "import json,sys;print(json.loads(sys.argv[1])[0]['id'])" "$pulled")
dq finish "$id" --ok --note "MR !5" --url https://git01/mr/5
check "finish — done" '[[ $(dq list --all) == *"done"*"https://git01/mr/5"* && $(dq pull) == "[]" ]]'

set +e; out=$(dq add mr --repo . --branch develop --target master --title t 2>&1); rc=$?; set -e
check "базовая ветка — отказ" '((rc != 0)) && [[ $out == *"базовая ветка"* ]]'

# РП: merge приёмки на вершине main, суть — во втором родителе; два add — одна выкатка.
$G init -q -b main "$t/rp"; $G -C "$t/rp" config user.email t@t; $G -C "$t/rp" config user.name t
echo a >"$t/rp/a"; $G -C "$t/rp" add -A; $G -C "$t/rp" commit -qm "init"
merge_feature() {
  $G -C "$t/rp" switch -qc "$1" main; echo "$1" >"$t/rp/$1"; $G -C "$t/rp" add -A; $G -C "$t/rp" commit -qm "$2"
  $G -C "$t/rp" switch -q main; $G -C "$t/rp" merge -q --no-ff -m "chore(merge): $1 в main. T-12345" "$1"
}
merge_feature f1 "feat(calendar): календарь цепочкой. T-192364"
dq add rp-prod >/dev/null
merge_feature f2 "fix(ui): вкладка видна. T-12345"
out=$(dq add rp-prod)
n=$(dq list --json | python3 -c "import json,sys;print(len([i for i in json.load(sys.stdin) if i['kind']=='rp-prod']))")
check "rp-prod схлопывается в одну" '((n == 1))'
check "заголовки обеих правок" '[[ $out == *"календарь цепочкой; вкладка видна"* ]]'
check "задача из первой правки" '[[ $(dq list --json | python3 -c "import json,sys;print([i for i in json.load(sys.stdin) if i[\"kind\"]==\"rp-prod\"][0][\"task\"])") == 192364 ]]'
rid=$(dq list --json | python3 -c "import json,sys;print([i for i in json.load(sys.stdin) if i['kind']=='rp-prod'][0]['id'])")
head=$($G -C "$t/rp" rev-parse main)
dq finish "$rid" --ok --note "старый" --sha 0000000000
check "finish старого sha — остаётся ready" '[[ $(dq list) == *"$rid  ready"* ]]'
dq finish "$rid" --ok --note "prod" --sha "$head"
check "finish текущего sha — done" '[[ $(dq list) == "очередь пуста" ]]'

echo "итог: $pass ok, $failn fail"; ((failn == 0))
