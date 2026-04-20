#!/usr/bin/env bash
set -euo pipefail

start_time="$(date +%s)"
report_timing() {
  local exit_code=$?
  local end_time
  end_time="$(date +%s)"
  local elapsed=$((end_time - start_time))
  cleanup_children
  echo "[${snapshot:-unknown}] run_all.sh completed in ${elapsed}s (exit code: ${exit_code})"
}

qemu_pid=""
converted_img_tmp=""
cleanup_children() {
  if [[ -n "${converted_img_tmp:-}" && -f "$converted_img_tmp" ]]; then
    rm -f "$converted_img_tmp"
  fi
  if [[ -n "${qemu_pid:-}" ]]; then
    kill -TERM -- "-$qemu_pid" >/dev/null 2>&1 || kill "$qemu_pid" >/dev/null 2>&1 || true
    sleep 1
    kill -KILL -- "-$qemu_pid" >/dev/null 2>&1 || kill -KILL "$qemu_pid" >/dev/null 2>&1 || true
    wait "$qemu_pid" >/dev/null 2>&1 || true
  fi
}
trap report_timing EXIT
trap 'cleanup_children; exit 130' INT TERM

usage() {
  cat <<'EOF'
Usage: run_all.sh --qflex-ckp-dir DIR --gem5-ckp-dir DIR --core-count N --memory-gb GB \
  --base IMAGE --snapshot NAME [--ssh-host HOST] [--ssh-user USER] \
  [--monitor-base PORT] [--qmp-base PORT] [--ssh-base PORT]

Example:
  run_all.sh --qflex-ckp-dir qflex_checkpoints --gem5-ckp-dir gem5_checkpoints \
    --core-count 4 --memory-gb 16 --base web_search.qcow2 --snapshot snapshot_0
  run_all.sh --qflex-ckp-dir qflex_checkpoints --gem5-ckp-dir gem5_checkpoints \
    --core-count 4 --memory-gb 16 --base web_search.qcow2 --snapshot snapshot_0 \
    --ssh-host 127.0.0.1 --ssh-user ubuntu --monitor-base 45454 --qmp-base 4444 \
    --ssh-base 2222
EOF
}

qflex_ckp_dir=""
gem5_ckp_dir=""
core_count=""
memory_gb=""
base=""
snapshot=""
ssh_host="127.0.0.1"
ssh_user="qflex"
ssh_password="${QPOINTS_SSH_PASSWORD:-qflex}"
monitor_base="45454"
qmp_base="4444"
ssh_base="2222"

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
    --core-count)
      core_count="${2:-}"
      shift 2
      ;;
    --memory-gb)
      memory_gb="${2:-}"
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
    --ssh-user)
      ssh_user="${2:-}"
      shift 2
      ;;
    --monitor-base)
      monitor_base="${2:-}"
      shift 2
      ;;
    --qmp-base)
      qmp_base="${2:-}"
      shift 2
      ;;
    --ssh-base)
      ssh_base="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$qflex_ckp_dir" || -z "$gem5_ckp_dir" || -z "$core_count" || -z "$memory_gb" || -z "$base" || -z "$snapshot" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi


ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -d "$qflex_ckp_dir" ]]; then
  echo "[${snapshot}] qflex checkpoint directory not found: $qflex_ckp_dir" >&2
  exit 1
fi
if ! qflex_ckp_dir="$(cd "$qflex_ckp_dir" && pwd)"; then
  echo "[${snapshot}] failed to access qflex checkpoint directory: $qflex_ckp_dir" >&2
  exit 1
fi
if ! mkdir -p "$gem5_ckp_dir"; then
  echo "[${snapshot}] failed to create gem5 checkpoint directory: $gem5_ckp_dir" >&2
  exit 1
fi
if ! gem5_ckp_dir="$(cd "$gem5_ckp_dir" && pwd)"; then
  echo "[${snapshot}] failed to access gem5 checkpoint directory: $gem5_ckp_dir" >&2
  exit 1
fi
run_dir="${qflex_ckp_dir}/run"

snapshot_idx=0
if [[ "$snapshot" =~ _([0-9]+)$ ]]; then
  snapshot_idx="${BASH_REMATCH[1]}"
fi

monitor_port=$((monitor_base + snapshot_idx))
qmp_port=$((qmp_base + snapshot_idx))
ssh_port=$((ssh_base + snapshot_idx))

max_ssh_attempts="${QPOINTS_SSH_MAX_ATTEMPTS:-120}"
if [[ ! "$max_ssh_attempts" =~ ^[1-9][0-9]*$ ]]; then
  echo "[${snapshot}] ERROR: QPOINTS_SSH_MAX_ATTEMPTS must be a positive integer, got: ${max_ssh_attempts}" >&2
  exit 1
fi

if [[ ! -d "$run_dir" ]]; then
  echo "[${snapshot}] run directory not found: $run_dir" >&2
  exit 1
fi

cp "$ROOT_DIR/scripts/qflex/run_qemu_emu.sh" "$run_dir/"
chmod +x "$run_dir/run_qemu_emu.sh"
echo "[${snapshot}] start qemu in the background"
(
  cd "$run_dir"
  exec ./run_qemu_emu.sh "$core_count" "${memory_gb}G" "$base" "$snapshot" \
    "$monitor_port" "$qmp_port" "$ssh_port" > "qemu_emu_${snapshot}.log" 2>&1
) &
qemu_pid=$!

# Wait for SSH to become available before proceeding.
ssh_attempt=0
while (( ssh_attempt < max_ssh_attempts )); do
  if SSHPASS="$ssh_password" sshpass -e ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null -p "$ssh_port" "${ssh_user}@${ssh_host}" "true" \
    >/dev/null 2>&1; then
    break
  fi
  ssh_attempt=$((ssh_attempt + 1))
  echo "[${snapshot}] waiting for vm ssh (${ssh_user}@${ssh_host}:${ssh_port})... (${ssh_attempt}/${max_ssh_attempts})"
  sleep 0.5
done

if (( ssh_attempt >= max_ssh_attempts )); then
  echo "[${snapshot}] ERROR: timed out waiting for vm ssh (${ssh_user}@${ssh_host}:${ssh_port}) after ${max_ssh_attempts} attempts." >&2
  exit 1
fi

img_dest_dir="${gem5_ckp_dir}/${snapshot}"
tmp_log="${run_dir}/gen_snapshot_${snapshot}.log"

echo "[${snapshot}] start generating gem5 checkpoint"
"$ROOT_DIR/gen_snapshot.sh" "$gem5_ckp_dir" "$snapshot" "" 0 "$core_count" "$monitor_port" \
  2> "$tmp_log"

if [[ -d "$img_dest_dir" ]]; then
  mv "$tmp_log" "$img_dest_dir/gen_snapshot_${snapshot}.log"
else
  echo "[${snapshot}] Destination directory does not exist: $img_dest_dir" >&2
  exit 1
fi

cp "$ROOT_DIR/scripts/qflex/convert.sh" "$run_dir/"
converted_img="${img_dest_dir}/${snapshot}.img"
converted_img_tmp="${img_dest_dir}/.${snapshot}.img.tmp.$$"
rm -f "$converted_img" "$converted_img_tmp"

(
  cd "$run_dir"
  chmod +x convert.sh
  echo "[${snapshot}] start converting the disk image"
  ./convert.sh "$base" "$snapshot" "$converted_img_tmp"
)

if [[ -f "$converted_img_tmp" ]]; then
  mv "$converted_img_tmp" "$converted_img"
else
  echo "[${snapshot}] Converted image not found: $converted_img_tmp" >&2
  exit 1
fi
