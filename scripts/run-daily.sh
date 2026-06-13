#!/usr/bin/env bash
# Linux/cron helper: activates repo .venv and runs run-daily. See docs/deploy-vps.md.
# Logs: <repo>/logs/run-daily-YYYY-MM.log (same spirit as scripts/run-daily.ps1 on Windows).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Cron invokes this path directly; ensure executable after git checkout/reset (mode may be 644).
chmod +x "${BASH_SOURCE[0]}" 2>/dev/null || true

if [[ ! -f "${REPO_ROOT}/app/main.py" ]]; then
  echo "error: missing ${REPO_ROOT}/app/main.py — run: git fetch origin && git reset --hard origin/main" | tee -a "${REPO_ROOT}/logs/run-daily-$(date +%Y-%m).log" >&2
  exit 1
fi

mkdir -p "${REPO_ROOT}/logs"
log_file="${REPO_ROOT}/logs/run-daily-$(date +%Y-%m).log"

if [[ ! -d "${REPO_ROOT}/.venv" ]]; then
  echo "error: missing ${REPO_ROOT}/.venv — create it and run: pip install -e '.[gmail]'" | tee -a "${log_file}" >&2
  exit 1
fi

if [[ -t 2 ]] || [[ -t 1 ]]; then
  echo "Logging to ${log_file} — follow progress: tail -f $(printf '%q' "${log_file}")" >&2
fi

# Activate outside the log redirect block — avoids brittle parsing edge cases inside `{ ... }`.
# shellcheck disable=SC1091
source "${REPO_ROOT}/.venv/bin/activate"
export PYTHONUNBUFFERED=1

# Keep editable install in sync after git pull (avoids ModuleNotFoundError on cron).
"${REPO_ROOT}/.venv/bin/pip" install -e "${REPO_ROOT}[gmail]" -q >>"${log_file}" 2>&1 || {
  echo "warning: pip install -e failed; continuing with existing venv" >>"${log_file}"
}

{
  printf '\n======== %s ========\n' "$(date '+%Y-%m-%d %H:%M:%S %z')"
  python -m app.main run-daily
} >>"${log_file}" 2>&1
