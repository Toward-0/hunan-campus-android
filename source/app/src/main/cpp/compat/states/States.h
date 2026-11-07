#ifndef ANDROID_CIPHER_STATE_H
#define ANDROID_CIPHER_STATE_H
#include "cipher/CipherInterface.h"
/* Scratch state used only while importing a module under mobile_mutex. */
typedef struct { struct { int8_t type; ios_zsm_blob_t blob; cipher_interface_t* cipher; } auth_cfg; } prog_status_t;
extern prog_status_t* g_prog_status;
extern _Thread_local unsigned char tl_thread_idx;
#endif
