// macOS compatibility shim for Linux's <sys/prctl.h>.
//
// This project only ever calls prctl(PR_SET_NAME, "<name>", 0, 0, 0) to give a
// thread a readable name. Linux stores that in the kernel task struct, which on
// macOS is done through pthread_setname_np() for the *current* thread.
// Anything other than PR_SET_NAME is a no-op that returns -1, matching the
// kernel's "unknown option" behaviour.
#ifndef _DSH_MACOS_COMPAT_SYS_PRCTL_H
#define _DSH_MACOS_COMPAT_SYS_PRCTL_H

#if defined(__linux__)
#error "macos_compat/sys/prctl.h must not shadow the real <sys/prctl.h> on Linux"
#endif

#include <stdarg.h>
#include <pthread.h>

#ifndef PR_SET_NAME
#define PR_SET_NAME 15
#endif

static inline int prctl(int option, ...) {
    if (option != PR_SET_NAME) {
        return -1;
    }
    va_list ap;
    va_start(ap, option);
    const char *name = va_arg(ap, const char *);
    va_end(ap);
    if (name == 0) {
        return -1;
    }
#if defined(__APPLE__)
    // pthread_setname_np() acts on the calling thread and truncates to 63 bytes.
    return pthread_setname_np(name);
#else
    (void)name;
    return 0;
#endif
}

#endif // _DSH_MACOS_COMPAT_SYS_PRCTL_H
