# Deploy on Ubuntu VPS (Lightsail / EC2–style)

This guide targets a **single maintainer**: SSH as **`ubuntu`**, Python app under **`~/daily-digest/repo/`**, state under **`~/daily-digest/data/`**, secrets under **`~/daily-digest/secrets/`**, **`cron`** for scheduling. Matches the CLI in [`README.md`](../README.md).

**Secrets must never be committed** — see [.gitignore](../.gitignore) (`.env`, `credentials.json`, `token.json`, `data/*.db`, `secrets/`, …). Prefer **`scp`** or editor upload; do not paste credentials into tracked markdown.

---

## File placement cheat sheet (absolute paths, username `ubuntu`)

| Asset | Required? | Canonical path on server |
|--------|-----------|-------------------------|
| **Application code** | Yes | **`/home/ubuntu/daily-digest/repo/`** (`git clone` or full copy — keep **`pyproject.toml`** next to **`app/`**). |
| **`.env`** | Yes (`run-daily`) | **`/home/ubuntu/daily-digest/repo/.env`** |
| **`credentials.json`** (Gmail OAuth client) | Yes (`run-daily`) | **`/home/ubuntu/daily-digest/secrets/credentials.json`** |
| **`token.json`** (OAuth refresh/access cache) | Yes after first OAuth | **`/home/ubuntu/daily-digest/secrets/token.json`** |
| **`daily_digest.db`** (SQLite) | Auto-created unless you migrate | **`/home/ubuntu/daily-digest/data/daily_digest.db`** (match **`DAILY_DIGEST_DB_PATH`**) |

**`.env`** must point at the above with **full paths** (`DAILY_DIGEST_DB_PATH`, `GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`).

---

## 1. Ubuntu packages

Ubuntu instance with **`ubuntu@PUBLIC_IP`** SSH (key in **`.pem`**, optional Static IP):

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
python3 --version   # must be Python >= 3.11 per pyproject.toml
```

---

## 2. Directory layout

```bash
mkdir -p ~/daily-digest/{data,secrets,logs,backups}
```

| Path | Role |
|------|------|
| **`~/daily-digest/repo/`** | Repository root (**`pyproject.toml`**, **`app/`**, **`.venv`**, **`.env`**) |
| **`~/daily-digest/data/`** | SQLite **`daily_digest.db`** |
| **`~/daily-digest/secrets/`** | **`credentials.json`**, **`token.json`** |
| **`~/daily-digest/logs/`** | Optional **`cron.log`** (cron redirect) |
| **`~/daily-digest/backups/`** | Daily **`cp`** snapshots of **`daily_digest.db`** |

Get code into **`~/daily-digest/repo/`** (`git clone … repo` **or** copy the full project tree). **Important:** **`python -m venv .venv`** and **`pip install -e ".[gmail]"`** run **inside `repo/`**, not in **`~/daily-digest/` alone** (there must be a **`pyproject.toml`** next to **`app/`**).

---

## 3. Virtualenv and install

```bash
cd ~/daily-digest/repo
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[gmail]"
```

(Use **`pip install -e ".[dev,gmail]"`** if you run **`pytest`** on the VPS.)

---

## 4. Configuration (`.env`)

```bash
cd ~/daily-digest/repo
cp .env.example .env
# Edit with nano, vim, or Cursor Remote-SSH
```

**Example (absolute paths, user `ubuntu`):**

```dotenv
DAILY_DIGEST_DB_PATH=/home/ubuntu/daily-digest/data/daily_digest.db
GMAIL_CREDENTIALS_PATH=/home/ubuntu/daily-digest/secrets/credentials.json
GMAIL_TOKEN_PATH=/home/ubuntu/daily-digest/secrets/token.json

NEWSLETTER_SENDERS= ...
DIGEST_RECIPIENT_EMAIL= ...
OPENAI_API_KEY= ...
```

If Linux username ≠ **`ubuntu`**, replace **`/home/ubuntu`** accordingly.

```bash
chmod 600 ~/daily-digest/repo/.env
```

---

## 5. Upload secrets from your laptop

**Windows PowerShell example** (`scp -i your-key.pem`):

```powershell
scp -i "C:\path\to\LightsailDefaultKey-xxx.pem" .env ubuntu@PUBLIC_IP:/home/ubuntu/daily-digest/repo/.env
scp -i "C:\path\to\LightsailDefaultKey-xxx.pem" credentials.json ubuntu@PUBLIC_IP:/home/ubuntu/daily-digest/secrets/credentials.json
scp -i "C:\path\to\LightsailDefaultKey-xxx.pem" token.json ubuntu@PUBLIC_IP:/home/ubuntu/daily-digest/secrets/token.json
```

On server:

```bash
chmod 600 ~/daily-digest/repo/.env \
         ~/daily-digest/secrets/credentials.json \
         ~/daily-digest/secrets/token.json
```

### Gmail OAuth — first **`token.json` must be done locally**

A **headless VPS** cannot reliably complete **`InstalledAppFlow.run_local_server()`**. On your **PC** (browser available), same **`credentials.json`** as production:

1. Put **`credentials.json`** where **`GMAIL_CREDENTIALS_PATH`** expects (local **`Settings`** **or** symlink path).
2. Run **`python -m app.main run-daily`** once (or any path that constructs **`GmailClient`** — it will write **`token.json`** when missing/expired appropriately on a workstation).
3. **`scp`** the new **`token.json`** to **`GMAIL_TOKEN_PATH`** on the VPS, then **`chmod 600`**.

Subsequent VPS runs refresh using the **`refresh_token`** inside **`token.json`**.

### Token refresh failure recovery (`invalid_grant`, revoked refresh)

**Symptoms:** **`google.auth.exceptions.RefreshError`** or **`invalid_grant`** in stderr / logs.

Behavior in this codebase: **`GmailClient`** deletes a dead **`token.json`** on **`RefreshError`**, then attempts interactive OAuth (**works on laptop**, **not on headless VPS**).

Recovery:

1. On a machine with browser, regenerate **`token.json`** (same GCP OAuth client **`credentials.json`**).
2. Re-upload **`token.json`** → **`~/daily-digest/secrets/token.json`**; **`chmod 600`**.
3. **`ssh`** to VPS: **`python -m app.main show-config`**, then **`python -m app.main run-daily`**.

(Optional: revoke app in Google Account settings if you rotated clients.)

---

## 6. Manual verification (before `cron`)

```bash
cd ~/daily-digest/repo
source .venv/bin/activate
python -m app.main show-config
python -m app.main run-daily
```

---

## 7. Log inspection

| Log | Producer | Typical use |
|-----|----------|-------------|
| **`~/daily-digest/repo/logs/run-daily-YYYY-MM.log`** | [`scripts/run-daily.sh`](../scripts/run-daily.sh) wraps **`run-daily`** stdout/stderr monthly | **`tail -n 120 ~/daily-digest/repo/logs/run-daily-$(date +%Y-%m).log`** |
| **`~/daily-digest/logs/cron.log`** | **`cron`** line **`>> cron.log 2>&1`** | **`tail -n 200 ~/daily-digest/logs/cron.log`** — captures wrapper/cron-layer output |

**Cron note:** **`run-daily` exit non-zero** writes to **`cron.log`** like any stderr; **`MAILTO=…`** can email failures (often unset on small VPS).

**Preview only (reads SQLite, no Gmail):** **`preview-digest --date`** uses **UTC calendar day** — see **`--help`**.

```bash
python -m app.main preview-digest --date YYYY-MM-DD -o /tmp/preview.html
```

---

## 8. Wrapper script [`scripts/run-daily.sh`](../scripts/run-daily.sh)

Runs from **repo-relative** logic — it discovers **`REPO_ROOT`** from the **`scripts/`** directory. It **does not** embed `cron` lines; it only invokes Python.

```bash
chmod +x ~/daily-digest/repo/scripts/run-daily.sh
~/daily-digest/repo/scripts/run-daily.sh
```

**Never paste `crontab` lines (`CRON_TZ`, `0 17 * * *`, …)** into **`run-daily.sh`** — **`crontab -e`** only.

---

## 9. Cron — **`America/Los_Angeles`**, daily **5:00 PM**

Schedule as **`ubuntu`**:

```bash
crontab -e
```

**Scheduling — 17:00 (5 PM)** in **`America/Los_Angeles`**:

```cron
CRON_TZ=America/Los_Angeles
0 17 * * * /home/ubuntu/daily-digest/repo/scripts/run-daily.sh >> /home/ubuntu/daily-digest/logs/cron.log 2>&1
```

Ensure **`mkdir -p ~/daily-digest/logs`** exists.

Verify:

```bash
crontab -l
```

---

## 10. SQLite backup (daily)

After digest (e.g. **5:30 PM**):

```cron
CRON_TZ=America/Los_Angeles
30 17 * * * cp /home/ubuntu/daily-digest/data/daily_digest.db "/home/ubuntu/daily-digest/backups/daily_digest_$(date +\%F).db"
```

**In `crontab`, `%` must be escaped:** **`\%F`**.

Same-calendar-day reruns overwrite the dated file — acceptable unless you rename with time. Rotate old **`backups/`** periodically or sync to **S3 / Drive**.

---

## 11. One scheduler

Disable **Windows Task Scheduler** (or macOS/Linux **cron**) on your laptop once VPS **`cron`** is live — avoid two writers against the same Gmail + SQLite mental model (**`run_lock`** helps overlap, but duplication is pointless).

---

## Optional: **`/opt/`** + dedicated UNIX user

Larger setups use **`/opt/...`** and a service user — requires **`authorized_keys`** for SSH. Solo flows stay simpler with **`ubuntu`** + **`~/daily-digest`**.
