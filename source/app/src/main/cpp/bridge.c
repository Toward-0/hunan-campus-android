#include <jni.h>
#include "cipher/CipherInterface.h"
#include "cipher/KeyData.h"
#include "hunan/HunanXml.h"

/* Server responses are UTF-8, not JNI modified UTF-8; use String(byte[], UTF-8). */
static jstring from_utf8(JNIEnv* env, const char* text) {
    if (!text) return NULL;
    size_t n = strlen(text);
    if (n > INT32_MAX) return NULL;
    jbyteArray bytes = (*env)->NewByteArray(env, (jsize)n);
    if (!bytes) return NULL;
    (*env)->SetByteArrayRegion(env, bytes, 0, (jsize)n, (const jbyte*)text);
    jclass cls = (*env)->FindClass(env, "java/lang/String");
    jmethodID ctor = cls ? (*env)->GetMethodID(env, cls, "<init>", "([BLjava/lang/String;)V") : NULL;
    jstring charset = (*env)->NewStringUTF(env, "UTF-8");
    jstring result = ctor && charset ? (*env)->NewObject(env, cls, ctor, bytes, charset) : NULL;
    (*env)->DeleteLocalRef(env, bytes);
    if (cls) (*env)->DeleteLocalRef(env, cls);
    if (charset) (*env)->DeleteLocalRef(env, charset);
    return result;
}

/* One cipher per call: no desktop globals, signals, worker threads or exit(). */
JNIEXPORT jstring JNICALL Java_org_esurfing_hunan_NativeCore_crypt(JNIEnv* env, jobject self, jstring input, jboolean decrypt) {
    (void)self;
    if (!input || (*env)->GetStringUTFLength(env, input) > 131072) return NULL;
    const char* text = (*env)->GetStringUTFChars(env, input, NULL);
    if (!text) return NULL;
    cipher_interface_t* cipher = create_aes_double_cbc_hunan_cipher(
        key_FAB1DCDE_2D24_41CD_8510_2416DC7854CF, iv_FAB1DCDE_2D24_41CD_8510_2416DC7854CF);
    char* result = cipher ? (decrypt ? cipher->decrypt(cipher, text) : cipher->encrypt(cipher, text)) : NULL;
    jstring out = from_utf8(env, result);
    free(result);
    if (cipher) cipher->destroy(cipher);
    (*env)->ReleaseStringUTFChars(env, input, text);
    return out;
}

JNIEXPORT jstring JNICALL Java_org_esurfing_hunan_NativeCore_xml(JNIEnv* env, jobject self, jint ep, jobjectArray input) {
    (void)self;
    if (!input || ep < 0 || ep >= HUNAN_EP_COUNT) return NULL;
    size_t count = 0;
    hunan_endpoint_fields((hunan_endpoint_t)ep, &count);
    if ((*env)->GetArrayLength(env, input) != (jsize)count) return NULL;
    const char** values = calloc(count, sizeof(char*));
    jstring* refs = calloc(count, sizeof(jstring));
    if (!values || !refs) { free(values); free(refs); return NULL; }
    int ok = 1;
    for (size_t i = 0; i < count; ++i) {
        refs[i] = (*env)->GetObjectArrayElement(env, input, (jsize)i);
        if (!refs[i] || (*env)->GetStringUTFLength(env, refs[i]) > 4096) { ok = 0; break; }
        values[i] = (*env)->GetStringUTFChars(env, refs[i], NULL);
        if (!values[i]) { ok = 0; break; }
    }
    char* text = ok ? hunan_build_xml_for((hunan_endpoint_t)ep, values) : NULL;
    jstring result = from_utf8(env, text);
    free(text);
    for (size_t i = 0; i < count; ++i) {
        if (values[i]) (*env)->ReleaseStringUTFChars(env, refs[i], values[i]);
        if (refs[i]) (*env)->DeleteLocalRef(env, refs[i]);
    }
    free(values); free(refs);
    return result;
}
