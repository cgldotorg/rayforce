/*
 *   Copyright (c) 2025-2026 Anton Kundenko <singaraiona@gmail.com>
 *   All rights reserved.
 *
 *   Permission is hereby granted, free of charge, to any person obtaining a copy
 *   of this software and associated documentation files (the "Software"), to deal
 *   in the Software without restriction, including without limitation the rights
 *   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 *   copies of the Software, and to permit persons to whom the Software is
 *   furnished to do so, subject to the following conditions:
 *
 *   The above copyright notice and this permission notice shall be included in all
 *   copies or substantial portions of the Software.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 *   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 *   SOFTWARE.
 */

/* The library a restricted peer names in the ipc/hostfn tests' refused
 * .sys.loadfn calls (built by the Makefile as build/libhostfn_mark.so).
 * Opening it runs mark_loaded, which creates /tmp/rf_hostfn_mark_<pid> for
 * the process that opened it, so a test can tell whether a given process
 * opened it. */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <unistd.h>
#include <rayforce.h>

__attribute__((constructor)) static void mark_loaded(void) {
    char path[64];
    snprintf(path, sizeof(path), "/tmp/rf_hostfn_mark_%d", (int)getpid());
    FILE* f = fopen(path, "w");
    if (f) fclose(f);
}

/* (hf_mark x): x. */
ray_t* hf_mark(ray_t** args, int64_t n) {
    ray_retain(args[0]);
    return args[0];
}
