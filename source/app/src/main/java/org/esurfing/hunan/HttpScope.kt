package org.esurfing.hunan

import android.net.Network
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** One connection generation owns discovery, protocol and probes. No wake lock or periodic work here. */
class HttpScope(val generation: Long = SessionState.snapshot().generation,
    private val mapUrl: (Network, URL) -> URL = { _, url -> url },
    private val opener: ((Network, URL) -> HttpURLConnection)? = null) : AutoCloseable {
    companion object {
        private val deadlines = ScheduledThreadPoolExecutor(1) { task -> Thread(task, "http-budget").apply { isDaemon = true } }
            .apply { removeOnCancelPolicy = true }
        fun queuedDeadlines() = deadlines.queue.size
    }
    private val cancelled = AtomicBoolean()
    private var owned: OwnedHttpTransport? = null
    private data class Lease(val deadline: Long, val timer: ScheduledFuture<*>)
    private val calls = ConcurrentHashMap<HttpURLConnection, Lease>()
    @Synchronized fun open(network: Network, url: URL): HttpURLConnection {
        check(!cancelled.get())
        val mapped = mapUrl(network, url)
        TransportPolicy.check(mapped, opener != null)
        val connection = opener?.invoke(network, mapped) ?: (owned ?: OwnedHttpTransport().also { owned = it }).open(network, mapped)
        val deadline = android.os.SystemClock.elapsedRealtime() + 20000
        val timer = deadlines.schedule({
            if(calls.containsKey(connection)) {
                TimingTrace.emit(TracePoint.CONTROL, generation, error = ErrorKind.NETWORK, numeric = 20000)
                connection.disconnect()
            }
        }, 20, TimeUnit.SECONDS)
        calls[connection] = Lease(deadline, timer)
        if(cancelled.get()) { finish(connection); error("操作已停止") }
        return connection
    }
    fun finish(connection: HttpURLConnection) {
        calls.remove(connection)?.timer?.cancel(false)
        connection.disconnect()
    }
    fun checkActive(connection: HttpURLConnection) {
        val lease = calls[connection]
        if(cancelled.get() || lease == null) throw java.io.InterruptedIOException("操作已停止")
        if(android.os.SystemClock.elapsedRealtime() >= lease.deadline) {
            finish(connection)
            throw java.net.SocketTimeoutException("请求超出时间预算")
        }
    }
    @Synchronized fun cancel() {
        cancelled.set(true)
        interruptInFlight()
        owned?.close(); owned = null
    }
    override fun close() = cancel()
    fun interruptInFlight() {
        calls.keys.toList().forEach { finish(it) }
    }
}


