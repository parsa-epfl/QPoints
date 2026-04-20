if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment NAME --snapshot NAME --inst N --cores N [--branch-trace] [--timing-ruby]

Arguments (all required):
  --gem5-ckp-dir  Checkpoint root directory
  --experiment    Experiment name
  --snapshot      Snapshot name
  --inst          Instruction count
  --cores         Number of cores

Options:
  --branch-trace  Enable per-core branch trace logging
  --timing-ruby   Use O3CPU with Ruby MESI_Two_Level. Without this flag,
                  the existing starter_fs.py AtomicSimpleCPU config is used.

Example:
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment OoO --snapshot snapshot_0 --inst 100000 --cores 1 --branch-trace
EOF
  exit 0
fi

export M5_PATH=$(pwd)/bin/m5
GEM5_HOME=$(pwd)/gem5
GEM5_CFG_CLASSIC=$GEM5_HOME/configs/example/arm/starter_fs.py
GEM5_CFG_TIMING_RUBY=$GEM5_HOME/configs/example/arm/qpoints_mesi_fs.py

GEM5_CKP_DIR=""
EXPERIMENT=""
SNAPSHOT=""
INST=""
CORES=""
BRANCH_TRACE=""
TIMING_RUBY=""

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
    --timing-ruby)
      TIMING_RUBY="1"
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

CKPT_DIR="${GEM5_CKP_DIR}/${SNAPSHOT}"

OUTDIR=sim_outs/${EXPERIMENT}/${SNAPSHOT}
mkdir -p $OUTDIR
touch ${OUTDIR}

if [[ -n "$TIMING_RUBY" ]]; then
  $GEM5_HOME/build/ARM_MESI_Two_Level/gem5.opt --outdir=${OUTDIR} --debug-file=debug.insts $GEM5_CFG_TIMING_RUBY -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --bootloader="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64" --cpu-type O3CPU --bp-type TAGE --btb-entries 4096 --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 16384MiB --mem-channels=2 ${BRANCH_TRACE}
else
  $GEM5_HOME/build/ARM/gem5.opt --outdir=${OUTDIR} --debug-file=debug.insts $GEM5_CFG_CLASSIC -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --bootloader="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64" --caches --cpu-type AtomicSimpleCPU --fdip --bp-type TAGE --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 16384MiB --mem-channels=2 ${BRANCH_TRACE}
fi
