export M5_PATH=$(pwd)/bin/m5
GEM5_HOME=$(pwd)/gem5
GEM5_CFG=$GEM5_HOME/configs/example/arm/starter_fs.py


WORKLOAD="web_search"
SNAPSHOT="snapshot_0"
CKPT_DIR=/checkpoints/${WORKLOAD}/${SNAPSHOT}

OUTDIR=sim_outs/${WORKLOAD}/${SNAPSHOT}
mkdir -p $OUTDIR
touch ${OUTDIR}

INST=100000
CORES=1

$GEM5_HOME/build/ARM/gem5.opt  --outdir=${OUTDIR} --debug-file=debug.insts  $GEM5_CFG -I $INST --disk-image="${CKPT_DIR}/${SNAPSHOT}.img" --bootloader="${M5_PATH}/binaries/boot_v2_qemu_virt.arm64" --caches --cpu-type AtomicSimpleCPU --fdip --bp-type TAGE --restore "${CKPT_DIR}" --num-cores ${CORES} --mem-size 16384MiB --mem-channels=2
