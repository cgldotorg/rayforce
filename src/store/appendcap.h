#ifndef RAY_APPENDCAP_H
#define RAY_APPENDCAP_H
#include <rayforce.h>
/* Trusted executable launch only; deliberately not a Rayfall configuration API. */
ray_err_t ray_append_cap_configure(const char* root, const char* date);
void ray_append_cap_reset(void);
ray_t* ray_append_today_fn(ray_t** args, int64_t n);
#endif
