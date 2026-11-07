/* Android-only allocation/hex helpers. Unlike the desktop helpers, never exit(). */
#include "cipher/CipherUtils.h"
#include <stdint.h>

#ifdef HUNAN_ISOLATION
extern int isolation_fail_allocation(void);
#define ALLOC_FAIL() isolation_fail_allocation()
#else
#define ALLOC_FAIL() 0
#endif
void* s_malloc(size_t n) { return n && !ALLOC_FAIL() ? malloc(n) : NULL; }
void* s_calloc(size_t n, size_t size) { return n && size && n <= SIZE_MAX / size && !ALLOC_FAIL() ? calloc(n, size) : NULL; }
void s_free(void* p) { free(p); }
char* bytes_2_hex(const uint8_t* bytes, size_t n) {
    if (!bytes || !n || n > (SIZE_MAX - 1) / 2) return NULL;
    char* out = malloc(n * 2 + 1);
    if (!out) return NULL;
    const char* digits = "0123456789ABCDEF";
    for (size_t i = 0; i < n; ++i) { out[i*2] = digits[bytes[i] >> 4]; out[i*2+1] = digits[bytes[i] & 15]; }
    out[n*2] = 0; return out;
}
static int nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
uint8_t* hex_2_bytes(const char* hex, size_t* length) {
    if (!hex || !length) return NULL;
    size_t n = strlen(hex);
    if (!n || (n & 1)) return NULL;
    uint8_t* out = malloc(n / 2);
    if (!out) return NULL;
    for (size_t i = 0; i < n/2; ++i) {
        int a = nibble(hex[i*2]), b = nibble(hex[i*2+1]);
        if (a < 0 || b < 0) { free(out); return NULL; }
        out[i] = (uint8_t)((a << 4) | b);
    }
    *length = n/2; return out;
}
