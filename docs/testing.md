# Testing — manual acceptance walk-through

Run this after any significant change, before publishing. A dev
instance on **port 7861** keeps the running service (7860) untouched:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 7861 &
```

## 0. Prerequisites

```bash
.venv/bin/python -m pytest tests/ -x -q          # must be green
scripts/check_privacy.sh                          # must pass
```

## 1. First-run wizard

Fresh state (no `workspace_root` in `config.local.json`):

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' http://127.0.0.1:7861/status
# expect: 303 -> http://127.0.0.1:7861/setup
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7861/setup   # 200
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST -d 'workspace=/tmp/smoke-workspace' http://127.0.0.1:7861/setup
# expect: 303 -> /submit?message=workspace%20saved&message_type=success
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7861/status   # 200
```

The wizard must reject system directories:

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST -d 'workspace=/etc' http://127.0.0.1:7861/setup
# expect: 303 -> /setup?message=...error
```

## 2. Bilingual switching

The language toggle is a plain link (`?lang=en|zh`) that sets a
year-long cookie and 303-redirects to the clean URL. Language
resolution: cookie → `ui_lang` config → Accept-Language → English.

```bash
# switch + redirect
curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}\n' \
  'http://127.0.0.1:7861/status?lang=zh'      # 303 -> /status, Set-Cookie dashboard_lang=zh
# cookie sticks
curl -s -b 'dashboard_lang=zh' http://127.0.0.1:7861/status | grep -q '集群状态'
# en cookie wins over zh Accept-Language
curl -s -b 'dashboard_lang=en' -H 'Accept-Language: zh-CN' \
  http://127.0.0.1:7861/status | grep -q 'Cluster Status'
# no cookie: Accept-Language decides
curl -s -H 'Accept-Language: zh-CN' http://127.0.0.1:7861/status | grep -q '集群状态'
# default is English
curl -s http://127.0.0.1:7861/status | grep -q 'Cluster Status'
# every page renders in both languages
for page in status jobs submit env-check setup; do
  curl -s -o /dev/null -w "$page en:%{http_code} " http://127.0.0.1:7861/$page
  curl -s -o /dev/null -w "zh:%{http_code}\n" -b 'dashboard_lang=zh' http://127.0.0.1:7861/$page
done
# all 200; the only Chinese left on an English status page is the toggle button
curl -s -b 'dashboard_lang=en' http://127.0.0.1:7861/status | grep -o '集群\|队列\|分区' || echo "no zh residue"
```

## 3. Teaching features

```bash
curl -s http://127.0.0.1:7861/status | grep -c 'btn-copy'      # > 0
curl -s http://127.0.0.1:7861/status | grep -q 'openssl enc -aes-256-cbc'   # cheat sheet
curl -s http://127.0.0.1:7861/jobs | grep -q 'data-copy="squeue -u $USER"'
```

## 4. GPU history

The charts read the JSON API; overlay labels must follow the UI
language. Date formats per scale: `2026-07-25` (day), `2026-W30`
(week), `2026-07` (month), `2026` (year).

```bash
# linear day: 5-minute timeline, ISO labels
curl -s -b 'dashboard_lang=en' 'http://127.0.0.1:7861/status/gpu-history?scale=day' \
  | .venv/bin/python -c "import json,sys; d=json.load(sys.stdin); print(len(d['data']['timeline']))"   # > 0
# overlay requires start+end -> 400
curl -s -o /dev/null -w '%{http_code}\n' \
  'http://127.0.0.1:7861/status/gpu-history?scale=day&mode=overlay'    # 400
# bilingual overlay labels
curl -s -b 'dashboard_lang=en' \
  'http://127.0.0.1:7861/status/gpu-history?scale=week&mode=overlay&start=2026-W33&end=2026-W33' \
  | grep -q 'Mon'
curl -s -b 'dashboard_lang=zh' \
  'http://127.0.0.1:7861/status/gpu-history?scale=week&mode=overlay&start=2026-W33&end=2026-W33' \
  | grep -q '周一'
# overview cards render on the status page
curl -s -b 'dashboard_lang=en' http://127.0.0.1:7861/status | grep -q 'GPU'
```

History comes from `data/gpu_history/` (cron collector, see README
"GPU history collection"). With no data, the section shows an empty
state instead of failing.

## 5. Submit / cancel smoke (real SLURM cluster)

### 5a. Paste channel

`partition` and `gres` are optional: omit them to submit without
`--partition` / `--gres` flags (SLURM's native default). When they are
sent, they must be on the configured allowlist.

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST http://127.0.0.1:7861/submit \
  --data-urlencode 'script_text=#!/usr/bin/env bash
echo "hello from $SLURM_JOB_ID"' \
  --data-urlencode 'script_filename=smoke.sbatch' \
  --data-urlencode 'job_name=smoke' \
  --data-urlencode 'cpus_per_task=1' \
  --data-urlencode 'mem=4G' \
  --data-urlencode 'time_limit=00:05:00'
# expect: 303 -> /jobs/<id>
# then cancel it:
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:7861/jobs/<id>/cancel
```

### 5b. Python upload — auto-generated sbatch

```bash
printf 'print("hello")\n' > /tmp/smoke.py
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST http://127.0.0.1:7861/submit \
  -F 'script_file=@/tmp/smoke.py' \
  -F 'script_filename=smoke.py' \
  -F 'job_name=smoke-py' \
  -F 'partition=GPU' -F 'gres=gpu:1' \
  -F 'cpus_per_task=1' -F 'mem=4G' -F 'time_limit=00:05:00'
# expect: 303 -> /jobs/<id>; the stored script starts with a bash
# shebang and runs `python3 smoke.py` (shlex-quoted; the job runs on a
# compute node with its own python3 — the dashboard .venv is local)
```

### 5c. Whitelist rejection stays intact

A job name with a space must be rejected; a partition that is not on
the allowlist must be rejected too:

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST http://127.0.0.1:7861/submit \
  --data-urlencode 'script_text=echo hi' \
  --data-urlencode 'job_name=bad name' \
  --data-urlencode 'cpus_per_task=1' --data-urlencode 'mem=4G' \
  --data-urlencode 'time_limit=00:05:00'
# expect: 303 -> /submit?message=...&message_type=error

curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST http://127.0.0.1:7861/submit \
  --data-urlencode 'script_text=echo hi' \
  --data-urlencode 'job_name=ok' \
  --data-urlencode 'partition=not-on-the-allowlist' \
  --data-urlencode 'cpus_per_task=1' --data-urlencode 'mem=4G' \
  --data-urlencode 'time_limit=00:05:00'
# expect: 303 -> /submit?message=...&message_type=error
```

### 5d. Script picker: missing file degrades to an error

A workspace script that passes the name checks but does not exist must
give a 303 error message, not a 500:

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -X POST http://127.0.0.1:7861/submit \
  --data-urlencode 'existing_script=nothere.sbatch' \
  --data-urlencode 'job_name=ok' \
  --data-urlencode 'partition=GPU' --data-urlencode 'gres=gpu:1' \
  --data-urlencode 'cpus_per_task=1' --data-urlencode 'mem=4G' \
  --data-urlencode 'time_limit=00:05:00'
# expect: 303 -> /submit?message=Script%20file%20not%20found...&message_type=error
# (an existing script in workspace/scripts/ must instead 303 -> /jobs/<id>)
```

## 6. Status page shows both queues

```bash
curl -s http://127.0.0.1:7861/status | grep -q 'squeue -u $USER'   # my jobs
curl -s http://127.0.0.1:7861/status | grep -q 'squeue'            # cluster queue
```

## 7. Security regression

```bash
# bind rejection
printf '{"server_bind_host": "0.0.0.0"}' > /tmp/bad-config.json   # merged into config.local.json
.venv/bin/python -c "from app.config import get_settings; get_settings.cache_clear(); import app.config; app.config.get_settings()" || echo "0.0.0.0 rejected"
# path escape on download
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7861/jobs/1/download   # 404
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7861/jobs/../../../etc/passwd/raw   # 404/4xx
# CSRF: cross-origin POST blocked, no-Origin POST (curl) allowed
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Origin: http://evil.example' -H 'Host: 127.0.0.1:7861' \
  -d 'workspace=/tmp/smoke-workspace' http://127.0.0.1:7861/setup   # 403
# non-numeric job id renders without touching SLURM (page stays 200)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7861/jobs/12a34   # 200
```
