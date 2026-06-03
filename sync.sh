#!/bin/bash

# Stop if not in a git repo
if [ ! -d ".git" ]; then
  echo "Not a git repository"
  exit 1
fi

branch=$(git branch --show-current)

echo "Syncing on branch: $branch"

git add .

# Only commit if there are changes
if git diff --cached --quiet; then
  echo "No changes to commit"
  exit 0
fi

git commit -m "auto-update: $(date '+%Y-%m-%d %H:%M:%S')"

git pull origin "$branch" --rebase

git push origin "$branch"
