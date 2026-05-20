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

#define DEFAULT_PATH "/var/tmp/gem5-append-log/commit.log"
#define DEFAULT_TAG "cass-logish"
#define DEFAULT_SPIN_ITERS 20000000UL
#define DEFAULT_RECORD_COUNT 128UL
#define DEFAULT_FSYNC_EVERY 8UL
#define MAX_RECORD_LINE 256
#define MAX_EXPECTED_BYTES (2UL << 20)

static volatile uint64_t spin_sink = 0;

__attribute__((noinline)) static void spin_window(unsigned long iters) {
    for (unsigned long i = 0; i < iters; ++i) {
        spin_sink += (i ^ 0x9e3779b97f4a7c15ULL);
    }
}

__attribute__((noinline, noreturn)) void append_log_success_loop(void) {
    volatile uint64_t marker = 0xa11eed55ULL;
    while (1) {
        marker ^= 0x5151ULL;
        __asm__ volatile("" : "+r"(marker) :: "memory");
    }
}

__attribute__((noinline, noreturn)) void append_log_failure_loop(void) {
    volatile uint64_t marker = 0xbad10badULL;
    while (1) {
        marker ^= 0x9191ULL;
        __asm__ volatile("" : "+r"(marker) :: "memory");
    }
}

static void fail_perror(const char *msg) {
    perror(msg);
    append_log_failure_loop();
}

static void fail_msg(const char *msg) {
    fprintf(stderr, "%s\n", msg);
    append_log_failure_loop();
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
        fail_msg("memory-backed fs is not allowed for append-log test");
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

static unsigned long record_checksum(unsigned long idx, const char *tag) {
    unsigned long sum = 0x9e3779b9UL ^ idx;
    for (const unsigned char *p = (const unsigned char *)tag; *p; ++p) {
        sum = (sum << 5) - sum + *p;
    }
    return sum;
}

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : DEFAULT_PATH;
    const char *tag = argc > 2 ? argv[2] : DEFAULT_TAG;
    unsigned long spin_iters = argc > 3 ? strtoul(argv[3], NULL, 0) : DEFAULT_SPIN_ITERS;
    unsigned long record_count = argc > 4 ? strtoul(argv[4], NULL, 0) : DEFAULT_RECORD_COUNT;
    unsigned long fsync_every = argc > 5 ? strtoul(argv[5], NULL, 0) : DEFAULT_FSYNC_EVERY;

    if (record_count == 0) {
        fail_msg("record_count must be > 0");
    }
    if (fsync_every == 0) {
        fail_msg("fsync_every must be > 0");
    }

    char parent_dir[PATH_MAX];
    parent_dir_of(path, parent_dir, sizeof(parent_dir));
    mkdir_p(parent_dir, 0755);
    ensure_disk_backed_dir(parent_dir);

    size_t tag_len = strlen(tag);
    if (tag_len == 0) {
        fail_msg("tag must be non-empty");
    }

    size_t max_expected = record_count * MAX_RECORD_LINE;
    if (max_expected == 0 || max_expected > MAX_EXPECTED_BYTES) {
        fail_msg("expected append-log size is out of range");
    }
    char *expected = malloc(max_expected);
    char *actual = malloc(max_expected);
    if (expected == NULL || actual == NULL) {
        fail_msg("malloc failed");
    }

    size_t expected_len = 0;
    for (unsigned long i = 0; i < record_count; ++i) {
        int n = snprintf(expected + expected_len, max_expected - expected_len,
                         "SEQ=%06lu TAG=%s CHECK=%08lx\n",
                         i, tag, record_checksum(i, tag));
        if (n < 0 || (size_t)n >= max_expected - expected_len) {
            fail_msg("record formatting overflow");
        }
        expected_len += (size_t)n;
    }

    fprintf(stderr,
            "READY_FOR_CHECKPOINT spin_iters=%lu record_count=%lu fsync_every=%lu path=%s bytes=%zu\n",
            spin_iters, record_count, fsync_every, path, expected_len);
    fflush(stderr);
    spin_window(spin_iters);

    int fd = open(path, O_CREAT | O_TRUNC | O_WRONLY, 0644);
    if (fd < 0) {
        fail_perror("open-create");
    }
    if (close(fd) != 0) {
        fail_perror("close-create");
    }

    fd = open(path, O_WRONLY | O_APPEND);
    if (fd < 0) {
        fail_perror("open-append");
    }

    size_t offset = 0;
    for (unsigned long i = 0; i < record_count; ++i) {
        size_t line_len = strcspn(expected + offset, "\n") + 1;
        if (write_all(fd, expected + offset, line_len) != 0) {
            close(fd);
            fail_perror("write-append");
        }
        offset += line_len;
        if (((i + 1) % fsync_every) == 0 || (i + 1) == record_count) {
            if (fsync(fd) != 0) {
                close(fd);
                fail_perror("fsync-append");
            }
        }
        if ((i + 1) == (record_count / 2)) {
            if (close(fd) != 0) {
                fail_perror("close-midway");
            }
            fd = open(path, O_WRONLY | O_APPEND);
            if (fd < 0) {
                fail_perror("reopen-append");
            }
        }
    }

    evict_fd_cache(fd);
    if (close(fd) != 0) {
        fail_perror("close-append");
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
        fprintf(stderr, "append-log mismatch got=%zd expected=%zu\n", got, expected_len);
        append_log_failure_loop();
    }

    free(actual);
    free(expected);
    append_log_success_loop();
}
