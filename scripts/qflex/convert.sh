#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: convert.sh [BASE] [SNAPSHOT]

Example:
  convert.sh clean_4core.qcow2 init_warmed
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 1
fi

BASE="$1"
SNAPSHOT="$2"

# Convert snapshot directly without temp copy.
qemu-img convert -f qcow2 -O raw -l "$SNAPSHOT" "$BASE" "${SNAPSHOT}.img"
