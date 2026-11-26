#!/usr/bin/env bash
# Apply the protected-main ruleset and enable secret scanning on a repository.
# Usage: bash scripts/setup/apply-github-ruleset.sh owner/repo
set -euo pipefail

REPO="${1:?usage: apply-github-ruleset.sh owner/repo}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gh api --method POST "repos/${REPO}/rulesets" \
  --input "${SCRIPT_DIR}/github-main-ruleset.json"

gh api --method PATCH "repos/${REPO}" \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'

echo "Applied main-protection ruleset and secret scanning to ${REPO}"
