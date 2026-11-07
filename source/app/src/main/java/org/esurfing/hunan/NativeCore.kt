package org.esurfing.hunan

object NativeCore {
    init { System.loadLibrary("hunan_core") }
    external fun crypt(input: String, decrypt: Boolean): String?
    external fun xml(endpoint: Int, values: Array<String>): String?
    external fun createMobile(module: ByteArray): Long
    external fun mobileId(handle: Long): String?
    external fun cryptMobile(handle: Long, input: ByteArray, decrypt: Boolean): ByteArray?
    external fun releaseMobile(handle: Long)
    external fun liveMobileHandles(): Int
}
