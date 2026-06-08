#!/usr/bin/env bash

if [[ -z "${BASH_VERSINFO:-}" || "${BASH_VERSINFO[0]}" -lt 4 || ( "${BASH_VERSINFO[0]}" -eq 4 && "${BASH_VERSINFO[1]}" -lt 3 ) ]]; then
  echo "Error: run_gem5.sh requires Bash 4.3 or newer." >&2
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment-name NAME --snapshot NAME --core-count N [--memory-gb N] [--bootloader FILE] [--root-device DEV] [--itb-size N] [--dtb-size N] [--have-large-asid-64 | --no-large-asid-64] [--inst N | --measurement-cycles N [--warmup-cycles N]] [--branch-trace] [--tage-decision-trace] [--data-trace] [--dump-cache-state] [--timing-ruby] [--timing-ruby-moesi] [--no-cache-hierarchy-restore] [--sim-config FILE]

Arguments:
  --gem5-ckp-dir  Checkpoint root directory
  --experiment-name
                  Experiment name
  --snapshot      Snapshot name
  --core-count    Number of cores
  --memory-gb     Memory size in GB (default: 16)
  --bootloader    Bootloader image to supply to gem5. Defaults to bin/m5/binaries/boot_v2_qemu_virt.arm64
  --root-device   Root device to pass to gem5 full-system configs (default: /dev/vda)
  --itb-size      Instruction TLB size to pass to gem5 (default: 64)
  --dtb-size      Data TLB size to pass to gem5 (default: 64)
  --have-large-asid-64 / --no-large-asid-64
                  Control the gem5 large-ASID mode for TLB restore and runtime config
  --inst          Instruction count for legacy instruction-bounded runs
  --warmup-cycles Detailed warmup window in CPU cycles (timing Ruby only)
  --measurement-cycles
                  Measurement window in CPU cycles (timing Ruby only)

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
  --no-cache-hierarchy-restore
                  Disable the MOESI LLC/L1 cache-hierarchy restore flags while
                  leaving other restore-related options in the selected
                  sim-config untouched.
  --sim-config    Optional file containing additional gem5 CLI arguments,
                  one per line. This is appended after the tracked default
                  config for the selected simulation path. This file owns
                  machine/model configuration only; runner-owned options are
                  rejected here.

Example:
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment-name OoO --snapshot snapshot_0 --inst 100000 --core-count 1 --branch-trace
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment-name OoO --snapshot snapshot_0 --core-count 8 --timing-ruby-moesi --warmup-cycles 200000 --measurement-cycles 100000
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
      -I|--outdir|--debug-file|--disk-image|--bootloader|--root-device|--cpu-type|--bp-type|--restore|--num-cores|--mem-size|--branch-trace|--tage-decision-trace|--data-trace|--dump-cache-state|--caches|--warmup-cycles|--measurement-cycles)
        die "${args_file} sets runner-owned option ${key}. Put run-shape and artifact toggles on run_gem5.sh itself; keep --sim-config for machine/model parameters only."
        ;;
    esac
  done
}

extract_machine_geometry_args() {
  local -n inout_array_ref="$1"
  local filtered=()
  local arg value

  for arg in "${inout_array_ref[@]}"; do
    case "$arg" in
      --itb-size=*)
        value="${arg#*=}"
        [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "Invalid --itb-size value in sim-config: $value"
        ITB_SIZE="$value"
        ;;
      --dtb-size=*)
        value="${arg#*=}"
        [[ "$value" =~ ^[1-9][0-9]*$ ]] || die "Invalid --dtb-size value in sim-config: $value"
        DTB_SIZE="$value"
        ;;
      --have-large-asid-64)
        HAVE_LARGE_ASID_64=1
        ;;
      --no-large-asid-64)
        HAVE_LARGE_ASID_64=0
        ;;
      *)
        filtered+=("$arg")
        ;;
    esac
  done

  inout_array_ref=("${filtered[@]}")
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
TIMING_UIPC_SUMMARY_SCRIPT="${ROOT_DIR}/scripts/timing/summarize_gem5_uipc.py"

GEM5_CKP_DIR=""
EXPERIMENT_NAME=""
SNAPSHOT=""
INST=""
WARMUP_CYCLES=""
MEASUREMENT_CYCLES=""
CORE_COUNT=""
MEMORY_GB="16"
KERNEL=""
BOOTLOADER=""
ROOT_DEVICE="/dev/vda"
ITB_SIZE="64"
DTB_SIZE="64"
HAVE_LARGE_ASID_64=1
SIM_CONFIG=""
RESTORE_CACHE_HIERARCHY=1
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
    --experiment-name|--experiment)
      require_value "$1" "${2:-}"
      EXPERIMENT_NAME="$2"
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
    --warmup-cycles)
      require_value "$1" "${2:-}"
      WARMUP_CYCLES="$2"
      shift 2
      ;;
    --measurement-cycles)
      require_value "$1" "${2:-}"
      MEASUREMENT_CYCLES="$2"
      shift 2
      ;;
    --core-count|--cores)
      require_value "$1" "${2:-}"
      CORE_COUNT="$2"
      shift 2
      ;;
    --memory-gb)
      require_value "$1" "${2:-}"
      MEMORY_GB="$2"
      shift 2
      ;;
    --bootloader)
      require_value "$1" "${2:-}"
      BOOTLOADER="$2"
      shift 2
      ;;
    --root-device)
      require_value "$1" "${2:-}"
      ROOT_DEVICE="$2"
      shift 2
      ;;
    --itb-size)
      require_value "$1" "${2:-}"
      ITB_SIZE="$2"
      shift 2
      ;;
    --dtb-size)
      require_value "$1" "${2:-}"
      DTB_SIZE="$2"
      shift 2
      ;;
    --have-large-asid-64)
      HAVE_LARGE_ASID_64=1
      shift 1
      ;;
    --no-large-asid-64)
      HAVE_LARGE_ASID_64=0
      shift 1
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
    --no-cache-hierarchy-restore)
      RESTORE_CACHE_HIERARCHY=0
      shift 1
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

if [[ -z "$GEM5_CKP_DIR" || -z "$EXPERIMENT_NAME" || -z "$SNAPSHOT" || -z "$CORE_COUNT" ]]; then
  die "Missing required arguments."
fi

if [[ ! "$MEMORY_GB" =~ ^[1-9][0-9]*$ ]]; then
  die "--memory-gb must be a positive integer."
fi
MEM_SIZE_MIB=$((MEMORY_GB * 1024))

if [[ -n "$MEASUREMENT_CYCLES" || -n "$WARMUP_CYCLES" ]]; then
  if [[ -z "$TIMING_RUBY_PROTOCOL" ]]; then
    die "Cycle-window timing requires a timing Ruby mode."
  fi
  if [[ -n "$INST" ]]; then
    die "Do not mix --inst with --warmup-cycles/--measurement-cycles."
  fi
  if [[ -z "$MEASUREMENT_CYCLES" ]]; then
    die "--warmup-cycles requires --measurement-cycles."
  fi
else
  if [[ -z "$INST" ]]; then
    die "Missing required arguments."
  fi
fi

if [[ -n "$SIM_CONFIG" ]]; then
  sim_config_validation_args=()
  load_gem5_args_file "$SIM_CONFIG" sim_config_validation_args
  validate_sim_config_args "$SIM_CONFIG" "${sim_config_validation_args[@]}"
fi

CKPT_DIR="${GEM5_CKP_DIR}/${SNAPSHOT}"
DISK_IMAGE="${CKPT_DIR}/${SNAPSHOT}.img"
if [[ -z "$BOOTLOADER" ]]; then
  BOOTLOADER="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64"
fi

if [[ ! "$ITB_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  die "--itb-size must be a positive integer."
fi
if [[ ! "$DTB_SIZE" =~ ^[1-9][0-9]*$ ]]; then
  die "--dtb-size must be a positive integer."
fi

OUTDIR="${ROOT_DIR}/sim_outs/${EXPERIMENT_NAME}/${SNAPSHOT}"
require_dir "$CKPT_DIR" "Checkpoint directory"
require_file "$DISK_IMAGE" "Checkpoint disk image"
require_file "$BOOTLOADER" "Bootloader"

if [[ "${#DUMP_CACHE_STATE_ARGS[@]}" -gt 0 && -z "$TIMING_RUBY_PROTOCOL" ]]; then
  die "--dump-cache-state requires a timing Ruby mode."
fi

if [[ "${#DUMP_CACHE_STATE_ARGS[@]}" -gt 0 && "$TIMING_RUBY_PROTOCOL" != "MESI_Two_Level" ]]; then
  die "--dump-cache-state is currently supported only on the MESI timing-Ruby path."
fi

MACHINE_CONFIG="${CKPT_DIR}/machine_config.json"
require_file "$MACHINE_CONFIG" "Checkpoint machine config"

checkpoint_kernel_contract="$(python3 - "$MACHINE_CONFIG" <<'PY'
import json
import os
import sys
from pathlib import Path

machine_config_path = Path(sys.argv[1])
machine_config = json.loads(machine_config_path.read_text(encoding="utf-8"))
status = machine_config.get("kernel_capture_status", "")
kernel_value = machine_config.get("kernel", "")
kernel_bundle_dir = machine_config.get("kernel_bundle_dir", "")

if status != "ready":
    print(
        f"Checkpoint kernel contract is not ready (kernel_capture_status={status!r}). "
        "Complete the lineage kernel bundle before running gem5.",
        file=sys.stderr,
    )
    sys.exit(2)

if not kernel_value:
    print("Checkpoint machine config is missing kernel.", file=sys.stderr)
    sys.exit(2)

if not kernel_bundle_dir:
    print("Checkpoint machine config is missing kernel_bundle_dir.", file=sys.stderr)
    sys.exit(2)

kernel_path = Path(os.path.abspath(Path(kernel_value).expanduser()))
kernel_dir = Path(os.path.abspath(Path(kernel_bundle_dir).expanduser()))

if not kernel_dir.is_dir():
    print(f"Checkpoint kernel bundle directory not found: {kernel_dir}", file=sys.stderr)
    sys.exit(2)

if not kernel_path.is_file():
    print(f"Checkpoint kernel not found: {kernel_path}", file=sys.stderr)
    sys.exit(2)

if kernel_path.parent != kernel_dir:
    print(
        f"Checkpoint kernel path is not under checkpoint kernel bundle dir: "
        f"{kernel_path} not under {kernel_dir}",
        file=sys.stderr,
    )
    sys.exit(2)

print(str(kernel_path))
PY
)" || die "Failed to resolve a ready kernel from ${MACHINE_CONFIG}."

KERNEL="${checkpoint_kernel_contract}"
require_file "$KERNEL" "Kernel image"

mkdir -p "$OUTDIR"

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
      if [[ "$RESTORE_CACHE_HIERARCHY" -eq 1 ]]; then
        TIMING_RUBY_RESTORE_ARGS=(
          --restore-llc-state
          --restore-l1d-state
          --restore-l1i-state
        )
      fi
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
  extract_machine_geometry_args TIMING_RUBY_CONFIG_ARGS

  TIMING_WINDOW_ARGS=()
  if [[ -n "$MEASUREMENT_CYCLES" ]]; then
    if [[ -n "$WARMUP_CYCLES" ]]; then
      TIMING_WINDOW_ARGS+=(--warmup-cycles "$WARMUP_CYCLES")
    fi
    TIMING_WINDOW_ARGS+=(--measurement-cycles "$MEASUREMENT_CYCLES")
  else
    TIMING_WINDOW_ARGS+=(-I "$INST")
  fi

  gem5_cmd=(
    "$timing_ruby_bin"
    "--outdir=${OUTDIR}"
    "--debug-file=debug.insts"
    "$timing_ruby_cfg"
    "${TIMING_WINDOW_ARGS[@]}"
    "--disk-image=${DISK_IMAGE}"
    "--bootloader=${BOOTLOADER}"
    "--kernel=${KERNEL}"
    "--root-device=${ROOT_DEVICE}"
    --cpu-type O3CPU
    --bp-type TAGE
    --restore "$CKPT_DIR"
    --num-cores "$CORE_COUNT"
    --mem-size "${MEM_SIZE_MIB}MiB"
    "--itb-size=${ITB_SIZE}"
    "--dtb-size=${DTB_SIZE}"
    "${TIMING_RUBY_RESTORE_ARGS[@]}"
    "${TIMING_RUBY_CONFIG_ARGS[@]}"
    "${BRANCH_TRACE_ARGS[@]}"
    "${TAGE_DECISION_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
    "${DUMP_CACHE_STATE_ARGS[@]}"
  )
  if [[ "$HAVE_LARGE_ASID_64" -eq 1 ]]; then
    gem5_cmd+=(--have-large-asid-64)
  fi
else
  require_executable "$GEM5_BIN_CLASSIC" "Classic gem5 binary"
  require_file "$GEM5_CFG_CLASSIC" "Classic gem5 config"

  CLASSIC_CONFIG_ARGS=()
  load_gem5_args_file "$DEFAULT_CLASSIC_SIM_CONFIG" CLASSIC_CONFIG_ARGS
  if [[ -n "$SIM_CONFIG" ]]; then
    append_gem5_args_file "$SIM_CONFIG" CLASSIC_CONFIG_ARGS
  fi
  extract_machine_geometry_args CLASSIC_CONFIG_ARGS

  gem5_cmd=(
    "$GEM5_BIN_CLASSIC"
    "--outdir=${OUTDIR}"
    "--debug-file=debug.insts"
    "$GEM5_CFG_CLASSIC"
    -I "$INST"
    "--disk-image=${DISK_IMAGE}"
    "--bootloader=${BOOTLOADER}"
    "--kernel=${KERNEL}"
    "--root-device=${ROOT_DEVICE}"
    --caches
    --cpu-type AtomicSimpleCPU
    --fdip
    --bp-type TAGE
    --restore "$CKPT_DIR"
    --num-cores "$CORE_COUNT"
    --mem-size "${MEM_SIZE_MIB}MiB"
    "--itb-size=${ITB_SIZE}"
    "--dtb-size=${DTB_SIZE}"
    "${CLASSIC_CONFIG_ARGS[@]}"
    "${BRANCH_TRACE_ARGS[@]}"
    "${TAGE_DECISION_TRACE_ARGS[@]}"
    "${DATA_TRACE_ARGS[@]}"
  )
  if [[ "$HAVE_LARGE_ASID_64" -eq 1 ]]; then
    gem5_cmd+=(--have-large-asid-64)
  fi
fi

"${gem5_cmd[@]}"

if [[ -f "$OUTDIR/stats_final.txt" ]]; then
  mv -f "$OUTDIR/stats_final.txt" "$OUTDIR/stats.txt"
fi

if [[ -n "$MEASUREMENT_CYCLES" ]]; then
  require_executable "$TIMING_UIPC_SUMMARY_SCRIPT" "gem5 uIPC summary script"
  python3 "$TIMING_UIPC_SUMMARY_SCRIPT" \
    --stats-file "$OUTDIR/stats.txt" \
    --experiment "$EXPERIMENT_NAME" \
    --snapshot "$SNAPSHOT" \
    --output-json "$OUTDIR/uipc_summary.json"
fi
