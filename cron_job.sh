#!/usr/bin/env bash
set -euo pipefail

BRANCH="${BRANCH:-main}"

# 1 · Clone a fresh copy (Render Cron Jobs are ephemeral)
git clone --depth 1 "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git" repo
cd repo

# 2 · (Re)generate the artifacts
echo "Generating new verdicts JSON…"
python3 get_new_verdicts.py

# 3 · Configure Git
git config user.name  "Render Cron Bot"
git config user.email "cron@render.com"

# 4 · Stage everything and commit only if there are *actual* changes
git add -A
if git diff --cached --quiet; then
  echo "No changes detected; exiting."
  exit 0
fi

git commit -m "chore: update verdicts $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
git push origin "$BRANCH"

echo "✔ Updated verdicts and pushed to ${BRANCH}."
