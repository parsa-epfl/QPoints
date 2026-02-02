if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
  cat <<'EOF'
Usage: convert.sh [BASE] [SNAPSHOT]

Example:
  convert.sh clean_4core.qcow2 init_warmed
EOF
  exit 1
fi

BASE="$1"
SNAPSHOT="$2"

# Convert snapshot directly without temp copy.
qemu-img convert -f qcow2 -O raw -l ${SNAPSHOT} ${BASE} ${SNAPSHOT}.img
