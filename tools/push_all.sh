#!/usr/bin/env bash
set -euo pipefail

git status --short

git log --oneline origin/main..HEAD

git push
