ckp_dir="${1:-checkpoints/workload}"
snapshot="${2:-"snapshots_0"}"
image="${3:-"snaphots_0.img"}"

mkdir -p ${ckp_dir}/${snapshot}
rm -rf ${ckp_dir}/${snapshot}

cd scripts
python3 create_snapshot.py --disk-image $image --copy-disk-img --dest-dir ${ckp_dir}/${snapshot}
cd ..

echo "A checkpoint is created at ${ckp_dir}/${snapshot} directory"
