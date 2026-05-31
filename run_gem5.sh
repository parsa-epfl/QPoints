if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment NAME --snapshot NAME --inst N --cores N [--branch-trace] [--va-file FILE] [--tlb-output-dir DIR] [--generate-checkpoint]

Arguments (all required):
  --gem5-ckp-dir  Checkpoint root directory
  --experiment    Experiment name
  --snapshot      Snapshot name
  --inst          Instruction count
  --cores         Number of cores

Optional:
  --branch-trace  Enable per-core branch trace logging
  --va-file FILE  WormCacheQFlex MMU snapshot JSON (e.g. mmus-0.json);
                  runs VA->PA translations at startup then exits
  --tlb-output-dir DIR  Output directory for TLB checkpoint files (default: gem5 checkpoint dir)
  --generate-checkpoint  Generate a checkpoint at the end of simulation

Example:
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment OoO --snapshot snapshot_0 --inst 100000 --cores 1 --branch-trace --va-file mmus-0.json --tlb-output-dir /output --generate-checkpoint
EOF
  exit 0
fi

export M5_PATH=$(pwd)/bin/m5
GEM5_HOME=$(pwd)/gem5
GEM5_CFG=$GEM5_HOME/configs/example/arm/starter_fs.py

GEM5_CKP_DIR=""
EXPERIMENT=""
SNAPSHOT=""
INST=""
CORES=""
BRANCH_TRACE=""
VA_FILE=""
TLB_OUTPUT_DIR=""
GENERATE_CHECKPOINT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gem5-ckp-dir)
      GEM5_CKP_DIR="$2"
      shift 2
      ;;
    --experiment)
      EXPERIMENT="$2"
      shift 2
      ;;
    --snapshot)
      SNAPSHOT="$2"
      shift 2
      ;;
    --inst)
      INST="$2"
      shift 2
      ;;
    --cores)
      CORES="$2"
      shift 2
      ;;
    --branch-trace)
      BRANCH_TRACE="--branch-trace"
      shift 1
      ;;
    --va-file)
      VA_FILE="$2"
      shift 2
      ;;
    --tlb-output-dir)
      TLB_OUTPUT_DIR="$2"
      shift 2
      ;;
    --generate-checkpoint)
      GENERATE_CHECKPOINT="--generate-checkpoint"
      shift 1
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [[ -z "$GEM5_CKP_DIR" || -z "$EXPERIMENT" || -z "$SNAPSHOT" || -z "$INST" || -z "$CORES" ]]; then
  echo "Missing required arguments."
  exit 1
fi

CKPT_DIR="${GEM5_CKP_DIR}/${SNAPSHOT}.gem"

if [[ -z "$TLB_OUTPUT_DIR" ]]; then
  TLB_OUTPUT_DIR="$CKPT_DIR"
fi

OUTDIR=sim_outs/${EXPERIMENT}/${SNAPSHOT}
mkdir -p $OUTDIR
touch ${OUTDIR}

$GEM5_HOME/build/ARM/gem5.opt  --outdir=${OUTDIR} --debug-flags=TLB,TLBVerbose,VATranslator --debug-file=debug.insts  $GEM5_CFG -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --bootloader="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64" --caches --cpu-type AtomicSimpleCPU --fdip --bp-type TAGE --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 8192MiB --mem-channels=1 ${BRANCH_TRACE} ${VA_FILE:+--va-file $VA_FILE} ${TLB_OUTPUT_DIR:+--tlb-output-dir $TLB_OUTPUT_DIR} ${GENERATE_CHECKPOINT}
