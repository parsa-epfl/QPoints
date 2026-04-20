#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: gen_snapshot.sh [ckp_dir] [snapshot] [image] [copy_img] [num_cores] [monitor_port]

Arguments (all optional):
  ckp_dir      Checkpoint root directory (default: checkpoints/workload)
  snapshot     Snapshot subdirectory name (default: snapshots_0)
  image        Disk image filename; used only when copy_img is enabled (default: snapshots_0.img)
  copy_img     Copy disk image into snapshot dir: 1|true|yes (default: 0, requires image)
  num_cores    Number of cores for snapshot (default: 1)
  monitor_port QEMU monitor telnet port (default: 45454)

Example:
  gen_snapshot.sh checkpoints/workload snapshots_0 my.img true 4 45454
EOF
  exit 0
fi

ckp_dir="${1:-checkpoints/workload}"
snapshot="${2:-"snapshots_0"}"
image="${3:-"snapshots_0.img"}"
copy_img="${4:-0}"
num_cores="${5:-1}"
monitor_port="${6:-45454}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root_dir="$(cd "${script_dir}/../.." && pwd)"
dest_dir="${ckp_dir}/${snapshot}"
mkdir -p "$dest_dir"

copy_args=()
disk_args=()
if [[ "$copy_img" == "1" || "$copy_img" == "true" || "$copy_img" == "yes" ]]; then
  copy_args=(--copy-disk-img)
  disk_args=(--disk-image "$image")
fi

python3 "${root_dir}/scripts/create_snapshot.py" "${disk_args[@]}" "${copy_args[@]}" --dest-dir "$dest_dir" \
  --num-cores "$num_cores" --monitor-port "$monitor_port"

echo "A checkpoint is created at ${dest_dir} directory"
