#!/usr/bin/env bash
set -euo pipefail

# 1. Clone (or update) your repo
if [ -d repo ]; then
  cd repo
  git fetch origin
  git reset --hard origin/${BRANCH:-main}
else
  git clone https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git repo
  cd repo
fi

# 2. (Re)generate the JSON
#    Now that we're inside "repo/", just run the script directly
echo "Generating new verdicts JSON…"
python3 get_new_verdicts.py

# 3. Configure Git author info
git config user.name  "Render Cron Bot"
git config user.email "cron@render.com"

# 4. Check for changes before committing
if git diff --quiet; then
  echo "No changes detected; exiting."
  exit 0
fi

# 5. Commit & push
git commit -m "chore: update verdicts via Cron Job"
git push origin ${BRANCH:-main}

echo "✔ Updated data.json and pushed to ${BRANCH:-main}."
