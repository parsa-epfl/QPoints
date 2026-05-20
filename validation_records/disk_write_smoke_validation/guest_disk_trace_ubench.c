#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/types.h>
#include <unistd.h>

#ifndef TMPFS_MAGIC
#define TMPFS_MAGIC 0x01021994
#endif
#ifndef RAMFS_MAGIC
#define RAMFS_MAGIC 0x858458f6
#endif

#define DEFAULT_PATH "/var/tmp/gem5-disk-smoke/payload.bin"
#define DEFAULT_PAYLOAD "gem5-disk-smoke-payload-v3"
#define DEFAULT_SPIN_ITERS 20000000UL
#define DEFAULT_REPEAT_COUNT 256UL
#define MAX_EXPECTED_BYTES (1UL << 20)

static volatile uint64_t spin_sink = 0;

__attribute__((noinline)) static void spin_window(unsigned long iters) {
    for (unsigned long i = 0; i < iters; ++i) {
        spin_sink += (i ^ 0x9e3779b97f4a7c15ULL);
    }
}

__attribute__((noinline, noreturn)) void disk_smoke_success_loop(void) {
    volatile uint64_t marker = 0xfeedfaceULL;
    while (1) {
        marker ^= 0x1234ULL;
        __asm__ volatile("" : "+r"(marker) :: "memory");
    }
}

__attribute__((noinline, noreturn)) void disk_smoke_failure_loop(void) {
    volatile uint64_t marker = 0xdeadbeefULL;
    while (1) {
        marker ^= 0x4321ULL;
        __asm__ volatile("" : "+r"(marker) :: "memory");
    }
}

static void fail_perror(const char *msg) {
    perror(msg);
    disk_smoke_failure_loop();
}

static void fail_msg(const char *msg) {
    fprintf(stderr, "%s\n", msg);
    disk_smoke_failure_loop();
}

static void parent_dir_of(const char *path, char *out, size_t out_sz) {
    if (out_sz == 0) {
        fail_msg("parent dir buffer is empty");
    }
    size_t len = strlen(path);
    if (len >= out_sz) {
        fail_msg("path too long");
    }
    memcpy(out, path, len + 1);
    char *slash = strrchr(out, '/');
    if (slash == NULL) {
        strcpy(out, ".");
        return;
    }
    if (slash == out) {
        slash[1] = '\0';
        return;
    }
    *slash = '\0';
}

static void mkdir_p(const char *path, mode_t mode) {
    char buf[PATH_MAX];
    size_t len = strlen(path);
    if (len >= sizeof(buf)) {
        fail_msg("mkdir path too long");
    }
    memcpy(buf, path, len + 1);
    for (char *p = buf + 1; *p; ++p) {
        if (*p == '/') {
            *p = '\0';
            if (mkdir(buf, mode) != 0 && errno != EEXIST) {
                fail_perror("mkdir");
            }
            *p = '/';
        }
    }
    if (mkdir(buf, mode) != 0 && errno != EEXIST) {
        fail_perror("mkdir");
    }
}

static void ensure_disk_backed_dir(const char *path) {
    struct statfs fs;
    if (statfs(path, &fs) != 0) {
        fail_perror("statfs");
    }
    if ((unsigned long)fs.f_type == TMPFS_MAGIC ||
        (unsigned long)fs.f_type == RAMFS_MAGIC) {
        fail_msg("memory-backed fs is not allowed for disk smoke test");
    }
}

static void fsync_dir(const char *path) {
    int dirfd = open(path, O_RDONLY | O_DIRECTORY);
    if (dirfd < 0) {
        fail_perror("open-dir");
    }
    if (fsync(dirfd) != 0) {
        close(dirfd);
        fail_perror("fsync-dir");
    }
    if (close(dirfd) != 0) {
        fail_perror("close-dir");
    }
}

static int write_all(int fd, const void *buf, size_t len) {
    const char *ptr = (const char *)buf;
    while (len > 0) {
        ssize_t rc = write(fd, ptr, len);
        if (rc < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        ptr += (size_t)rc;
        len -= (size_t)rc;
    }
    return 0;
}

static ssize_t read_all_exact(int fd, void *buf, size_t len) {
    char *ptr = (char *)buf;
    size_t done = 0;
    while (done < len) {
        ssize_t rc = read(fd, ptr + done, len - done);
        if (rc < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        if (rc == 0) {
            break;
        }
        done += (size_t)rc;
    }
    return (ssize_t)done;
}

static void evict_fd_cache(int fd) {
#ifdef POSIX_FADV_DONTNEED
    (void)posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
#endif
}

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : DEFAULT_PATH;
    const char *payload = argc > 2 ? argv[2] : DEFAULT_PAYLOAD;
    unsigned long spin_iters = argc > 3 ? strtoul(argv[3], NULL, 0) : DEFAULT_SPIN_ITERS;
    unsigned long repeat_count = argc > 4 ? strtoul(argv[4], NULL, 0) : DEFAULT_REPEAT_COUNT;

    if (repeat_count == 0) {
        fail_msg("repeat_count must be > 0");
    }

    char parent_dir[PATH_MAX];
    parent_dir_of(path, parent_dir, sizeof(parent_dir));
    mkdir_p(parent_dir, 0755);
    ensure_disk_backed_dir(parent_dir);

    size_t payload_len = strlen(payload);
    if (payload_len == 0) {
        fail_msg("payload must be non-empty");
    }
    size_t expected_len = payload_len * repeat_count;
    if (expected_len == 0 || expected_len > MAX_EXPECTED_BYTES) {
        fail_msg("expected payload length is out of range");
    }

    char *expected = malloc(expected_len);
    char *actual = malloc(expected_len);
    if (expected == NULL || actual == NULL) {
        fail_msg("malloc failed");
    }
    for (unsigned long i = 0; i < repeat_count; ++i) {
        memcpy(expected + i * payload_len, payload, payload_len);
    }

    fprintf(stderr,
            "READY_FOR_CHECKPOINT spin_iters=%lu repeat_count=%lu path=%s bytes=%zu\n",
            spin_iters, repeat_count, path, expected_len);
    fflush(stderr);
    spin_window(spin_iters);

    int fd = open(path, O_CREAT | O_TRUNC | O_WRONLY, 0644);
    if (fd < 0) {
        fail_perror("open-write");
    }
    if (write_all(fd, expected, expected_len) != 0) {
        close(fd);
        fail_perror("write");
    }
    if (fsync(fd) != 0) {
        close(fd);
        fail_perror("fsync");
    }
    evict_fd_cache(fd);
    if (close(fd) != 0) {
        fail_perror("close-write");
    }
    fsync_dir(parent_dir);
    sync();

    memset(actual, 0, expected_len);
    fd = open(path, O_RDONLY);
    if (fd < 0) {
        fail_perror("open-read");
    }
    evict_fd_cache(fd);
    ssize_t got = read_all_exact(fd, actual, expected_len);
    if (got < 0) {
        close(fd);
        fail_perror("read");
    }
    if (close(fd) != 0) {
        fail_perror("close-read");
    }

    if ((size_t)got != expected_len || memcmp(actual, expected, expected_len) != 0) {
        fprintf(stderr, "payload mismatch got=%zd expected=%zu\n", got, expected_len);
        disk_smoke_failure_loop();
    }

    free(actual);
    free(expected);
    disk_smoke_success_loop();
}
