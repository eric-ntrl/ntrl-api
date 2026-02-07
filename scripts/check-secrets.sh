#!/usr/bin/env bash
# Check staged files for common secret patterns

if git diff --cached --diff-filter=ACM | grep -qEi '(sk-[a-zA-Z0-9]{20,}|AKIA[A-Z0-9]{16}|ghp_[a-zA-Z0-9]{36})'; then
  echo "ERROR: Possible secret detected in staged changes. Review your diff."
  exit 1
fi

exit 0
