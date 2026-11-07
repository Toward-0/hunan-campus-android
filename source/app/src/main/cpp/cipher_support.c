/* Derived from vendor/hunan/src/cipher/CipherUtils.c; Android allocation helpers remain in memory_hex.c. */
#include "cipher/CipherUtils.h"
void zsm_blob_free(ios_zsm_blob_t* blob)
{
    if (!blob) return;
    s_free(blob->key);
    s_free(blob->iv);
    s_free(blob->js);
    memset(blob, 0, sizeof(*blob));
}

size_t s_strlen(const char* str)
{
    return str ? strlen(str) : 0;
}

uint8_t* pkcs7_padding(const uint8_t* data, const size_t data_len, const size_t block_size, size_t* out_len)
{
    if (!data || !out_len || block_size == 0) return NULL;
    size_t padding = block_size - data_len % block_size;
    if (padding == 0) padding = block_size;
    if (data_len > SIZE_MAX - padding) return NULL;
    const size_t padded_len = data_len + padding;
    uint8_t* padded = s_malloc(padded_len);
    if (!padded) return NULL;
    memcpy(padded, data, data_len);
    memset(padded + data_len, (uint8_t)padding, padding);
    *out_len = padded_len;
    return padded;
}

uint8_t* rm_pkcs7_padding(const uint8_t* data, const size_t data_len, size_t* out_len)
{
    if (!data || !out_len || data_len == 0) return NULL;
    const uint8_t padding = data[data_len - 1];
    if (padding == 0 || padding > data_len) return NULL;
    for (size_t i = data_len - padding; i < data_len; i++) if (data[i] != padding) return NULL;
    const size_t unpadded_len = data_len - padding;
    uint8_t* unpadded = s_malloc(unpadded_len ? unpadded_len : 1);
    if (!unpadded) return NULL;
    memcpy(unpadded, data, unpadded_len);
    *out_len = unpadded_len;
    return unpadded;
}

uint8_t* pad_2_multiple(const uint8_t* data, const size_t data_len, const size_t multiple, size_t* out_len)
{
    if (!data || !out_len || multiple == 0) return NULL;
    const size_t padding = (multiple - data_len % multiple) % multiple;
    if (data_len > SIZE_MAX - padding) return NULL;
    const size_t padded_len = data_len + padding;
    uint8_t* padded = s_calloc(padded_len ? padded_len : 1, 1);
    if (!padded) return NULL;
    memcpy(padded, data, data_len);
    *out_len = padded_len;
    return padded;
}

uint32_t bytes_2_uint32_be(const uint8_t* bytes)
{
    if (!bytes) return 0;
    return (uint32_t)bytes[0] << 24 |
           (uint32_t)bytes[1] << 16 |
           (uint32_t)bytes[2] << 8 |
           (uint32_t)bytes[3];
}

uint32_t bytes_2_uint32_le(const uint8_t* bytes)
{
    if (!bytes) return 0;
    return (uint32_t)bytes[3] << 24 |
           (uint32_t)bytes[2] << 16 |
           (uint32_t)bytes[1] << 8 |
           (uint32_t)bytes[0];
}

void uint32_2_bytes_be(const uint32_t value, uint8_t* bytes)
{
    if (!bytes) return;
    bytes[0] = (uint8_t)(value >> 24);
    bytes[1] = (uint8_t)(value >> 16);
    bytes[2] = (uint8_t)(value >> 8);
    bytes[3] = (uint8_t)value;
}

void uint32_2_bytes_le(const uint32_t value, uint8_t* bytes)
{
    if (!bytes) return;
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
    bytes[2] = (uint8_t)(value >> 16);
    bytes[3] = (uint8_t)(value >> 24);
}

void xor_bytes(const uint8_t* a, const uint8_t* b, uint8_t* result, const size_t len)
{
    if (!a || !b || !result) return;
    for (size_t i = 0; i < len; i++) result[i] = a[i] ^ b[i];
}
