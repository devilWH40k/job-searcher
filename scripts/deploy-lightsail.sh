#!/usr/bin/env bash
# Executed on the existing Ubuntu Lightsail host by GitHub Actions.
set -euo pipefail
umask 077

commit=${1:?Pass the tested commit SHA}
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid commit SHA'; exit 1; }
cd /home/ubuntu/job-searcher
exec 9>/home/ubuntu/.job-searcher-deploy.lock
flock -n 9 || { echo 'Another deployment is running'; exit 1; }
uv=/home/ubuntu/.local/bin/uv
test -x "$uv"
test -z "$(git status --porcelain)" || { echo 'Server checkout has local changes'; exit 1; }
git fetch origin main
git merge-base --is-ancestor "$commit" origin/main
previous=$(git rev-parse HEAD)
echo "Deploying $commit; previous commit: $previous"
sudo -n systemctl stop job-searcher

# A failed deployment stays stopped for explicit recovery; never restore user data
# automatically, since a new version may have performed schema migrations.
trap 'sudo -n systemctl stop job-searcher; echo "Deployment failed. Service remains stopped; see README recovery steps. Previous commit: $previous" >&2' ERR
mkdir -p /var/lib/job-searcher/backups
if test -f /var/lib/job-searcher/data/vacancies.sqlite3; then
  .venv/bin/python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
import sqlite3

source = Path('/var/lib/job-searcher/data/vacancies.sqlite3')
stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
destination = Path('/var/lib/job-searcher/backups') / f'vacancies-{stamp}.sqlite3'
with sqlite3.connect(f'{source.as_uri()}?mode=ro', uri=True) as database:
    with sqlite3.connect(destination) as backup:
        database.backup(backup)
print(f'Database backup: {destination}')
PY
fi
git checkout --detach "$commit"
"$uv" sync --locked --no-dev --python 3.14.2
.venv/bin/python -m job_bot --version
sudo -n systemctl start job-searcher
sleep 10
if ! sudo -n systemctl is-active --quiet job-searcher; then
  sudo -n systemctl stop job-searcher
  false
fi
trap - ERR
echo "Deployment successful: $commit"
