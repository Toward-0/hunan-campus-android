/* Compiled only into .isolation. Never present in the phone main APK. */
#include <jni.h>
#include <stdatomic.h>
static atomic_int fail_at = -1;
int isolation_fail_allocation(void) {
    int n = atomic_load(&fail_at);
    if (n < 0) return 0;
    return atomic_fetch_sub(&fail_at, 1) == 0;
}
JNIEXPORT void JNICALL Java_org_esurfing_hunan_CompatProbe_failAllocation(JNIEnv* e, jobject s, jint n) { (void)e; (void)s; atomic_store(&fail_at,n); }
JNIEXPORT jint JNICALL Java_org_esurfing_hunan_CompatProbe_nativeBits(JNIEnv* e, jobject s) { (void)e; (void)s; return sizeof(void*)*8; }
JNIEXPORT jstring JNICALL Java_org_esurfing_hunan_CompatProbe_nativeAbi(JNIEnv* e, jobject s) {
    (void)s;
#if defined(__aarch64__)
    return (*e)->NewStringUTF(e,"arm64-v8a");
#elif defined(__arm__)
    return (*e)->NewStringUTF(e,"armeabi-v7a");
#elif defined(__x86_64__)
    return (*e)->NewStringUTF(e,"x86_64");
#else
#error Unsupported isolation ABI
#endif
}
