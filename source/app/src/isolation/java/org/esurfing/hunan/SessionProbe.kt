package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.net.Network
import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import java.net.*
import java.util.concurrent.*

class FixtureActivity : android.app.Activity() {
    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(android.widget.TextView(this).apply { text = "隔离模拟测试：不提交校园账号" })
    }
}

/** Only this isolated subclass rewrites targets. No hook, fixture endpoint or mock class is in release. */
class MockSessionService : SessionService() {
    override fun mapHttpUrl(network: Network, url: URL): URL {
        check(packageName == "org.esurfing.hunan.isolation")
        val path = when {
            url.host == "127.0.0.1" -> url.file
            else -> "/probe"
        }
        return URL("http://127.0.0.1:${SessionFixture.port}$path")
    }
}

private object SessionFixture {
    @Volatile var port = 0
    @Volatile var delay = "none"
    @Volatile var accepted = CountDownLatch(1)
    @Volatile var discovery = false
    @Volatile var keepCount = 0
    val executor = Executors.newFixedThreadPool(4)
    fun serve(socket: Socket) {
        try {
            socket.use {
                socket.soTimeout = 5000
                val input = socket.getInputStream()
                val bytes = ArrayList<Byte>()
                while(bytes.size < 32768) {
                    val n = input.read(); if(n < 0) return
                    bytes.add(n.toByte())
                    if(bytes.size >= 4 && bytes.takeLast(4) == listOf<Byte>(13,10,13,10)) break
                }
                val header = bytes.toByteArray().toString(Charsets.US_ASCII)
                val path = header.substringBefore("\r\n").split(' ').getOrElse(1) { "/" }.substringBefore('?')
                val length = Regex("(?im)^Content-Length: ([0-9]+)").find(header)?.groupValues?.get(1)?.toInt() ?: 0
                check(length in 0..65536)
                repeat(length) { if(input.read() < 0) return }
                val phase = when(path) { "/auth.cgi" -> "auth"; "/keep.cgi" -> { keepCount++; if(keepCount > 1) "heartbeat" else "initial-keep" }; "/probe" -> if(discovery) "discovery" else "probe"; else -> "other" }
                if(phase == delay || (delay == "budget" && phase == "auth")) accepted.countDown()
                if(phase == delay) Thread.sleep(2000)
                val output = socket.getOutputStream()
                if(path == "/probe") {
                    val location = if(discovery) "Location: http://127.0.0.1:$port/index.cgi?wlanuserip=127.0.0.2&wlanusermac=001122334455&mscgip=127.0.0.1\r\n" else ""
                    val body = if(discovery) "" else "fixture"
                    output.write("HTTP/1.1 ${if(discovery) "302 Found" else "200 OK"}\r\n${location}Content-Length: ${body.length}\r\nConnection: close\r\n\r\n$body".toByteArray())
                    if(discovery) discovery = false
                    return
                }
                val fields = when(path) {
                    "/ticket.cgi" -> "<ticket>isolated-ticket</ticket>"
                    "/auth.cgi" -> "<userid>isolated-fixture-user</userid><keep-url>http://127.0.0.1:$port/keep.cgi</keep-url><term-url>http://127.0.0.1:$port/term.cgi</term-url>"
                    "/keep.cgi" -> "<interval>30</interval>"
                    else -> "<state>0</state>"
                }
                val body = if(path == "/term.cgi") "" else checkNotNull(NativeCore.crypt("<response>$fields</response>", false))
                output.write("HTTP/1.1 200 OK\r\nError-Code: 0\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n".toByteArray())
                if(delay == "budget" && phase == "auth") {
                    for(ch in body) { output.write(ch.code); output.flush(); Thread.sleep(2000) }
                } else output.write(body.toByteArray())
            }
        } catch (_: Exception) { /* Expected when the client cancels a delayed synthetic response. */ }
    }
}

class SessionProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        var stage = "guard"
        var server: ServerSocket? = null
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            ctx.startActivity(Intent(ctx, FixtureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            val listening = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
            server = listening
            SessionFixture.port = listening.localPort
            Thread {
                try { while(!listening.isClosed) { val socket = listening.accept(); SessionFixture.executor.execute { SessionFixture.serve(socket) } } }
                catch (_: Exception) { }
            }.apply { isDaemon = true; start() }
            val prefs = ctx.getSharedPreferences("settings", 0)
            var revision = 100L
            fun configure(discovery: Boolean = false) {
                SessionFixture.discovery = discovery; SessionFixture.keepCount = 0
                prefs.edit().clear().putString("username", "isolated-fixture-user").putString("channel", "windows")
                    .putString("portal", if(discovery) "" else "http://127.0.0.1:${listening.localPort}")
                    .putString("ip", "127.0.0.2").putString("gateway", "127.0.0.1").putString("mscgip", "127.0.0.1")
                    .putString("mac", "00-11-22-33-44-55").putLong("configRevision", ++revision).commit()
                IdentityCache.clear(ctx)
                Credentials(ctx).save("isolated-fixture-password")
            }
            fun command(action: String) = runOnMainSync { ctx.startForegroundService(Intent(ctx, MockSessionService::class.java).setAction(action)) }
            fun await(timeout: Long = 5000, predicate: () -> Boolean) {
                val end = SystemClock.elapsedRealtime()+timeout
                while(!predicate()) { check(SystemClock.elapsedRealtime()<end); Thread.sleep(20) }
            }
            fun stop() {
                command("stop")
                await { SessionState.snapshot().phase == Phase.STOPPED && !SessionState.snapshot().desired && SessionService.instancesCreated.get() == SessionService.instancesDestroyed.get() }
                runOnMainSync { }
            }
            // These are explicitly synthetic interval=30 responses, not real-server semantics.
            for(phase in listOf("discovery", "auth", "probe", "heartbeat")) {
                stage = phase
                configure(phase == "discovery")
                SessionFixture.delay = phase; SessionFixture.accepted = CountDownLatch(1)
                command("start")
                check(SessionFixture.accepted.await(if(phase == "heartbeat") 65 else 8, TimeUnit.SECONDS))
                stop()
                val generation = SessionState.snapshot().generation
                Thread.sleep(2300)
                check(SessionState.snapshot().phase == Phase.STOPPED && SessionState.snapshot().generation == generation)
                sendStatus(1, Bundle().apply { putString("phase", "PASS synthetic $phase cancellation") })
            }
            stage = "budget"
            configure(); SessionFixture.delay = "budget"; SessionFixture.accepted = CountDownLatch(1)
            command("start"); check(SessionFixture.accepted.await(8, TimeUnit.SECONDS))
            val started = SystemClock.elapsedRealtime()
            await(26000) { SessionState.snapshot().phase == Phase.NEEDS_INPUT }
            check(SystemClock.elapsedRealtime()-started < 25000)
            stop()
            stage = "100 synthetic sessions"
            val resources = mutableListOf<String>()
            SessionFixture.delay = "none"
            repeat(100) { cycle ->
                configure(); command("start")
                await(8000) { SessionState.snapshot().phase == Phase.AUTHENTICATED && SessionState.snapshot().internetResult == CheckResult.PASS }
                stop()
                if(cycle % 25 == 0 || cycle == 99) resources.add("${cycle+1}:${Thread.getAllStackTraces().size}:${android.os.Debug.getNativeHeapAllocatedSize()}")
                if(cycle % 10 == 0) sendStatus(1, Bundle().apply { putInt("completedSyntheticSessions", cycle+1) })
            }
            Thread.sleep(3000)
            resources.add("idle3s:${Thread.getAllStackTraces().size}:${android.os.Debug.getNativeHeapAllocatedSize()}")
            System.gc(); System.runFinalization(); Thread.sleep(1000)
            resources.add("forcedGC:${Thread.getAllStackTraces().size}:${android.os.Debug.getNativeHeapAllocatedSize()}")
            Credentials(ctx).clear(); prefs.edit().clear().commit(); IdentityCache.clear(ctx)
            finish(-1, Bundle().apply {
                putString("result", "PASS: isolated simulated discovery/auth/probe/scheduled-heartbeat stop + late results, slow-body request budget, 100 auth/initial-heartbeat/probe/stop cycles; NOT real-campus or background endurance")
                putString("resources_cycle_threads_nativeBytes", resources.joinToString(","))
            })
        } catch(t: Throwable) {
            finish(0, Bundle().apply { putString("result", "FAIL stage=$stage class=${t.javaClass.simpleName}; line=${t.stackTrace.firstOrNull { it.fileName == "SessionProbe.kt" }?.lineNumber}") })
        } finally { server?.close(); SessionFixture.executor.shutdownNow() }
    }
}

