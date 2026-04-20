if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: run_gem5.sh --gem5-ckp-dir DIR --experiment NAME --snapshot NAME --inst N --cores N [--branch-trace]

Arguments (all required):
  --gem5-ckp-dir  Checkpoint root directory
  --experiment    Experiment name
  --snapshot      Snapshot name
  --inst          Instruction count
  --cores         Number of cores

Example:
  run_gem5.sh --gem5-ckp-dir /checkpoints --experiment OoO --snapshot snapshot_0 --inst 100000 --cores 1 --branch-trace
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

OUTDIR=sim_outs/${EXPERIMENT}/${SNAPSHOT}
mkdir -p $OUTDIR
touch ${OUTDIR}

$GEM5_HOME/build/ARM/gem5.opt --debug-flags=All --outdir=${OUTDIR} --debug-file=debug.insts  $GEM5_CFG -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --cpu atomic --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 8192MiB --mem-channels=1
