if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  cat <<'EOF'
Usage: gen_snapshot.sh [ckp_dir] [snapshot] [image] [copy_img] [num_cores]

Arguments (all optional):
  ckp_dir      Checkpoint root directory (default: checkpoints/workload)
  snapshot     Snapshot subdirectory name (default: snapshots_0)
  image        Disk image filename; used only when copy_img is enabled (default: snaphots_0.img)
  copy_img     Copy disk image into snapshot dir: 1|true|yes (default: 0, requires image)
  num_cores    Number of cores for snapshot (default: 1)

Example:
  gen_snapshot.sh checkpoints/workload snapshots_0 my.img true 4
EOF
  exit 0
fi

ckp_dir="${1:-checkpoints/workload}"
snapshot="${2:-"snapshots_0"}"
image="${3:-"snaphots_0.img"}"
copy_img="${4:-0}"
num_cores="${5:-1}"

copy_arg=""
disk_arg=""
if [[ "$copy_img" == "1" || "$copy_img" == "true" || "$copy_img" == "yes" ]]; then
  copy_arg="--copy-disk-img"
  disk_arg="--disk-image \"$image\""
fi

dest_dir="${ckp_dir}/${snapshot}"
if [[ -d "$dest_dir" ]]; then
  echo "Destination directory already exists: $dest_dir"
  printf "Delete it and proceed? [y/n]: " > /dev/tty
  read -r resp < /dev/tty
  case "$resp" in
    y|Y|yes|YES)
      rm -rf "$dest_dir"
      ;;
    n|N|no|NO)
      echo "Aborting."
      exit 1
      ;;
    *)
      echo "Unrecognized response. Aborting."
      exit 1
      ;;
  esac
fi

mkdir -p "$dest_dir"

cd scripts
python3 create_snapshot.py $disk_arg $copy_arg --dest-dir ${ckp_dir}/${snapshot} --num-cores "$num_cores"
cd ..

echo "A checkpoint is created at ${ckp_dir}/${snapshot} directory"
