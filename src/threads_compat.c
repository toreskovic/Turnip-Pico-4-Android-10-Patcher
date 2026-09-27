/* Export the Android NDK's pre-API-30 C11 threading implementations.
 * Compile with an Android API 29 (or earlier) target. */
#define call_once ndk_call_once
#define mtx_init ndk_mtx_init
#define mtx_destroy ndk_mtx_destroy
#define mtx_lock ndk_mtx_lock
#define mtx_unlock ndk_mtx_unlock
#define cnd_init ndk_cnd_init
#define cnd_destroy ndk_cnd_destroy
#define cnd_wait ndk_cnd_wait
#define cnd_signal ndk_cnd_signal
#define cnd_broadcast ndk_cnd_broadcast
#define thrd_create ndk_thrd_create
#define thrd_join ndk_thrd_join
#define thrd_yield ndk_thrd_yield
#define thrd_current ndk_thrd_current
#include <threads.h>
#undef call_once
#undef mtx_init
#undef mtx_destroy
#undef mtx_lock
#undef mtx_unlock
#undef cnd_init
#undef cnd_destroy
#undef cnd_wait
#undef cnd_signal
#undef cnd_broadcast
#undef thrd_create
#undef thrd_join
#undef thrd_yield
#undef thrd_current

void call_once(once_flag *flag, void (*fn)(void)) { ndk_call_once(flag, fn); }
int mtx_init(mtx_t *m, int type) { return ndk_mtx_init(m, type); }
void mtx_destroy(mtx_t *m) { ndk_mtx_destroy(m); }
int mtx_lock(mtx_t *m) { return ndk_mtx_lock(m); }
int mtx_unlock(mtx_t *m) { return ndk_mtx_unlock(m); }
int cnd_init(cnd_t *c) { return ndk_cnd_init(c); }
void cnd_destroy(cnd_t *c) { ndk_cnd_destroy(c); }
int cnd_wait(cnd_t *c, mtx_t *m) { return ndk_cnd_wait(c, m); }
int cnd_signal(cnd_t *c) { return ndk_cnd_signal(c); }
int cnd_broadcast(cnd_t *c) { return ndk_cnd_broadcast(c); }
int thrd_create(thrd_t *t, thrd_start_t fn, void *arg) { return ndk_thrd_create(t, fn, arg); }
int thrd_join(thrd_t t, int *result) { return ndk_thrd_join(t, result); }
void thrd_yield(void) { ndk_thrd_yield(); }
thrd_t thrd_current(void) { return ndk_thrd_current(); }
