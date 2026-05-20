#!/bin/sh
set -eu

TEST_ROOT="${TEST_ROOT:-/var/tmp/gem5-disk-smoke}"
TEST_FILE="${TEST_ROOT}/payload.txt"
LOG_FILE="${LOG_FILE:-/tmp/disk_smoke.log}"
CONSOLE_LOG="${CONSOLE_LOG:-/dev/ttyAMA0}"
EXPECTED="${EXPECTED:-gem5-disk-smoke-payload-v1}"
CONTROL_TOKEN="${CONTROL_TOKEN:-GO}"

emit_log_line() {
  line="$1"
  printf '%s\n' "$line" | tee -a "$LOG_FILE"
  if [ -n "$CONSOLE_LOG" ] && [ -e "$CONSOLE_LOG" ]; then
    printf '%s\n' "$line" > "$CONSOLE_LOG" 2>/dev/null || true
  fi
}

log() {
  emit_log_line "$(date '+%s') $*"
}

finish() {
  code="$1"
  if [ -x /sbin/m5 ]; then
    /sbin/m5 exit
  fi
  exit "$code"
}

fail() {
  log "DISK_SMOKE_FAIL: $*"
  finish 1
}

check_backing_fs() {
  probe_path="$1"
  fs_type="$(df -T "$probe_path" 2>/dev/null | awk 'NR==2 {print $2}')"
  [ -n "$fs_type" ] || fail "unable to determine filesystem type for ${probe_path}"
  case "$fs_type" in
    tmpfs|ramfs)
      fail "refusing to run on memory-backed filesystem type=${fs_type} path=${probe_path}"
      ;;
  esac
  log "BACKING_FS type=${fs_type} path=${probe_path}"
}

wait_for_go() {
  [ -e "$CONSOLE_LOG" ] || fail "control console missing path=${CONSOLE_LOG}"
  exec 9<>"$CONSOLE_LOG" || fail "unable to open control console path=${CONSOLE_LOG}"
  log "READY_FOR_CHECKPOINT waiting_for=${CONTROL_TOKEN} test_file=${TEST_FILE}"
  while IFS= read -r token <&9; do
    [ "$token" = "$CONTROL_TOKEN" ] && break
    log "IGNORING_CONTROL_TOKEN value=${token}"
  done
  log "CONTROL_TOKEN_RECEIVED value=${CONTROL_TOKEN}"
}

mkdir -p "$TEST_ROOT"
: > "$LOG_FILE"
check_backing_fs "$TEST_ROOT"
wait_for_go

printf '%s\n' "$EXPECTED" > "$TEST_FILE" || fail "write failed"
sync || fail "sync failed"

if [ -w /proc/sys/vm/drop_caches ]; then
  sync || fail "pre-drop sync failed"
  echo 3 > /proc/sys/vm/drop_caches || fail "drop_caches failed"
fi

ACTUAL="$(cat "$TEST_FILE" 2>/dev/null || true)"
[ "$ACTUAL" = "$EXPECTED" ] || fail "readback mismatch expected=${EXPECTED} actual=${ACTUAL}"
ls -l "$TEST_FILE" | tee -a "$LOG_FILE"
log "DISK_SMOKE_PASS"
finish 0
