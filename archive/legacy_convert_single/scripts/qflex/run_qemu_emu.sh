#!/usr/bin/env bash
set -euo pipefail

# This script must be used in the folder where the qflex snapshot resides
usage() {
  cat <<'EOF'
Usage: run_qemu_emu.sh [CORES] [MEMORY] [BASE] [SNAPSHOT] [MONITOR_PORT] [QMP_PORT] [SSH_PORT]

MEMORY may be specified as a plain integer or with a QEMU size suffix,
for example 16384, 16384M, or 16G.

Warning:
  BASE is opened as a writable qcow2 image for checkpoint conversion. Guest
  writes will persist into that image unless you provide an explicit writable
  copy or overlay yourself.

Example:
  run_qemu_emu.sh 4 16G web_search.qcow2 snapshot_0 45454 4444 2222
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -lt 7 ]]; then
  usage >&2
  exit 1
fi

CORES="$1"
MEM="$2"
BASE="$3"
SNAPSHOT="$4"
MONITOR_PORT="$5"
QMP_PORT="$6"
SSH_PORT="$7"

BIOS_PATH="${QEMU_EFI_FD:-}"
if [[ -z "$BIOS_PATH" ]]; then
  for candidate in \
    "./QEMU_EFI.fd" \
    "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd" \
    "/usr/share/AAVMF/AAVMF_CODE.fd" \
    "/usr/share/edk2/aarch64/QEMU_EFI.fd"
  do
    if [[ -f "$candidate" ]]; then
      BIOS_PATH="$candidate"
      break
    fi
  done
fi

if [[ -z "$BIOS_PATH" || ! -f "$BIOS_PATH" ]]; then
  echo "Error: could not find UEFI firmware. Set QEMU_EFI_FD to a valid QEMU_EFI.fd/AAVMF_CODE.fd path." >&2
  exit 1
fi

echo "Warning: run_qemu_emu.sh opens ${BASE} as a writable qcow2 image; guest writes will persist into that file." >&2

exec ./qemu-system-aarch64 \
  -M virt,gic-version=max,virtualization=off,secure=off \
  -smp "$CORES" \
  -cpu max,pauth=off,sme=off \
  -m "$MEM" \
  -boot order=d,menu=on \
  -bios "$BIOS_PATH" \
  -drive "if=virtio,file=${BASE},format=qcow2" \
  -nic "user,model=virtio-net-pci,hostfwd=tcp::${SSH_PORT}-:22" \
  -rtc clock=vm \
  -loadvm "$SNAPSHOT" \
  -qmp "tcp:localhost:${QMP_PORT},server,nowait" -monitor "telnet::${MONITOR_PORT},server,nowait" \
  -nographic \
  -serial mon:stdio \
  -no-reboot
