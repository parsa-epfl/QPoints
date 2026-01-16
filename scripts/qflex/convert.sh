BASE="web_search.qcow2"
SNAPSHOT="snapshot_0"

# 0) (optional) verify snapshot exists
qemu-img snapshot -l ${BASE}

# 1) make a copy (reflink if possible, otherwise normal copy)
echo "step1"
cp --reflink=auto ${BASE} tmp.qcow2 2>/dev/null || cp ${BASE} tmp.qcow2

# 2) set the *active* internal snapshot on the copy
echo "step2"
qemu-img snapshot -a ${SNAPSHOT} tmp.qcow2

# 3) convert the now-active state to raw
echo "step3"
qemu-img convert -p -f qcow2 -O raw tmp.qcow2 ${SNAPSHOT}.img

# 4) cleanup
echo "step4"
rm -f tmp.qcow2

