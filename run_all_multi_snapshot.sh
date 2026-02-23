#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_all_multi_snapshot.sh --first snapshot_N --last snapshot_M --parallel K \
  [run_all.sh flags...]

Example:
  run_all_multi_snapshot.sh --first snapshot_0 --last snapshot_99 --parallel 4 \
    --qflex-ckp-dir /path/qflex --gem5-ckp-dir /path/gem5 --core-count 4 --memory-gb 16 \
    --base clean_4core.qcow2 --ssh-user qflex
EOF
}

first=""
last=""
parallel=""
run_all_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --first)
      first="${2:-}"
      shift 2
      ;;
    --last)
      last="${2:-}"
      shift 2
      ;;
    --parallel)
      parallel="${2:-}"
      shift 2
      ;;
    *)
      run_all_args+=("$1")
      shift
      ;;
  esac
done

if [[ -z "$first" || -z "$last" || -z "$parallel" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

if [[ ! "$first" =~ ^snapshot_([0-9]+)$ ]]; then
  echo "First must be in the form snapshot_N." >&2
  exit 1
fi
first_idx="${BASH_REMATCH[1]}"

if [[ ! "$last" =~ ^snapshot_([0-9]+)$ ]]; then
  echo "Last must be in the form snapshot_N." >&2
  exit 1
fi
last_idx="${BASH_REMATCH[1]}"

if (( first_idx > last_idx )); then
  echo "First snapshot index must be <= last snapshot index." >&2
  exit 1
fi

if [[ ${#run_all_args[@]} -eq 0 ]]; then
  echo "Missing run_all.sh flags to pass through." >&2
  usage
  exit 1
fi

start_time="$(date +%s)"
cleanup_children() {
  jobs -pr | xargs -r kill >/dev/null 2>&1 || true
}
trap 'cleanup_children; exit 130' INT TERM

running=0
for i in $(seq "$first_idx" "$last_idx"); do
  snapshot="snapshot_${i}"
  echo snapshot: ${snapshot}
  ./run_all.sh "${run_all_args[@]}" --snapshot "$snapshot" &
  running=$((running + 1))
  sleep 1
  if (( running >= parallel )); then
    wait -n
    running=$((running - 1))
  fi
done

wait
end_time="$(date +%s)"
elapsed=$((end_time - start_time))
echo "All conversions completed in ${elapsed}s"
