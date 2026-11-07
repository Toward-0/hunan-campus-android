#include <jni.h>
#include <pthread.h>
#include "states/States.h"
#include "utils/Logger.h"
#include "cipher/CipherUtils.h"

static prog_status_t scratch;
prog_status_t* g_prog_status = &scratch;
_Thread_local unsigned char tl_thread_idx = 0;
/* Module key material is never logged or persisted. */
void log_out(LogLevel level, const char* file, uint32_t line, const char* fmt, ...) {
    (void)level; (void)file; (void)line; (void)fmt;
}
static pthread_mutex_t mobile_mutex = PTHREAD_MUTEX_INITIALIZER;
static struct { jlong id; cipher_interface_t* cipher; char algo[ALGO_ID_LEN]; } slots[8];
static jlong next_id = 1;
static int find_slot(jlong id) {
    for (int i=0; i<8; i++) if (id > 0 && slots[i].id == id) return i;
    return -1;
}
JNIEXPORT jlong JNICALL Java_org_esurfing_hunan_NativeCore_createMobile(JNIEnv* env, jobject self, jbyteArray input) {
    (void)self;
    if (!input) return 0;
    jsize n = (*env)->GetArrayLength(env,input);
    if (n < 15 || n > 65536) return 0;
    uint8_t* data = malloc((size_t)n);
    if (!data) return 0;
    (*env)->GetByteArrayRegion(env,input,0,n,(jbyte*)data);
    if ((*env)->ExceptionCheck(env)) { free(data); return 0; }
    size_t off=3;
    if (memcmp(data,"001",3)!=0 || off >= (size_t)n) { free(data); return 0; }
    off += 1 + data[off];
    if (off >= (size_t)n) { free(data); return 0; }
    off += 1 + data[off];
    if (off+9 > (size_t)n) { free(data); return 0; }
    uint32_t packed=bytes_2_uint32_le(data+off+5);
    if ((packed>>28)!=2 || !(packed&0x0FFFFFFF) || (packed&0x0FFFFFFF)>1048576) { free(data); return 0; }
    pthread_mutex_lock(&mobile_mutex);
    jlong result=0;
    for(int i=0;i<8;i++) if (!slots[i].id && next_id > 0) {
        memset(&scratch,0,sizeof(scratch));
        if (init_ios_cipher_from_zsm(data,(size_t)n,slots[i].algo)) {
            slots[i].cipher=scratch.auth_cfg.cipher;
            slots[i].id=next_id;
            next_id = next_id == INT64_MAX ? 0 : next_id + 1;
            result=slots[i].id;
        }
        /* The upstream loader already freed its temporary blob. */
        memset(&scratch,0,sizeof(scratch));
        break;
    }
    pthread_mutex_unlock(&mobile_mutex);
    free(data);
    return result;
}
JNIEXPORT jstring JNICALL Java_org_esurfing_hunan_NativeCore_mobileId(JNIEnv* env,jobject self,jlong id) {
    (void)self; pthread_mutex_lock(&mobile_mutex);
    int i=find_slot(id);jstring result=i<0?NULL:(*env)->NewStringUTF(env,slots[i].algo);
    pthread_mutex_unlock(&mobile_mutex);return result;
}
JNIEXPORT jbyteArray JNICALL Java_org_esurfing_hunan_NativeCore_cryptMobile(JNIEnv* env,jobject self,jlong id,jbyteArray input,jboolean decrypt) {
    (void)self;
    if(!input) return NULL;
    jsize n=(*env)->GetArrayLength(env,input);
    if(n<1 || n>131072) return NULL;
    char* data=calloc((size_t)n+1,1);if(!data)return NULL;
    (*env)->GetByteArrayRegion(env,input,0,n,(jbyte*)data);
    if ((*env)->ExceptionCheck(env)) { free(data); return NULL; }
    if(memchr(data,0,(size_t)n)){free(data);return NULL;}
    pthread_mutex_lock(&mobile_mutex);
    int i=find_slot(id);
    char* out=i<0?NULL:(decrypt?slots[i].cipher->decrypt(slots[i].cipher,data):slots[i].cipher->encrypt(slots[i].cipher,data));
    jbyteArray result=NULL;
    if(out){size_t len=strlen(out);if(len<=262144){result=(*env)->NewByteArray(env,(jsize)len);if(result)(*env)->SetByteArrayRegion(env,result,0,(jsize)len,(const jbyte*)out);}free(out);}
    pthread_mutex_unlock(&mobile_mutex);free(data);return result;
}
JNIEXPORT void JNICALL Java_org_esurfing_hunan_NativeCore_releaseMobile(JNIEnv* env,jobject self,jlong id) {
    (void)env;(void)self;pthread_mutex_lock(&mobile_mutex);
    int i=find_slot(id);if(i>=0){slots[i].cipher->destroy(slots[i].cipher);memset(&slots[i],0,sizeof(slots[i]));}
    pthread_mutex_unlock(&mobile_mutex);
}
JNIEXPORT jint JNICALL Java_org_esurfing_hunan_NativeCore_liveMobileHandles(JNIEnv* env,jobject self) {
    (void)env;(void)self;pthread_mutex_lock(&mobile_mutex);
    jint count=0;for(int i=0;i<8;i++) if(slots[i].id) count++;
    pthread_mutex_unlock(&mobile_mutex);return count;
}
