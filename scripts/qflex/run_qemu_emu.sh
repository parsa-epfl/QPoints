#!/usr/bin/bash
# This script must be used in the folder where the qflex snapshot resides
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 7 ]]; then
  cat <<'EOF'
Usage: run_qemu_emu.sh [CORES] [MEM] [BASE] [SNAPSHOT] [MONITOR_PORT] [QMP_PORT] [SSH_PORT]

Example:
  run_qemu_emu.sh 4 16384 web_search.qcow2 snapshot_0 45454 4444 2222
EOF
  exit 1
fi

CORES="$1"
MEM="$2"
BASE="$3"
SNAPSHOT="$4"
MONITOR_PORT="$5"
QMP_PORT="$6"
SSH_PORT="$7"

./vanilla-qemu-system-aarch64 \
  -M virt,gic-version=max,virtualization=off,secure=off \
  -smp ${CORES} \
  -cpu max,pauth=off \
  -m ${MEM} \
  -boot order=d,menu=on \
  -bios ./QEMU_EFI.fd \
  -drive if=virtio,file=${BASE},format=qcow2,snapshot=on,tmp-snapshot-name=${SNAPSHOT} \
  -nic user,model=virtio-net-pci,hostfwd=tcp::${SSH_PORT}-:22 \
  -rtc clock=vm \
  -loadvm ${SNAPSHOT} \
  -qmp tcp:localhost:${QMP_PORT},server,nowait -monitor telnet::${MONITOR_PORT},server,nowait \
  -nographic \
  -serial mon:stdio \
  -no-reboot
