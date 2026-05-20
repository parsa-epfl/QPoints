# Reproduction Commands

These are the exact host/guest commands used for the accepted validation pass.

## 1. Launch QEMU prep VM from `snapshot_1`

```bash
cd /mnt/sdb/aansari/experiments/single-core/run
./run_qemu_emu.sh 1 16G single-core.qcow2 snapshot_1 45456 4446 2224
```

## 2. Stop the resident benchmark in the guest

```bash
SSHPASS=qflex sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -p 2224 qflex@127.0.0.1 \
  'kill -TERM 2280 || true'
```

## 3. Stage the guest binary and launch it into the checkpoint window

```bash
SSHPASS=qflex sshpass -e scp -O -P 2224 -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null \
  /home/dev/qflex_git/QPoints/scripts/validation/disk_smoke/guest_disk_trace_ubench.arm64 \
  qflex@127.0.0.1:/tmp/guest_disk_trace_ubench.arm64
```

```bash
SSHPASS=qflex sshpass -e ssh -o StrictHostKeyChecking=no \
  -o UserKnownHostsFile=/dev/null -p 2224 qflex@127.0.0.1 \
  'nohup /tmp/guest_disk_trace_ubench.arm64 /var/tmp/gem5-disk-smoke/payload.bin gem5-disk-smoke-payload-v3 20000000 256 >/tmp/disk_trace_ubench.stdout 2>&1 &'
```

Expected guest-side stdout before checkpoint includes `READY_FOR_CHECKPOINT ...`.

## 4. Stop QEMU and save internal `snapshot_2`

```bash
python3 - <<'PY2'
from telnetlib import Telnet

tn = Telnet('127.0.0.1', 45456)
tn.read_until(b'(qemu)')
for cmd in ('stop', 'savevm snapshot_2'):
    tn.write(cmd.encode() + b'\n')
    print(tn.read_until(b'(qemu)').decode(), end='')
tn.close()
PY2
```

## 5. Generate the gem5 checkpoint from the prepared QEMU state

```bash
cd /home/dev/qflex_git/QPoints
./gen_snapshot.sh /mnt/sdb/aansari/checkpoints/single-core snapshot_2 "" 0 1 45456
```

## 6. Convert the prepared qcow2 snapshot to raw

```bash
cd /mnt/sdb/aansari/experiments/single-core/run
./convert.sh single-core.qcow2 snapshot_2 \
  /mnt/sdb/aansari/checkpoints/single-core/snapshot_2/snapshot_2.img
```

## 7. Prepare FDIP sim-config

```bash
cat > /tmp/disk_smoke_fdip.args <<'EOF'
--fdip
EOF
```

## 8. Run the validating gem5 pass

```bash
cd /home/dev/qflex_git/QPoints
./run_gem5.sh \
  --gem5-ckp-dir /mnt/sdb/aansari/checkpoints/single-core \
  --experiment disk_trace_snapshot_2 \
  --snapshot snapshot_2 \
  --inst 250000000 \
  --cores 1 \
  --timing-ruby \
  --branch-trace \
  --sim-config /tmp/disk_smoke_fdip.args
```

## 9. Interpret the verdict

Run the packaged analyzer against the packaged trace:

```bash
python3 analyze_branch_trace.py branch_trace_core_0.log \
  --success-pc 0x40076c \
  --failure-pc 0x400798
```
