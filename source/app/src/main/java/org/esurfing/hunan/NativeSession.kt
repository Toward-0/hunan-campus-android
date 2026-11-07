package org.esurfing.hunan

import java.util.concurrent.atomic.AtomicLong

class NativeSession(module: ByteArray) : AutoCloseable {
    private val handle = AtomicLong(NativeCore.createMobile(module).also { require(it != 0L) { "服务端动态算法模块不受支持" } })
    val algorithm: String = try { NativeCore.mobileId(handle.get()) ?: error("动态算法标识缺失") }
        catch (e: Throwable) { close(); throw e }
    fun crypt(text: String, decrypt: Boolean): String {
        val result = NativeCore.cryptMobile(handle.get(), text.toByteArray(Charsets.UTF_8), decrypt)
            ?: error("动态协议加解密失败或会话已停止")
        return result.toString(Charsets.UTF_8)
    }
    override fun close() { NativeCore.releaseMobile(handle.getAndSet(0)) }
}
