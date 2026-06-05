# Milestone 7: VPS deployment support (Ubuntu + cron)

**Prerequisite:** Milestones 1–6 are complete. The app runs as **`python -m app.main run-daily`** with **`Settings`** / **`.env`**, Gmail OAuth files on disk, and SQLite state.

**Also see (planned, not part of M7):** [`milestone8-content-unit-routing.md`](milestone8-content-unit-routing.md) — Phase 6 content-unit routing.

**Goal:** Document and ship a **repeatable Ubuntu VPS** deployment (single maintainer, **`ubuntu`** user, **`~/daily-digest/`** layout) without putting secrets in git.

---

## I. Deliverables

1. **[`scripts/run-daily.sh`](scripts/run-daily.sh)** — Bash wrapper: `cd` repo root, `source .venv`, `python -m app.main run-daily`, append to **`logs/run-daily-YYYY-MM.log`** (mirror idea of [`scripts/run-daily.ps1`](scripts/run-daily.ps1)).
2. **[`docs/deploy-vps.md`](docs/deploy-vps.md)** — Single source of truth for Lightsail/EC2-style Ubuntu setup.

---

## II. Documentation requirements (`docs/deploy-vps.md`)

The doc **must** cover:

| Topic | Requirement |
|--------|-------------|
| **Ubuntu setup** | `apt` packages: `git`, `python3`, `python3-venv`, `python3-pip`; Python **≥ 3.11**. |
| **Virtualenv** | Create **`.venv` inside `~/daily-digest/repo`**, **not** the parent `~/daily-digest/` folder; `pip install -e ".[gmail]"`. |
| **File placement** | Explicit **absolute paths** for **`.env`**, **`credentials.json`**, **`token.json`**, **`daily_digest.db`** — see cheat sheet table in the doc. |
| **Cron** | Example **`0 17 * * *`** on a UTC VPS (**17:00 UTC**, ~**10:00 AM Pacific** during PDT). Document that **Debian/Ubuntu cron ignores `CRON_TZ` for scheduling** — hours are interpreted in the system timezone (`man 5 crontab`). |
| **OAuth** | **First consent on a workstation with a browser**; then **`scp`** **`token.json`** to **`GMAIL_TOKEN_PATH`** on the VPS. Headless VPS is not sufficient for initial consent. |
| **Refresh failures** | **`invalid_grant`** / revoked refresh token → re-auth locally → new **`token.json`** → re-upload; note **`GmailClient`** clears stale **`token.json`** on **`RefreshError`** then expects interactive flow **on machines that support it**. |
| **Logs** | Where **`cron`** appends (**`~/daily-digest/logs/cron.log`**), where **`run-daily.sh`** appends (**`repo/logs/run-daily-YYYY-MM.log`**), and **`tail`** examples. |
| **DB backup** | **`cp`** **`daily_digest.db`** into **`~/daily-digest/backups/`** via cron; escape **`%`** in **`date`** (**`\%F`**). Mention rotation later (S3/Drive/manual prune). |
| **Secrets policy** | **Never commit** `.env`, `credentials.json`, `token.json`, or `*.db` — align with **`.gitignore`**. |

---

## III. Non-goals (this milestone)

- **No** new CLI subcommands required (optional future: dedicated **`gmail-auth`** helper).
- **No** systemd timer requirement (cron is sufficient).
- **No** Terraform/CloudFormation; doc stays procedural.

---

## IV. Acceptance checklist

- [ ] Repo contains **`scripts/run-daily.sh`** (executable bit documented; user runs **`chmod +x`** on VPS after clone/sync).
- [ ] **`docs/deploy-vps.md`** satisfies §II above.
- [ ] **[`README.md`](README.md)** links to **`docs/deploy-vps.md`** and lists Milestone 7.
- [ ] **`run-daily.sh` does not embed crontab lines** — scheduling lives only in **`crontab -e`**.
