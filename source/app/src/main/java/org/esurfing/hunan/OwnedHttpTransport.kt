package org.esurfing.hunan

import android.net.Network
import okhttp3.*
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** A generation owns its pools. Networks and sockets are never cached across generations. */
class OwnedHttpTransport : AutoCloseable {
    companion object {
        val owners = AtomicInteger()
        val connections = AtomicInteger()
    }
    private val closed = AtomicBoolean()
    private val clients = mutableMapOf<Network, OkHttpClient>()
    init { owners.incrementAndGet() }

    @Synchronized fun open(network: Network, url: URL): HttpURLConnection {
        check(!closed.get()) { "操作已停止" }
        TransportPolicy.check(url, false)
        val client = clients.getOrPut(network) {
            OkHttpClient.Builder()
                .socketFactory(network.socketFactory)
                .dns(object : Dns { override fun lookup(hostname: String) = network.getAllByName(hostname).toList() })
                .connectionPool(ConnectionPool(2, 30, TimeUnit.SECONDS))
                .protocols(listOf(okhttp3.Protocol.HTTP_1_1))
                .followRedirects(false).followSslRedirects(false)
                .retryOnConnectionFailure(false)
                .callTimeout(20, TimeUnit.SECONDS)
                .build()
        }
        return OwnedConnection(url, client) { if (closed.get()) client.connectionPool.evictAll() }
    }

    @Synchronized override fun close() {
        if (!closed.compareAndSet(false, true)) return
        clients.values.forEach { it.dispatcher.cancelAll(); it.connectionPool.evictAll() }
        clients.clear()
        owners.decrementAndGet()
    }

    /** Small adapter for existing protocol code; no redirect, cache, cookies or POST replay. */
    private class OwnedConnection(url: URL, private val client: OkHttpClient, private val released: () -> Unit) : HttpURLConnection(url) {
        private val output = ByteArrayOutputStream()
        private val headers = linkedMapOf<String, String>()
        private val ended = AtomicBoolean()
        @Volatile private var call: Call? = null
        private var response: Response? = null
        init { connections.incrementAndGet() }
        override fun setRequestProperty(key: String, value: String) { check(!connected); headers[key] = value }
        override fun getRequestProperty(key: String): String? = headers.entries.firstOrNull { it.key.equals(key, true) }?.value
        override fun getOutputStream(): java.io.OutputStream { check(!connected); return output }
        private fun result(): Response {
            response?.let { return it }
            if (ended.get()) throw IOException("操作已停止")
            check(!instanceFollowRedirects) { "自动跳转未启用" }
            val request = Request.Builder().url(url)
            headers.forEach { (key, value) -> request.header(key, value) }
            val data = output.toByteArray()
            val body = if (doOutput || method in listOf("POST", "PUT", "PATCH")) object : RequestBody() {
                override fun contentType(): MediaType? = null
                override fun contentLength() = data.size.toLong()
                // Also forbids OkHttp's HTTP 408/503 follow-up replay of a credential POST.
                override fun isOneShot() = true
                override fun writeTo(sink: okio.BufferedSink) { sink.write(data) }
            } else null
            request.method(method, body)
            val next = client.newBuilder().connectTimeout(connectTimeout.toLong(), TimeUnit.MILLISECONDS)
                .readTimeout(readTimeout.toLong(), TimeUnit.MILLISECONDS)
                .writeTimeout(10, TimeUnit.SECONDS).build().newCall(request.build())
            synchronized(this) {
                if (ended.get()) throw IOException("操作已停止")
                call = next; connected = true
            }
            val received = next.execute()
            synchronized(this) {
                if (ended.get()) { received.close(); released(); throw IOException("操作已停止") }
                response = received
            }
            return received
        }
        override fun connect() { result() }
        override fun getResponseCode(): Int = result().code
        override fun getResponseMessage(): String = result().message
        override fun getHeaderField(name: String?): String? = if(name == null) "HTTP/1.1 ${result().code} ${result().message}" else result().header(name)
        override fun getHeaderFields(): Map<String, List<String>> = result().headers.toMultimap()
        override fun getInputStream(): InputStream {
            val value = result()
            if (value.code >= 400) throw IOException("HTTP ${value.code}")
            return value.body!!.byteStream()
        }
        override fun getErrorStream(): InputStream? = result().takeIf { it.code >= 400 }?.body?.byteStream()
        override fun usingProxy() = false
        @Synchronized override fun disconnect() {
            if (!ended.compareAndSet(false, true)) return
            call?.cancel()
            response?.close()
            response = null
            output.reset()
            connections.decrementAndGet()
            released()
        }
    }
}
