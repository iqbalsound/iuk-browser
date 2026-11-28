#!/usr/bin/env bash
# One-time publish over SSH.  Usage: scripts/publish-to-github.sh git@github.com:<user>/iuk-browser.git
# Create the EMPTY repository on GitHub first (no README, no license, no .gitignore).
set -euo pipefail
REMOTE="${1:?git@github.com:<user>/iuk-browser.git}"
cd "$(dirname "$0")/.."
ssh -T git@github.com 2>&1 | grep -qi "successfully authenticated" || { echo "SSH to GitHub is not set up yet (see docs/RELEASING.md)"; exit 1; }
[ -d .git ] || git init -b main
git add -A
git diff --cached --quiet || git commit -m "IUK Browser 2.1.0"
git remote get-url origin >/dev/null 2>&1 && git remote set-url origin "$REMOTE" || git remote add origin "$REMOTE"
git push -u origin main
echo "Pushed. To release: git tag v2.1.0 && git push origin v2.1.0"
