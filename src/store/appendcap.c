/* Narrow launch-bound append capability. No evaluator privilege switching. */
#define _XOPEN_SOURCE 700
#include "store/appendcap.h"
#include "store/part.h"
#include "core/platform.h"
#include "lang/internal.h"
#include "lang/env.h"
#include "lang/cal.h"
#include "table/sym.h"
#include <sys/stat.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* IPC evaluation and launch share the owning VM thread. */
static RAY_TLS struct {
    bool enabled;
    int32_t date;
    char root[1024], partition[1100], table[1150], sym[1100];
} cap;

void ray_append_cap_reset(void) { memset(&cap, 0, sizeof cap); }

static bool cap_node(const char* path, bool directory, bool optional) {
    struct stat st;
#ifdef RAY_OS_WINDOWS
    if (stat(path, &st)) return optional && errno == ENOENT;
#else
    if (lstat(path, &st)) return optional && errno == ENOENT;
#endif
    return directory ? S_ISDIR(st.st_mode) : S_ISREG(st.st_mode);
}

static bool cap_paths(void) {
    if (!cap_node(cap.root, true, false) || !cap_node(cap.partition, true, false) ||
        !cap_node(cap.table, true, false) || !cap_node(cap.sym, false, false)) return false;
    char path[1250];
    snprintf(path, sizeof path, "%s/.generations", cap.table);
    if (!cap_node(path, true, true)) return false;
    snprintf(path, sizeof path, "%s.tmp", cap.sym);
    if (!cap_node(path, false, true)) return false;
    snprintf(path, sizeof path, "%s.lk", cap.sym);
    if (!cap_node(path, false, true)) return false;
    snprintf(path, sizeof path, "%s/.write.lock", cap.table);
    return cap_node(path, false, true);
}

static ray_err_t cap_mount(void) {
    ray_t* mounted = ray_read_parted(cap.root, "quotes_1m");
    if (!mounted || RAY_IS_ERR(mounted)) {
        if (mounted) ray_error_free(mounted);
        return RAY_ERR_IO;
    }
    int64_t name = ray_sym_intern("quotes_1m", 9);
    ray_err_t err = name < 0 ? RAY_ERR_OOM : ray_env_set(name, mounted);
    ray_release(mounted);
    return err;
}

ray_err_t ray_append_cap_configure(const char* root, const char* date) {
#ifndef RAY_OS_LINUX
    (void)root; (void)date; return RAY_ERR_NYI;
#else
    if (cap.enabled || !root || root[0] != '/' || !date || strlen(date) != 10)
        return RAY_ERR_DOMAIN;
    for (int i = 0; i < 10; i++)
        if ((i == 4 || i == 7) ? date[i] != '.' : (date[i] < '0' || date[i] > '9'))
            return RAY_ERR_DOMAIN;
    int y, m, d;
    if (sscanf(date, "%4d.%2d.%2d", &y, &m, &d) != 3 || y < 1 ||
        m < 1 || m > 12 || d < 1 || d > 31) return RAY_ERR_DOMAIN;
    int32_t days = ymd_to_date(y, m, d);
    int yy, mm, dd; date_to_ymd(days, &yy, &mm, &dd);
    if (y != yy || m != mm || d != dd) return RAY_ERR_DOMAIN;
    char* resolved = realpath(root, NULL);
    if (!resolved) return RAY_ERR_IO;
    if (strlen(resolved) >= sizeof cap.root) { free(resolved); return RAY_ERR_RANGE; }
    snprintf(cap.root, sizeof cap.root, "%s", resolved); free(resolved);
    snprintf(cap.partition, sizeof cap.partition, "%s/%s", cap.root, date);
    snprintf(cap.table, sizeof cap.table, "%s/quotes_1m", cap.partition);
    snprintf(cap.sym, sizeof cap.sym, "%s/.sym", cap.root);
    cap.date = days;
    if (!cap_paths()) { ray_append_cap_reset(); return RAY_ERR_DOMAIN; }
    ray_err_t err = cap_mount();
    if (err != RAY_OK) { ray_append_cap_reset(); return err; }
    cap.enabled = true;
    return RAY_OK;
#endif
}

ray_t* ray_append_today_fn(ray_t** args, int64_t n) {
    if (!cap.enabled || n != 2 || !args[0] || args[0]->type != RAY_TABLE ||
        !args[1] || args[1]->type != -RAY_DATE || args[1]->i32 != cap.date || !cap_paths())
        return ray_error("access", "append capability does not authorize this request");
    ray_t* path = ray_str(cap.table, strlen(cap.table));
    ray_t* sym = ray_str(cap.sym, strlen(cap.sym));
    if (!path || !sym || RAY_IS_ERR(path) || RAY_IS_ERR(sym)) {
        if (path) ray_release(path);
        if (sym) ray_release(sym);
        return ray_error("oom", NULL);
    }
    ray_t* argv[] = {path, args[0], sym};
    ray_t* result = ray_splayed_append_fn(argv, 3);
    ray_release(path); ray_release(sym);
    if (!result || RAY_IS_ERR(result)) return result;
    /* Only future name resolution changes. No user source is evaluated. */
    if (cap_mount() != RAY_OK) {
        ray_release(result);
        return ray_error("commit", "append published but refreshing the mount failed");
    }
    return result;
}
