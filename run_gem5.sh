if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: run_gem5.sh [--ckpt-base DIR] [--workload NAME] [--snapshot NAME] [--inst N] [--cores N]

Arguments (all optional):
  --ckpt-base  Checkpoint base directory (default: /checkpoints)
  --workload   Workload name (default: web_search)
  --snapshot   Snapshot name (default: snapshot_0)
  --inst       Instruction count (default: 100000)
  --cores      Number of cores (default: 1)

Example:
  run_gem5.sh --ckpt-base /checkpoints --workload web_search --snapshot snapshot_0 --inst 100000 --cores 1
EOF
  exit 0
fi

export M5_PATH=$(pwd)/bin/m5
GEM5_HOME=$(pwd)/gem5
GEM5_CFG=$GEM5_HOME/configs/example/arm/starter_fs.py

CKPT_BASE="/checkpoints"
WORKLOAD="web_search"
SNAPSHOT="snapshot_0"
INST=100000
CORES=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ckpt-base)
      CKPT_BASE="$2"
      shift 2
      ;;
    --workload)
      WORKLOAD="$2"
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
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done
CKPT_DIR="${CKPT_BASE}/${WORKLOAD}/${SNAPSHOT}"

OUTDIR=sim_outs/${WORKLOAD}/${SNAPSHOT}
mkdir -p $OUTDIR
touch ${OUTDIR}

$GEM5_HOME/build/ARM/gem5.opt  --outdir=${OUTDIR} --debug-file=debug.insts  $GEM5_CFG -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --bootloader="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64" --caches --cpu-type AtomicSimpleCPU --fdip --bp-type TAGE --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 16384MiB --mem-channels=2
