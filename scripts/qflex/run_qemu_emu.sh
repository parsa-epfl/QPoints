#!/usr/bin/bash
# This script must be used in the folder where the qflex snapshot resides
CORES=4
MEM=16384
BASE=web_search.qcow2
SNAPSHOT="snapshot_0"

./qemu-system-aarch64 \
  -M virt,gic-version=max,virtualization=off,secure=off \
  -smp ${CORES} \
  -cpu max,pauth=off \
  -m ${MEM} \
  -boot order=d,menu=on \
  -bios ./QEMU_EFI.fd \
  -drive if=virtio,file=${BASE},format=qcow2 \
  -nic user,model=virtio-net-pci \
  -rtc clock=vm \
  -loadvm ${SNAPSHOT} \
  -qmp tcp:localhost:4444,server,nowait -monitor telnet::45454,server,nowait \
  -nographic \
  -serial mon:stdio \
  -no-reboot
