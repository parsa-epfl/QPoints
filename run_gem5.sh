#!/usr/bin/env bash

if [[ -z "${BASH_VERSINFO:-}" || "${BASH_VERSINFO[0]}" -lt 4 || ( "${BASH_VERSINFO[0]}" -eq 4 && "${BASH_VERSINFO[1]}" -lt 3 ) ]]; then
  echo "Error: run_gem5.sh requires Bash 4.3 or newer." >&2
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment NAME --snapshot NAME --inst N --cores N [--branch-trace] [--tage-decision-trace] [--data-trace] [--dump-cache-state] [--timing-ruby] [--timing-ruby-moesi] [--sim-config FILE]

Arguments (all required):
  --gem5-ckp-dir  Checkpoint root directory
  --experiment    Experiment name
  --snapshot      Snapshot name
  --inst          Instruction count
  --cores         Number of cores

Options:
  --branch-trace  Enable per-core branch trace logging in CSV format
  --tage-decision-trace
                  Enable per-core compact TAGE decision logging
  --data-trace    Enable per-core data access trace logging
  --dump-cache-state
                  Enable Ruby cache-state dumping (currently requires
                  the MESI timing-Ruby path)
  --timing-ruby   Use O3CPU with Ruby MESI_Two_Level. Without a timing-Ruby
                  flag, the existing starter_fs.py AtomicSimpleCPU config is
                  used.
  --timing-ruby-moesi
                  Use O3CPU with Ruby MOESI_CMP_directory and request the
                  staged LLC/L1 cache restore slices by default. If the
                  matching gem5_uarch artifacts are missing, gem5 will warn
                  and fall back to cold state for the missing slice.
  --sim-config    Optional file containing additional gem5 CLI arguments,
                  one per line. This is appended after the tracked default
                  config for the selected simulation path. This file owns
                  machine/model configuration only; runner-owned options are
                  rejected here.

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
      -e 's/^[[:space:]]*//' \
      -e 's/[[:space:]]*$//' \
      -e '/^[[:space:]]*$/d' \
      "$args_file"
  )
}

append_gem5_args_file() {
  local args_file="$1"
  local -n out_array_ref="$2"
  local file_args=()

  load_gem5_args_file "$args_file" file_args
  validate_sim_config_args "$args_file" "${file_args[@]}"
  out_array_ref+=("${file_args[@]}")
}

normalize_gem5_arg_key() {
  local arg="$1"
  case "$arg" in
    --*=*)
      printf "%s\n" "${arg%%=*}"
      ;;
    *)
      printf "%s\n" "$arg"
      ;;
  esac
}

validate_sim_config_args() {
  local args_file="$1"
  shift
  local arg key

  for arg in "$@"; do
    key="$(normalize_gem5_arg_key "$arg")"
    case "$key" in
      -I|--outdir|--debug-file|--disk-image|--bootloader|--cpu-type|--bp-type|--restore|--num-cores|--mem-size|--branch-trace|--tage-decision-trace|--data-trace|--dump-cache-state|--caches)
        die "${args_file} sets runner-owned option ${key}. Put run-shape and artifact toggles on run_gem5.sh itself; keep --sim-config for machine/model parameters only."
        ;;
    esac
  done
}

select_timing_ruby_protocol() {
  local protocol="$1"
  if [[ -n "$TIMING_RUBY_PROTOCOL" && "$TIMING_RUBY_PROTOCOL" != "$protocol" ]]; then
    die "Choose only one timing Ruby protocol flag."
  fi
  TIMING_RUBY_PROTOCOL="$protocol"
}

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  usage
  exit 0
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export M5_PATH="${ROOT_DIR}/bin/m5"
GEM5_HOME="${ROOT_DIR}/gem5"
GEM5_CFG_CLASSIC="${GEM5_HOME}/configs/example/arm/starter_fs.py"
# The current timing-Ruby FS launcher is shared by the MESI bring-up path
# and the early MOESI cold-bring-up path.
GEM5_CFG_TIMING_RUBY_FS="${GEM5_HOME}/configs/example/arm/qpoints_timing_ruby_fs.py"
GEM5_BIN_CLASSIC="${GEM5_HOME}/build/ARM/gem5.opt"
GEM5_BIN_TIMING_RUBY_MESI="${GEM5_HOME}/build/ARM_MESI_Two_Level/gem5.opt"
GEM5_BIN_TIMING_RUBY_MOESI="${GEM5_HOME}/build/ARM_MOESI_CMP_directory/gem5.opt"
DEFAULT_CLASSIC_SIM_CONFIG="${ROOT_DIR}/configs/classic_atomic_gem5.args"
DEFAULT_TIMING_RUBY_FRONTEND_SIM_CONFIG="${ROOT_DIR}/configs/timing_ruby_frontend_fdip.args"
DEFAULT_TIMING_RUBY_MESI_SIM_CONFIG="${ROOT_DIR}/configs/timing_ruby_gem5.args"
DEFAULT_TIMING_RUBY_MOESI_SIM_CONFIG="${ROOT_DIR}/configs/timing_ruby_moesi_gem5.args"

GEM5_CKP_DIR=""
EXPERIMENT=""
SNAPSHOT=""
INST=""
CORES=""
SIM_CONFIG=""
BRANCH_TRACE_ARGS=()
TAGE_DECISION_TRACE_ARGS=()
DATA_TRACE_ARGS=()
DUMP_CACHE_STATE_ARGS=()
TIMING_RUBY_PROTOCOL=""

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
    --tage-decision-trace)
      TAGE_DECISION_TRACE_ARGS=(--tage-decision-trace)
      shift 1
      ;;
    --data-trace)
      DATA_TRACE_ARGS=(--data-trace)
      shift 1
      ;;
    --dump-cache-state)
      DUMP_CACHE_STATE_ARGS=(--dump-cache-state)
      shift 1
      ;;
    --sim-config)
      require_value "$1" "${2:-}"
      SIM_CONFIG="$2"
      shift 2
      ;;
    --timing-ruby)
      select_timing_ruby_protocol "MESI_Two_Level"
      shift 1
      ;;
    --timing-ruby-moesi)
      select_timing_ruby_protocol "MOESI_CMP_directory"
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

if [[ -n "$SIM_CONFIG" ]]; then
  sim_config_validation_args=()
  load_gem5_args_file "$SIM_CONFIG" sim_config_validation_args
  validate_sim_config_args "$SIM_CONFIG" "${sim_config_validation_args[@]}"
fi

CKPT_DIR="${GEM5_CKP_DIR}/${SNAPSHOT}"
DISK_IMAGE="${CKPT_DIR}/${SNAPSHOT}.img"
BOOTLOADER="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64"

OUTDIR="${ROOT_DIR}/sim_outs/${EXPERIMENT}/${SNAPSHOT}"
require_dir "$CKPT_DIR" "Checkpoint directory"
require_file "$DISK_IMAGE" "Checkpoint disk image"
require_file "$BOOTLOADER" "Bootloader"

mkdir -p "$OUTDIR"

if [[ "${#DUMP_CACHE_STATE_ARGS[@]}" -gt 0 && -z "$TIMING_RUBY_PROTOCOL" ]]; then
  die "--dump-cache-state requires a timing Ruby mode."
fi

if [[ "${#DUMP_CACHE_STATE_ARGS[@]}" -gt 0 && "$TIMING_RUBY_PROTOCOL" != "MESI_Two_Level" ]]; then
  die "--dump-cache-state is currently supported only on the MESI timing-Ruby path."
fi

if [[ -n "$TIMING_RUBY_PROTOCOL" ]]; then
  timing_ruby_bin=""
  timing_ruby_cfg="$GEM5_CFG_TIMING_RUBY_FS"
  timing_ruby_default_sim_config=""
  TIMING_RUBY_RESTORE_ARGS=()

  case "$TIMING_RUBY_PROTOCOL" in
    MESI_Two_Level)
      timing_ruby_bin="$GEM5_BIN_TIMING_RUBY_MESI"
      timing_ruby_default_sim_config="$DEFAULT_TIMING_RUBY_MESI_SIM_CONFIG"
      ;;
    MOESI_CMP_directory)
      timing_ruby_bin="$GEM5_BIN_TIMING_RUBY_MOESI"
      timing_ruby_default_sim_config="$DEFAULT_TIMING_RUBY_MOESI_SIM_CONFIG"
      TIMING_RUBY_RESTORE_ARGS=(
        --restore-llc-state
        --restore-l1d-state
        --restore-l1i-state
      )
      ;;
    *)
      die "Unsupported timing Ruby protocol: $TIMING_RUBY_PROTOCOL"
      ;;
  esac

  require_executable "$timing_ruby_bin" "Timing Ruby gem5 binary"
  require_file "$timing_ruby_cfg" "Timing Ruby gem5 config"
  require_file "$DEFAULT_TIMING_RUBY_FRONTEND_SIM_CONFIG" "Timing Ruby frontend config"
  require_file "$timing_ruby_default_sim_config" "Timing Ruby default config"

  TIMING_RUBY_CONFIG_ARGS=()
  append_gem5_args_file "$DEFAULT_TIMING_RUBY_FRONTEND_SIM_CONFIG" TIMING_RUBY_CONFIG_ARGS
  append_gem5_args_file "$timing_ruby_default_sim_config" TIMING_RUBY_CONFIG_ARGS
  if [[ -n "$SIM_CONFIG" ]]; then
    append_gem5_args_file "$SIM_CONFIG" TIMING_RUBY_CONFIG_ARGS
  fi

  gem5_cmd=(
    "$timing_ruby_bin"
    "--outdir=${OUTDIR}"
    "--debug-file=debug.insts"
    "$timing_ruby_cfg"
    -I "$INST"
    "--disk-image=${DISK_IMAGE}"
    "--bootloader=${BOOTLOADER}"
    --cpu-type O3CPU
    --bp-type TAGE
    --restore "$CKPT_DIR"
    --num-cores "$CORES"
    --mem-size 16384MiB
    "${TIMING_RUBY_RESTORE_ARGS[@]}"
    "${TIMING_RUBY_CONFIG_ARGS[@]}"
    "${BRANCH_TRACE_ARGS[@]}"
    "${TAGE_DECISION_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
    "${DUMP_CACHE_STATE_ARGS[@]}"
  )
else
  require_executable "$GEM5_BIN_CLASSIC" "Classic gem5 binary"
  require_file "$GEM5_CFG_CLASSIC" "Classic gem5 config"

  CLASSIC_CONFIG_ARGS=()
  load_gem5_args_file "$DEFAULT_CLASSIC_SIM_CONFIG" CLASSIC_CONFIG_ARGS
  if [[ -n "$SIM_CONFIG" ]]; then
    append_gem5_args_file "$SIM_CONFIG" CLASSIC_CONFIG_ARGS
  fi

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
    "${TAGE_DECISION_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
  )
fi

"${gem5_cmd[@]}"
