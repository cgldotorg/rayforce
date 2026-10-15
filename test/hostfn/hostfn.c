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

/* The host-function fixture the ipc/hostfn tests load with .sys.loadfn
 * (built by the Makefile as build/libhostfn.so).  Its ray_* references are
 * left for the loading executable to resolve. */

#include <rayforce.h>

/* (hf_scale k v): the F64 vector v multiplied by the F64 atom k. */
ray_t* hf_scale(ray_t** args, int64_t n) {
    if (n != 2)
        return ray_error("arity", "hf_scale expects 2 arguments, got %lld", (long long)n);
    ray_t* k = args[0];
    ray_t* v = args[1];
    if (k->type != -RAY_F64 || v->type != RAY_F64)
        return ray_error("type", "hf_scale expects an f64 atom and an f64 vector");

    ray_t* out = ray_vec_new(RAY_F64, v->len);
    if (RAY_IS_ERR(out)) return out;
    const double* src = (const double*)ray_data(v);
    double* dst = (double*)ray_data(out);
    for (int64_t i = 0; i < v->len; i++) dst[i] = k->f64 * src[i];
    out->len = v->len;
    return out;
}
