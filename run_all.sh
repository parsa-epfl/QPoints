#!/usr/bin/env bash
set -euo pipefail

start_time="$(date +%s)"
report_timing() {
  local exit_code=$?
  local end_time
  end_time="$(date +%s)"
  local elapsed=$((end_time - start_time))
  echo "run_all.sh completed in ${elapsed}s (exit code: ${exit_code})"
}
trap report_timing EXIT

usage() {
  cat <<'EOF'
Usage: run_all.sh --qflex-ckp-dir DIR --gem5-ckp-dir DIR --cores N --mem MB \
  --base IMAGE --snapshot NAME [--ssh-host HOST] [--ssh-port PORT] [--ssh-user USER]

Example:
  run_all.sh --qflex-ckp-dir qflex_checkpoints --gem5-ckp-dir gem5_checkpoints \
    --cores 4 --mem 16384 --base web_search.qcow2 --snapshot snapshot_0
  run_all.sh --qflex-ckp-dir qflex_checkpoints --gem5-ckp-dir gem5_checkpoints \
    --cores 4 --mem 16384 --base web_search.qcow2 --snapshot snapshot_0 \
    --ssh-host 127.0.0.1 --ssh-port 2222 --ssh-user ubuntu
EOF
}

qflex_ckp_dir=""
gem5_ckp_dir=""
cores=""
mem=""
base=""
snapshot=""
ssh_host="127.0.0.1"
ssh_port="2222"
ssh_user="qflex"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --qflex-ckp-dir)
      qflex_ckp_dir="${2:-}"
      shift 2
      ;;
    --gem5-ckp-dir)
      gem5_ckp_dir="${2:-}"
      shift 2
      ;;
    --cores)
      cores="${2:-}"
      shift 2
      ;;
    --mem)
      mem="${2:-}"
      shift 2
      ;;
    --base)
      base="${2:-}"
      shift 2
      ;;
    --snapshot)
      snapshot="${2:-}"
      shift 2
      ;;
    --ssh-host)
      ssh_host="${2:-}"
      shift 2
      ;;
    --ssh-port)
      ssh_port="${2:-}"
      shift 2
      ;;
    --ssh-user)
      ssh_user="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$qflex_ckp_dir" || -z "$gem5_ckp_dir" || -z "$cores" || -z "$mem" || -z "$base" || -z "$snapshot" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run_dir="${qflex_ckp_dir}/run"

if [[ ! -d "$run_dir" ]]; then
  echo "run directory not found: $run_dir" >&2
  exit 1
fi

if [[ ! -f "$run_dir/run_qemu_emu.sh" ]]; then
  cp "$ROOT_DIR/scripts/qflex/run_qemu_emu.sh" "$run_dir/"
fi

(
  cd "$run_dir"
  chmod +x run_qemu_emu.sh
  echo start qemu in the background
  ./run_qemu_emu.sh "$cores" "$mem" "$base" "$snapshot" > qemu_emu.log 2>&1 &
#  ./run_qemu_emu.sh
)

# Wait for SSH to become available before proceeding.
while true; do
  if SSHPASS="qflex" sshpass -e ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null -p "$ssh_port" "${ssh_user}@${ssh_host}" "true" \
    >/dev/null 2>&1; then
    break
  fi
  echo "waiting for vm ssh (${ssh_user}@${ssh_host}:${ssh_port})..."
  sleep 0.5
done

img_dest_dir="${gem5_ckp_dir}/${snapshot}"
tmp_log="${run_dir}/gen_snapshot.log"

echo start generating gem5 checkpoint
"$ROOT_DIR/gen_snapshot.sh" "$gem5_ckp_dir" "$snapshot" "" 0 "$cores" \
  2> "$tmp_log"

if [[ -d "$img_dest_dir" ]]; then
  mv "$tmp_log" "$img_dest_dir/gen_snapshot.log"
else
  echo "Destination directory does not exist: $img_dest_dir" >&2
  exit 1
fi

if [[ ! -f "$run_dir/convert.sh" ]]; then
  cp "$ROOT_DIR/scripts/qflex/convert.sh" "$run_dir/"
fi

(
  cd "$run_dir"
  chmod +x convert.sh
  echo start converting the disk image
  ./convert.sh "$base" "$snapshot"
)

img_src="${run_dir}/${snapshot}.img"
if [[ -f "$img_src" ]]; then
  echo moving the raw disk image to the destination folder
  mv "$img_src" "$img_dest_dir/."
else
  echo "Converted image not found: $img_src" >&2
  exit 1
fi
