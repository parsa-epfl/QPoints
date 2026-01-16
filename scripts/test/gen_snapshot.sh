ckp_dir=$1
snapshot=$2
image=$3

mkdir -p ${ckp_dir}/${snapshot}
rm -rf ${ckp_dir}/${snapshot}

cd scripts
python3 create_snapshot.py --disk-image $image --copy-disk-img --dest-dir ${ckp_dir}/${snapshot}
cd ..

echo "A checkpoint is created at ${ckp_dir}/${snapshot} directory"
