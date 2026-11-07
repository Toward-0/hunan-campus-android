package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.net.*
import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import org.json.JSONObject
import java.io.File
import java.net.*
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicInteger

/** Non-exported and compiled ONLY into the separate .isolation APK. Every request is loopback. */
class StabilityService : SessionService() {
    override fun mapHttpUrl(network: Network, url: URL): URL {
        check(packageName == "org.esurfing.hunan.isolation")
        val path = if(url.host == "127.0.0.1") url.file else when {
            url.protocol == "https" && url.host == "www.baidu.com" -> "/https-primary"
            url.protocol == "https" -> "/https-secondary"
            else -> "/portal"
        }
        return URL("http://127.0.0.1:${StabilityFixture.port}$path")
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if(intent?.action in listOf("fixture-loss", "fixture-identity")) {
            val cm = getSystemService(ConnectivityManager::class.java)
            val network = cm.allNetworks.first { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
            if(intent?.action == "fixture-loss") handleNetworkLost(network)
            else {
                // Inject disappearance of IPv4/gateway via the real handler; do not alter phone Wi-Fi.
                // The public constructor was added in API 29; API 26 has the
                // platform constructor but it was not part of the public SDK.
                val empty = if(android.os.Build.VERSION.SDK_INT >= 29) LinkProperties()
                    else LinkProperties::class.java.getDeclaredConstructor().newInstance()
                handleLinkPropertiesChanged(network, empty)
            }
            return START_NOT_STICKY
        }
        return super.onStartCommand(intent, flags, startId)
    }
}

internal object StabilityFixture {
    @Volatile var port = 0
    @Volatile var persistent = true
    @Volatile var portal = false
    @Volatile var primaryTimeout = false
    @Volatile var logoutConfirmed = true
    @Volatile var delayPath = ""
    @Volatile var delayed = CountDownLatch(1)
    @Volatile var responseGate: CountDownLatch? = null
    @Volatile var clientIp = "127.0.0.2"
    @Volatile var discoveryUnavailable = false
    val counts = ConcurrentHashMap<String, AtomicInteger>()
    val sockets = ConcurrentHashMap.newKeySet<Socket>()
    val acceptedSockets = AtomicInteger()
    lateinit var module: ByteArray
    lateinit var cipher: NativeSession
    private var sequence = AtomicInteger()
    val executor = ThreadPoolExecutor(0, 128, 2, TimeUnit.SECONDS, SynchronousQueue<Runnable>(),
        ThreadFactory { task -> Thread(task, "fixture-http-${sequence.incrementAndGet()}").apply { isDaemon = true } })
    fun count(path: String) = counts[path]?.get() ?: 0
    fun closeSockets() { sockets.toList().forEach { runCatching { it.close() } } }
    fun serve(socket: Socket) {
        sockets.add(socket); acceptedSockets.incrementAndGet()
        try { socket.use {
            socket.soTimeout = 35000
            val input = socket.getInputStream().buffered()
            val output = socket.getOutputStream()
            while(!socket.isClosed) {
                val bytes = ArrayList<Byte>()
                while(bytes.size < 32768) {
                    val value = input.read(); if(value < 0) return
                    bytes.add(value.toByte())
                    val n = bytes.size
                    if(n >= 4 && bytes[n-4] == 13.toByte() && bytes[n-3] == 10.toByte() && bytes[n-2] == 13.toByte() && bytes[n-1] == 10.toByte()) break
                }
                val header = bytes.toByteArray().toString(Charsets.US_ASCII)
                val rawPath = header.substringBefore("\r\n").split(' ')[1].substringBefore('?')
                val length = Regex("(?im)^Content-Length: ([0-9]+)").find(header)?.groupValues?.get(1)?.toInt() ?: 0
                val path = if(rawPath == "/ticket.cgi" && length == 0) "/algo.cgi" else rawPath
                check(length in 0..65536)
                val request = ByteArray(length)
                var offset = 0
                while(offset < length) { val n = input.read(request, offset, length-offset); if(n < 0) return; offset += n }
                counts.computeIfAbsent(path) { AtomicInteger() }.incrementAndGet()
                if(path == delayPath) {
                    delayed.countDown()
                    val gate = responseGate
                    if(gate == null) Thread.sleep(2200) else check(gate.await(15, TimeUnit.SECONDS))
                }
                if(path == "/https-primary" && primaryTimeout) Thread.sleep(4500)
                val isModule = path == "/algo.cgi"
                val status = if(path == "/portal" && !discoveryUnavailable) 302 else if((portal && path.startsWith("/https")) || (path == "/term.cgi" && !logoutConfirmed)) 503 else 200
                val fields = when(path) {
                    "/ticket.cgi" -> "<ticket>public-synthetic-ticket</ticket>"
                    "/auth.cgi" -> "<userid>isolated-fixture-user</userid><keep-url>http://127.0.0.1:$port/keep.cgi</keep-url><term-url>http://127.0.0.1:$port/term.cgi</term-url>"
                    "/keep.cgi" -> "<interval>30</interval>"
                    else -> "<state>0</state>"
                }
                if(path == "/auth.cgi") {
                    val decoded = cipher.crypt(request.toString(Charsets.US_ASCII), true)
                    check(decoded.contains("<userid>isolated-fixture-user</userid>"))
                    check(decoded.contains("<passwd>isolated-fixture-password</passwd>"))
                }
                val body = when {
                    isModule -> module
                    path in listOf("/portal", "/term.cgi") -> byteArrayOf()
                    path.startsWith("/https") || path == "/echo" -> "public-fixture".toByteArray()
                    else -> cipher.crypt("<response>$fields</response>", false).toByteArray(Charsets.US_ASCII)
                }
                val location = if(path == "/portal") "Location: http://127.0.0.1:$port/index.cgi?wlanuserip=$clientIp&wlanusermac=001122334455&mscgip=127.0.0.1\r\n" else ""
                output.write("HTTP/1.1 $status Fixture\r\nError-Code: ${if(isModule) 200 else 0}\r\n${location}Content-Length: ${body.size}\r\nConnection: ${if(persistent) "keep-alive" else "close"}\r\n\r\n".toByteArray())
                output.write(body); output.flush()
                if(!persistent) return
            }
        } } catch (_: Exception) { /* Expected on cancellation/timeout. No request contents logged. */ }
        finally { sockets.remove(socket) }
    }
}

class StabilityProbe : Instrumentation() {
    private var mode = "lifecycle"
    override fun onCreate(arguments: Bundle?) { mode = arguments?.getString("mode") ?: mode; super.onCreate(arguments); start() }
    override fun onStart() {
        var stage = "setup"
        var server: ServerSocket? = null
        var report: File? = null
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            report = File(ctx.filesDir, "stability-$mode.jsonl"); report.writeText("")
            fun record(name: String, extra: JSONObject = JSONObject()) {
                extra.put("case", name).put("elapsed", SystemClock.elapsedRealtime()).put("pid", Process.myPid())
                report.appendText(extra.toString()+"\n")
                sendStatus(1, Bundle().apply { putString("case", name) })
            }
            ctx.startActivity(Intent(ctx, FixtureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            StabilityFixture.module = ctx.assets.open("synthetic-module.zsm").use { it.readBytes() }
            val malformed = ctx.assets.open("synthetic-short.zsm").use { it.readBytes() }
            repeat(200) {
                check(NativeCore.createMobile(malformed) == 0L)
                NativeSession(StabilityFixture.module).use { engine ->
                    check(engine.crypt(engine.crypt("public-round-trip-$it", false), true) == "public-round-trip-$it")
                }
                check(NativeCore.liveMobileHandles() == 0)
            }
            record("JNI synthetic 200 valid/short malformed lifecycles", JSONObject().put("handles", NativeCore.liveMobileHandles()))
            StabilityFixture.cipher = NativeSession(StabilityFixture.module)
            val listening = ServerSocket(0, 32, InetAddress.getByName("127.0.0.1")); server = listening
            StabilityFixture.port = listening.localPort
            Thread {
                try { while(!listening.isClosed) { val socket = listening.accept(); StabilityFixture.executor.execute { StabilityFixture.serve(socket) } } }
                catch (_: Exception) { }
            }.apply { name = "fixture-accept"; isDaemon = true; start() }
            val prefs = ctx.getSharedPreferences("settings", 0)
            fun configure(discovery: Boolean = false) {
                StabilityFixture.portal = false; StabilityFixture.logoutConfirmed = true
                StabilityFixture.primaryTimeout = false; StabilityFixture.delayPath = ""
                StabilityFixture.responseGate = null
                StabilityFixture.discoveryUnavailable = false
                StabilityFixture.counts.clear()
                val connectivity = ctx.getSystemService(ConnectivityManager::class.java)
                val wifi = connectivity.allNetworks.first { connectivity.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
                StabilityFixture.clientIp = if(discovery) connectivity.getLinkProperties(wifi)!!.linkAddresses.first { it.address is Inet4Address }.address.hostAddress!! else "127.0.0.2"
                prefs.edit().clear().putString("username", "isolated-fixture-user")
                    .putString("portal", if(discovery) "" else "http://127.0.0.1:${listening.localPort}")
                    .putString("ip", if(discovery) "" else "127.0.0.2").putString("gateway", if(discovery) "" else "127.0.0.1")
                    .putString("mscgip", if(discovery) "" else "127.0.0.1")
                    .putString("mac", if(discovery) "" else "00-11-22-33-44-55").commit()
                IdentityCache.clear(ctx); Credentials(ctx).save("isolated-fixture-password")
            }
            fun command(action: String) = runOnMainSync { ctx.startForegroundService(Intent(ctx, StabilityService::class.java).setAction(action)) }
            fun await(timeout: Long = 10000, predicate: () -> Boolean) {
                val end = SystemClock.elapsedRealtime()+timeout
                while(!predicate()) { check(SystemClock.elapsedRealtime()<end) { "Timeout at $stage" }; Thread.sleep(25) }
            }
            fun stopped() {
                await { SessionService.instancesCreated.get() == SessionService.instancesDestroyed.get() }
                await { OwnedHttpTransport.owners.get() == 0 && OwnedHttpTransport.connections.get() == 0 && HttpScope.queuedDeadlines() == 0 }
                check(WakeupDispatch.size() == 0)
                check(NativeCore.liveMobileHandles() == 1) // fixture cipher only
                runOnMainSync { }
            }
            fun stop() { command("stop"); stopped() }
            fun online() = await(15000) { SessionState.snapshot().phase == Phase.AUTHENTICATED && SessionState.snapshot().internetEvidence == InternetEvidence.HTTPS_VERIFIED }
            fun resources(): JSONObject {
                val threads = Thread.getAllStackTraces().keys
                return JSONObject().put("threadsTotal", threads.size).put("threadsWithoutFixture", threads.count { !it.name.startsWith("fixture-") })
                    .put("platformPools", threads.count { it.name.contains("ConnectionPool") })
                    .put("ownedPools", OwnedHttpTransport.owners.get()).put("calls", OwnedHttpTransport.connections.get())
                    .put("deadlines", HttpScope.queuedDeadlines()).put("callbacks", WakeupDispatch.size())
                    .put("jniHandlesIncludingFixture", NativeCore.liveMobileHandles()).put("nativeBytes", android.os.Debug.getNativeHeapAllocatedSize())
                    .put("fd", File("/proc/self/fd").list()?.size ?: -1)
            }

            if(mode == "account") {
                fun blockedUi(label: String) {
                    val activity = startActivitySync(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    fun views(v: android.view.View): List<android.view.View> = listOf(v) + if(v is android.view.ViewGroup)
                        (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
                    val all = views(activity.window.decorView)
                    val user = all.filterIsInstance<android.widget.EditText>().first { it.hint.toString() == "账号" }
                    val password = all.filterIsInstance<android.widget.EditText>().first { it.hint.toString() == "留空保留已保存密码" }
                    val save = all.filterIsInstance<android.widget.Button>().first { it.text.toString() == "保存并连接" }
                    val revision = prefs.getLong("configRevision", 0)
                    runOnMainSync {
                        user.setText("isolated-new-account"); password.setText("isolated-new-password")
                        repeat(10) { save.performClick() }
                        check(user.text.toString() == "isolated-new-account" && password.text.toString() == "isolated-new-password")
                    }
                    check(prefs.getString("username", "") == "isolated-fixture-user")
                    check(Credentials(ctx).load() == "isolated-fixture-password")
                    check(prefs.getLong("configRevision", 0) == revision)
                    runOnMainSync { activity.finish() }
                    record(label)
                }
                for(onlineResult in listOf(true, false)) {
                    stage = "discovery-exhausted-$onlineResult"
                    configure(true); StabilityFixture.discoveryUnavailable = true
                    StabilityFixture.portal = !onlineResult
                    command("start")
                    await { StabilityFixture.count("/portal") >= 3 && SessionState.snapshot().phase == Phase.DISCOVERING }
                    val before = SessionState.snapshot().generation
                    blockedUi("waiting-account-change-rejected-$onlineResult")
                    repeat(10) { command("start") }
                    check(SessionState.snapshot().generation == before)
                    await(60000) { SessionState.snapshot().phase == Phase.NEEDS_INPUT }; stopped()
                    check(!SessionState.snapshot().desired && !SessionState.snapshot().configurationBlocked())
                    check(prefs.getBoolean("manualOff", false))
                    check(StabilityFixture.count("/portal") == 10) // 3x3 discovery + one final bounded check
                    check(StabilityFixture.count("/https-primary") == 1)
                    check(StabilityFixture.count("/https-secondary") == if(onlineResult) 0 else 1)
                    check(StabilityFixture.count("/auth.cgi") == 0 && StabilityFixture.count("/ticket.cgi") == 0)
                    check(SessionState.snapshot().status.contains(if(onlineResult) "外网检测通过" else "外网未确认可用"))
                    val count = StabilityFixture.count("/portal")
                    Thread.sleep(1500); check(StabilityFixture.count("/portal") == count)
                    record(stage, resources().put("discoveryRequests", 9).put("loginRequests", 0))
                    // Explicit new action is accepted; no cache/identity fallback is used.
                    StabilityFixture.discoveryUnavailable = false; StabilityFixture.portal = false
                    command("start"); online(); check(StabilityFixture.count("/auth.cgi") == 1)
                    check(SessionState.snapshot().generation > before)
                    blockedUi("authenticated-account-change-rejected-$onlineResult")
                    StabilityFixture.delayPath = "/term.cgi"; StabilityFixture.delayed = CountDownLatch(1)
                    StabilityFixture.responseGate = CountDownLatch(1)
                    command("logout"); check(StabilityFixture.delayed.await(10, TimeUnit.SECONDS))
                    check(SessionState.snapshot().phase == Phase.LOGGING_OUT)
                    blockedUi("logout-account-change-rejected-$onlineResult")
                    repeat(10) { command("start"); command("logout") }
                    StabilityFixture.responseGate!!.countDown()
                    await { SessionState.snapshot().phase == Phase.LOGGED_OUT }; stopped()
                    check(StabilityFixture.count("/auth.cgi") == 1 && StabilityFixture.count("/term.cgi") == 1)
                    record("manual-retry-and-explicit-logout-$onlineResult", resources())
                }
                for(action in listOf("stop", "fixture-loss", "fixture-identity", "service-end")) {
                    stage = "cancel-discovery-$action"
                    configure(true); StabilityFixture.discoveryUnavailable = true
                    command("start"); await { StabilityFixture.count("/portal") >= 3 && SessionState.snapshot().phase == Phase.DISCOVERING }
                    if(action == "service-end") runOnMainSync { ctx.stopService(Intent(ctx, StabilityService::class.java)) }
                    else command(action)
                    stopped(); val count = StabilityFixture.count("/portal")
                    Thread.sleep(11000)
                    check(StabilityFixture.count("/portal") == count && StabilityFixture.count("/auth.cgi") == 0)
                    record(stage, resources())
                }
                // The real save handler after stopping accepts a synthetic account change once.
                configure(); SessionState.change { it.copy(phase = Phase.STOPPED, desired = false) }
                val activity = startActivitySync(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                fun views(v: android.view.View): List<android.view.View> = listOf(v) + if(v is android.view.ViewGroup)
                    (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
                val all = views(activity.window.decorView)
                val user = all.filterIsInstance<android.widget.EditText>().first { it.hint.toString() == "账号" }
                val password = all.filterIsInstance<android.widget.EditText>().first { it.hint.toString() == "留空保留已保存密码" }
                val save = all.filterIsInstance<android.widget.Button>().first { it.text.toString() == "保存并连接" }
                runOnMainSync {
                    user.setText("isolated-new-account"); password.setText("isolated-new-password")
                    repeat(10) { save.performClick() }
                    check(prefs.getString("username", "") == "isolated-new-account")
                    check(Credentials(ctx).load() == "isolated-new-password")
                    check(prefs.getLong("configRevision", 0) == 1L)
                    // Stop before any delayed authentication. Same package is isolation-only.
                    ctx.startForegroundService(Intent(ctx, SessionService::class.java).setAction("stop"))
                    activity.finish()
                }
                stopped(); Thread.sleep(1200); check(StabilityFixture.count("/auth.cgi") == 0)
                record("stopped-ui-save-once-no-implicit-login", resources())
            } else if(mode == "process") {
                stage = "process termination with a scheduled heartbeat"
                configure(); command("start"); online()
                record("READY_PROCESS_KILL", resources().put("generation", SessionState.snapshot().generation))
                Thread.sleep(180000)
                error("External process-kill test did not run")
            } else if(mode == "transport") {
                stage = "transport A/B"
                val cm = ctx.getSystemService(ConnectivityManager::class.java)
                val wifi = cm.allNetworks.first { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
                // Same request bytes, fresh Network wrapper each generation, no campus traffic.
                for(legacy in listOf(false, true)) for(keep in listOf(false, true)) {
                    StabilityFixture.persistent = keep
                    StabilityFixture.closeSockets()
                    val before = StabilityFixture.acceptedSockets.get()
                    val echoBefore = StabilityFixture.count("/echo")
                    repeat(if(keep) 12 else 100) {
                            val parcel = android.os.Parcel.obtain()
                            val network = try { wifi.writeToParcel(parcel, 0); parcel.setDataPosition(0); Network.CREATOR.createFromParcel(parcel) }
                                finally { parcel.recycle() }
                        val scope = if(legacy) HttpScope(0, opener = { n, u -> n.openConnection(u) as HttpURLConnection }) else HttpScope()
                        scope.use {
                            repeat(3) {
                                val c = scope.open(network, URL("http://127.0.0.1:${listening.localPort}/echo"))
                                try {
                                    c.instanceFollowRedirects=false; c.connectTimeout=2000; c.readTimeout=2000
                                    c.requestMethod="POST"; c.doOutput=true; c.setFixedLengthStreamingMode(7)
                                    c.setRequestProperty("Client-ID", "public-fixture")
                                    c.outputStream.use { it.write("fixture".toByteArray()) }
                                    check(c.responseCode==200 && c.getHeaderField("Error-Code")=="0")
                                    check(c.inputStream.use { it.readBytes().toString(Charsets.US_ASCII) } == "public-fixture")
                                } finally { scope.finish(c) }
                            }
                        }
                    }
                    val requests = StabilityFixture.count("/echo")-echoBefore
                    val sockets = StabilityFixture.acceptedSockets.get()-before
                    if(!legacy) check(sockets == if(keep) 12 else 300)
                    check(requests == if(keep) 36 else 300)
                    record("${if(legacy) "baseline" else "owned"}-${if(keep) "persistent" else "close"}", resources().put("requests", requests).put("acceptedSockets", sockets))
                    StabilityFixture.closeSockets(); Thread.sleep(2500)
                }
            } else if(mode == "repair") {
                for(action in listOf("unconfirmed", "stop", "fixture-loss", "fixture-identity", "service-end", "success")) {
                    stage = "repair-$action"
                    configure(); StabilityFixture.portal = true
                    command("start")
                    await(55000) { SessionState.snapshot().repairAvailable }
                    check(StabilityFixture.count("/auth.cgi") == 1 && SessionState.snapshot().internetEvidence == InternetEvidence.PORTAL_REQUIRED)
                    StabilityFixture.logoutConfirmed = action != "unconfirmed"
                    repeat(5) { command("repair") }
                    if(action == "unconfirmed") {
                        await { SessionState.snapshot().phase == Phase.NEEDS_INPUT }; stopped()
                    } else {
                        await { SessionState.snapshot().nextRecoveryAt > 0 }
                        val confirmedAt = SystemClock.elapsedRealtime()
                        repeat(5) { command("start"); command("repair") }
                        check(StabilityFixture.count("/auth.cgi") == 1 && StabilityFixture.count("/term.cgi") == 1)
                        if(action == "success") {
                            StabilityFixture.portal = false
                            onlineWait@ run {
                                await(112000) { SessionState.snapshot().phase == Phase.AUTHENTICATED && SessionState.snapshot().internetEvidence == InternetEvidence.HTTPS_VERIFIED }
                            }
                            check(SystemClock.elapsedRealtime()-confirmedAt >= 99000)
                            check(StabilityFixture.count("/auth.cgi") == 2)
                            repeat(5) { command("repair") }; Thread.sleep(500)
                            check(StabilityFixture.count("/auth.cgi") == 2 && StabilityFixture.count("/term.cgi") == 1)
                            stop()
                        } else if(action == "service-end") {
                            runOnMainSync { ctx.stopService(Intent(ctx, StabilityService::class.java)) }; stopped()
                            check(SessionState.snapshot().phase == Phase.INTERRUPTED && !SessionState.snapshot().repairing)
                        } else { command(action); stopped() }
                    }
                    if(action != "success") check(StabilityFixture.count("/auth.cgi") == 1)
                    record(stage, resources().put("loginRequests", StabilityFixture.count("/auth.cgi")).put("logoutRequests", StabilityFixture.count("/term.cgi")))
                }
                // Earlier cancelled 100-second waits have elapsed by now; no old worker reauthenticated.
                check(StabilityFixture.count("/auth.cgi") == 2)
            } else {
                stage = "repeated-start-while-discovery-waiting"
                configure(true); StabilityFixture.discoveryUnavailable = true
                command("start")
                await { StabilityFixture.count("/portal") >= 3 && SessionState.snapshot().phase == Phase.DISCOVERING }
                val waitingGeneration = SessionState.snapshot().generation
                repeat(10) { command("start") }; Thread.sleep(500)
                check(SessionState.snapshot().generation == waitingGeneration && StabilityFixture.count("/auth.cgi") == 0)
                stop(); record(stage)
                stage = "discovery-single-point-timeout"
                configure(true); StabilityFixture.primaryTimeout = true
                command("start"); repeat(10) { command("start") }; online()
                check(StabilityFixture.count("/auth.cgi") == 1 && StabilityFixture.count("/https-secondary") == 1)
                stop(); record(stage)
                stage = "normal-logout-unconfirmed"
                configure(); command("start"); online(); StabilityFixture.logoutConfirmed = false
                command("logout"); command("logout")
                await { SessionState.snapshot().phase == Phase.LOGOUT_UNCONFIRMED }; stopped()
                check(StabilityFixture.count("/auth.cgi") == 1 && StabilityFixture.count("/term.cgi") == 1)
                record(stage)
                for(path in listOf("/algo.cgi", "/auth.cgi", "/https-primary", "/term.cgi")) {
                    stage = "late-$path"
                    configure(); StabilityFixture.delayed = CountDownLatch(1)
                    if(path != "/term.cgi") StabilityFixture.delayPath = path
                    command("start")
                    if(path == "/term.cgi") { online(); StabilityFixture.delayPath = path; command("logout"); command("logout") }
                    check(StabilityFixture.delayed.await(10, TimeUnit.SECONDS))
                    stop(); val generation = SessionState.snapshot().generation
                    Thread.sleep(2500)
                    check(SessionState.snapshot().generation == generation && SessionState.snapshot().phase == Phase.STOPPED)
                    check(StabilityFixture.count("/auth.cgi") <= 1)
                    record(stage, resources())
                }
                for(action in listOf("fixture-loss", "fixture-identity", "service-end")) {
                    stage=action; configure(); command("start"); online()
                    if(action=="service-end") runOnMainSync { ctx.stopService(Intent(ctx, StabilityService::class.java)) } else command(action)
                    stopped(); Thread.sleep(1200)
                    check(StabilityFixture.count("/auth.cgi")==1)
                    record(stage, resources())
                }
                stage = "scheduled-heartbeat"
                configure(); command("start"); online()
                val generation=SessionState.snapshot().generation; val initialAt=SessionState.snapshot().heartbeatAt
                await(70000) { StabilityFixture.count("/keep.cgi")>=2 && SessionState.snapshot().heartbeatAt>initialAt }
                check(SessionState.snapshot().generation==generation && StabilityFixture.count("/auth.cgi")==1)
                stop(); record(stage, JSONObject().put("generation", generation).put("keepRequests", StabilityFixture.count("/keep.cgi")))
                for(keep in listOf(true, false)) {
                    StabilityFixture.persistent=keep
                    repeat(100) { cycle ->
                        stage="cycles-$keep-${cycle+1}"; configure(); command("start"); online(); stop()
                        check(StabilityFixture.count("/auth.cgi")==1)
                        if(cycle % 25 == 24) record(stage, resources())
                    }
                    Thread.sleep(3000); record("idle-$keep", resources())
                }
            }
            Credentials(ctx).clear(); prefs.edit().clear().commit(); IdentityCache.clear(ctx)
            StabilityFixture.cipher.close()
            check(NativeCore.liveMobileHandles()==0)
            record("PASS", resources())
            finish(-1, Bundle().apply { putString("result", "PASS isolated $mode; synthetic loopback only; no real-campus acceptance implied") })
        } catch(t: Throwable) {
            val reason="FAIL stage=$stage ${t.javaClass.simpleName} line=${t.stackTrace.firstOrNull { it.fileName=="StabilityProbe.kt" }?.lineNumber}"
            report?.appendText(JSONObject().put("result", reason).toString()+"\n")
            finish(0, Bundle().apply { putString("result", reason) })
        } finally {
            server?.close(); StabilityFixture.closeSockets(); StabilityFixture.executor.shutdownNow()
            runCatching { StabilityFixture.cipher.close() }
        }
    }
}
