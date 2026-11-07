package org.esurfing.hunan

import android.net.Network
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.net.URL
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicInteger

/** Real loopback HTTP, synthetic bytes only. Android socket binding is separately tested on-device. */
fun main() {
    val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
    val executor = Executors.newFixedThreadPool(4)
    server.executor = executor
    val counts = ConcurrentHashMap<String, AtomicInteger>()
    val ports = ConcurrentHashMap<String, MutableSet<Int>>()
    var delayed = CountDownLatch(1)
    server.createContext("/") { exchange ->
        val path = exchange.requestURI.path
        counts.computeIfAbsent(path) { AtomicInteger() }.incrementAndGet()
        ports.computeIfAbsent(path) { ConcurrentHashMap.newKeySet() }.add(exchange.remoteAddress.port)
        try {
            if (exchange.requestMethod == "POST") check(exchange.requestBody.readBytes().contentEquals("fixture".toByteArray()))
            if(path == "/delay") { delayed.countDown(); Thread.sleep(1800) }
            if(path == "/close") exchange.responseHeaders.add("Connection", "close")
            if(path == "/retry") exchange.responseHeaders.add("Retry-After", "0")
            if(path == "/redirect") exchange.responseHeaders.add("Location", "/ok")
            val code = when(path) { "/retry" -> 503; "/redirect" -> 302; else -> 200 }
            exchange.responseHeaders.add("Error-Code", "0")
            exchange.sendResponseHeaders(code, 7)
            exchange.responseBody.use { stream ->
                if(path == "/trickle") {
                    for(value in "fixture".toByteArray()) { stream.write(value.toInt()); stream.flush(); Thread.sleep(4200) }
                } else stream.write("fixture".toByteArray())
            }
        } catch (_: Exception) { } finally { exchange.close() }
    }
    server.start()
    val network = Network()
    fun request(scope: HttpScope, path: String, post: Boolean = false, timeout: Int = 1000): Int {
        val connection = scope.open(network, URL("http://127.0.0.1:${server.address.port}$path"))
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = timeout; connection.readTimeout = timeout
            if(post) { connection.requestMethod = "POST"; connection.doOutput = true; connection.setFixedLengthStreamingMode(7); connection.outputStream.use { it.write("fixture".toByteArray()) } }
            val code = connection.responseCode
            check(connection.getHeaderField("Error-Code") == "0")
            val body = (if(code >= 400) connection.errorStream else connection.inputStream)!!.use { it.readBytes() }
            check(body.contentEquals("fixture".toByteArray()))
            return code
        } finally { scope.finish(connection) }
    }
    try {
        HttpScope().use { scope ->
            repeat(25) { check(request(scope, "/keep", true) == 200) }
            repeat(25) { check(request(scope, "/close", true) == 200) }
            check(request(scope, "/retry", true) == 503)
            check(request(scope, "/redirect", true) == 302)
            check(counts["/retry"]!!.get() == 1 && counts["/redirect"]!!.get() == 1 && counts["/ok"] == null)
        }
        check(ports["/keep"]!!.size == 1) { "Persistent sockets not reused: ${ports["/keep"]!!.size}" }
        check(ports["/close"]!!.size == 25)
        HttpScope().use { scope -> check(runCatching { request(scope, "/delay", timeout = 150) }.isFailure) }
        delayed = CountDownLatch(1)
        val scope = HttpScope()
        val task = CompletableFuture.supplyAsync { runCatching { request(scope, "/delay", timeout = 5000) }.isFailure }
        check(delayed.await(2, TimeUnit.SECONDS)); scope.cancel()
        check(task.get(1, TimeUnit.SECONDS))
        val budgetStarted = System.nanoTime()
        HttpScope().use { scope -> check(runCatching { request(scope, "/trickle", timeout = 6000) }.isFailure) }
        val budgetMs = (System.nanoTime()-budgetStarted)/1_000_000
        check(budgetMs in 19000..24500) { "Whole-request budget was $budgetMs ms" }
        repeat(200) { HttpScope().use { scope -> check(request(scope, "/cycle", true) == 200) } }
        check(OwnedHttpTransport.owners.get() == 0 && OwnedHttpTransport.connections.get() == 0)
        check(HttpScope.queuedDeadlines() == 0)
        println("PASS: real loopback HTTP persistent=25 requests/1 socket; close=25/25; 503/302 POST each sent once; timeout/cancel; slow-body whole-request budget=${budgetMs}ms; 200 generations; owned pools/calls/deadlines=0. No Android/campus claim.")
    } finally { server.stop(0); executor.shutdownNow() }
}
