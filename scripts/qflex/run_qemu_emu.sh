#!/usr/bin/bash
# This script must be used in the folder where the qflex snapshot resides
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 4 ]]; then
  cat <<'EOF'
Usage: run_qemu_emu.sh [CORES] [MEM] [BASE] [SNAPSHOT]

Example:
  run_qemu_emu.sh 4 16384 web_search.qcow2 snapshot_0
EOF
  exit 1
fi

CORES="$1"
MEM="$2"
BASE="$3"
SNAPSHOT="$4"

./qemu-system-aarch64 \
  -M virt,gic-version=max,virtualization=off,secure=off \
  -smp ${CORES} \
  -cpu max,pauth=off \
  -m ${MEM} \
  -boot order=d,menu=on \
  -bios ./QEMU_EFI.fd \
  -drive if=virtio,file=${BASE},format=qcow2 \
  -nic user,model=virtio-net-pci,hostfwd=tcp::2222-:22 \
  -rtc clock=vm \
  -loadvm ${SNAPSHOT} \
  -qmp tcp:localhost:4444,server,nowait -monitor telnet::45454,server,nowait \
  -nographic \
  -serial mon:stdio \
  -no-reboot
