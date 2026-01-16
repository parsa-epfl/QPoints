BASE="root.qcow2"
SNAPSHOT="boot"
CLEAN="clean.qcow2"

# 0) sanity check snapshot exists
qemu-img snapshot -l ${BASE}

# 1) make a copy so you don't touch the original
cp --reflink=auto ${BASE} tmp_booted.qcow2 2>/dev/null || cp ${BASE} tmp_booted.qcow2

# 2) apply the snapshot to the copy (this changes the copy's "current" state)
qemu-img snapshot -a ${SNAPSHOT} tmp_booted.qcow2

# 3) convert to a fresh qcow2 (no internal snapshots)
qemu-img convert -f qcow2 -O qcow2 tmp_booted.qcow2 ${CLEAN}

# 4) optional cleanup
rm -f tmp_booted.qcow2

