#!/usr/bin/env bash

usage() {
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment NAME --snapshot NAME --inst N --cores N [--branch-trace] [--data-trace] [--timing-ruby] [--sim-config FILE]

Arguments (all required):
  --gem5-ckp-dir  Checkpoint root directory
  --experiment    Experiment name
  --snapshot      Snapshot name
  --inst          Instruction count
  --cores         Number of cores

Options:
  --branch-trace  Enable per-core branch trace logging
  --data-trace    Enable per-core data access trace logging
  --timing-ruby   Use O3CPU with Ruby MESI_Two_Level. Without this flag,
                  the existing starter_fs.py AtomicSimpleCPU config is used.
  --sim-config    Optional file containing additional gem5 CLI arguments,
                  one per line. This is applied to whichever simulation path
                  is selected and lets the modeled machine stay in a tracked
                  config file instead of growing the wrapper script.

Example:
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment OoO --snapshot snapshot_0 --inst 100000 --cores 1 --branch-trace
EOF
}

die() {
  echo "Error: $*" >&2
  echo >&2
  usage >&2
  exit 1
}

require_value() {
  if [[ $# -lt 2 || -z "${2:-}" || "${2:0:2}" == "--" ]]; then
    die "$1 requires a value."
  fi
}

require_file() {
  if [[ ! -f "$1" ]]; then
    die "$2 not found: $1"
  fi
}

require_dir() {
  if [[ ! -d "$1" ]]; then
    die "$2 not found: $1"
  fi
}

require_executable() {
  if [[ ! -x "$1" ]]; then
    die "$2 not found or not executable: $1"
  fi
}

load_gem5_args_file() {
  local args_file="$1"
  local -n out_array_ref="$2"

  require_file "$args_file" "Simulation config file"

  mapfile -t out_array_ref < <(
    sed \
      -e 's/[[:space:]]*#.*$//' \
      -e '/^[[:space:]]*$/d' \
      "$args_file"
  )
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export M5_PATH="${ROOT_DIR}/bin/m5"
GEM5_HOME="${ROOT_DIR}/gem5"
GEM5_CFG_CLASSIC="${GEM5_HOME}/configs/example/arm/starter_fs.py"
GEM5_CFG_TIMING_RUBY="${GEM5_HOME}/configs/example/arm/qpoints_mesi_fs.py"
GEM5_BIN_CLASSIC="${GEM5_HOME}/build/ARM/gem5.opt"
GEM5_BIN_TIMING_RUBY="${GEM5_HOME}/build/ARM_MESI_Two_Level/gem5.opt"
DEFAULT_CLASSIC_SIM_CONFIG="${ROOT_DIR}/configs/classic_atomic_gem5.args"
DEFAULT_TIMING_RUBY_SIM_CONFIG="${ROOT_DIR}/configs/timing_ruby_gem5.args"

GEM5_CKP_DIR=""
EXPERIMENT=""
SNAPSHOT=""
INST=""
CORES=""
SIM_CONFIG=""
BRANCH_TRACE_ARGS=()
DATA_TRACE_ARGS=()
TIMING_RUBY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gem5-ckp-dir)
      require_value "$1" "${2:-}"
      GEM5_CKP_DIR="$2"
      shift 2
      ;;
    --experiment)
      require_value "$1" "${2:-}"
      EXPERIMENT="$2"
      shift 2
      ;;
    --snapshot)
      require_value "$1" "${2:-}"
      SNAPSHOT="$2"
      shift 2
      ;;
    --inst)
      require_value "$1" "${2:-}"
      INST="$2"
      shift 2
      ;;
    --cores)
      require_value "$1" "${2:-}"
      CORES="$2"
      shift 2
      ;;
    --branch-trace)
      BRANCH_TRACE_ARGS=(--branch-trace)
      shift 1
      ;;
    --data-trace)
      DATA_TRACE_ARGS=(--data-trace)
      shift 1
      ;;
    --sim-config)
      require_value "$1" "${2:-}"
      SIM_CONFIG="$2"
      shift 2
      ;;
    --timing-ruby)
      TIMING_RUBY="1"
      shift 1
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

if [[ -z "$GEM5_CKP_DIR" || -z "$EXPERIMENT" || -z "$SNAPSHOT" || -z "$INST" || -z "$CORES" ]]; then
  die "Missing required arguments."
fi

CKPT_DIR="${GEM5_CKP_DIR}/${SNAPSHOT}"
DISK_IMAGE="${CKPT_DIR}/${SNAPSHOT}.img"
BOOTLOADER="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64"

OUTDIR="${ROOT_DIR}/sim_outs/${EXPERIMENT}/${SNAPSHOT}"
require_dir "$CKPT_DIR" "Checkpoint directory"
require_file "$DISK_IMAGE" "Checkpoint disk image"
require_file "$BOOTLOADER" "Bootloader"

mkdir -p "$OUTDIR"

if [[ -n "$TIMING_RUBY" ]]; then
  require_executable "$GEM5_BIN_TIMING_RUBY" "Timing Ruby gem5 binary"
  require_file "$GEM5_CFG_TIMING_RUBY" "Timing Ruby gem5 config"

  TIMING_RUBY_SIM_CONFIG="${SIM_CONFIG:-$DEFAULT_TIMING_RUBY_SIM_CONFIG}"
  TIMING_RUBY_CONFIG_ARGS=()
  load_gem5_args_file "$TIMING_RUBY_SIM_CONFIG" TIMING_RUBY_CONFIG_ARGS

  gem5_cmd=(
    "$GEM5_BIN_TIMING_RUBY"
    "--outdir=${OUTDIR}"
    "--debug-file=debug.insts"
    "$GEM5_CFG_TIMING_RUBY"
    -I "$INST"
    "--disk-image=${DISK_IMAGE}"
    "--bootloader=${BOOTLOADER}"
    --cpu-type O3CPU
    --bp-type TAGE
    --btb-entries 4096
    --restore "$CKPT_DIR"
    --num-cores "$CORES"
    --mem-size 16384MiB
    "${TIMING_RUBY_CONFIG_ARGS[@]}"
    "${BRANCH_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
  )
else
  require_executable "$GEM5_BIN_CLASSIC" "Classic gem5 binary"
  require_file "$GEM5_CFG_CLASSIC" "Classic gem5 config"

  CLASSIC_SIM_CONFIG="${SIM_CONFIG:-$DEFAULT_CLASSIC_SIM_CONFIG}"
  CLASSIC_CONFIG_ARGS=()
  load_gem5_args_file "$CLASSIC_SIM_CONFIG" CLASSIC_CONFIG_ARGS

  gem5_cmd=(
    "$GEM5_BIN_CLASSIC"
    "--outdir=${OUTDIR}"
    "--debug-file=debug.insts"
    "$GEM5_CFG_CLASSIC"
    -I "$INST"
    "--disk-image=${DISK_IMAGE}"
    "--bootloader=${BOOTLOADER}"
    --caches
    --cpu-type AtomicSimpleCPU
    --fdip
    --bp-type TAGE
    --restore "$CKPT_DIR"
    --num-cores "$CORES"
    --mem-size 16384MiB
    "${CLASSIC_CONFIG_ARGS[@]}"
    "${BRANCH_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
  )
fi

"${gem5_cmd[@]}"
