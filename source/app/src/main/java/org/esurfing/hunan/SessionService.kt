package org.esurfing.hunan

import android.app.*
import android.content.Intent
import android.net.*
import android.os.IBinder
import android.os.SystemClock
import android.os.Handler
import android.os.Looper
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

open class SessionService : Service() {
    companion object {
        val instancesCreated = AtomicLong()
        val instancesDestroyed = AtomicLong()
    }
    private val worker = ScheduledThreadPoolExecutor(1).apply { removeOnCancelPolicy = true }
    private val generation = AtomicLong(SessionState.snapshot().generation)
    @Volatile private var pending: ScheduledFuture<*>? = null
    private lateinit var wakeupScheduler: WakeupScheduler
    @Volatile private var protocol: Protocol? = null
    @Volatile private var selected: Network? = null
    @Volatile private var running = false
    private var fingerprint = ""
    private val examinedNetworks = mutableSetOf<Network>()
    @Volatile private var ticket = ""
    private var failures = 0
    private var configRevision = -1L
    @Volatile private var requests = HttpScope()
    private lateinit var cm: ConnectivityManager
    private lateinit var callback: ConnectivityManager.NetworkCallback
    private val holdCallback = object : ConnectivityManager.NetworkCallback() {}
    private var holdingWifi = false
    private val mainHandler = Handler(Looper.getMainLooper())
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }
    private val repairGate = SessionRepairGate()
    @Volatile private var repairInProgress = false
    @Volatile private var repairProtocol: Protocol? = null
    @Volatile private var destroyed = false
    private var loggingOut = false

    override fun onCreate() {
        super.onCreate()
        instancesCreated.incrementAndGet()
        SessionState.initialize(this)
        cm = getSystemService(ConnectivityManager::class.java)
        wakeupScheduler = WakeupScheduler(this, worker) { alive(it) }
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("session", "校园网连接", NotificationManager.IMPORTANCE_LOW))
        startForeground(1, notification("等待校园 Wi-Fi"))
        callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { if (running && selected == null && network !in examinedNetworks) activate(network) }
            override fun onLost(network: Network) = handleNetworkLost(network)
            override fun onLinkPropertiesChanged(network: Network, lp: LinkProperties) = handleLinkPropertiesChanged(network, lp)
        }
        cm.registerNetworkCallback(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), callback, Handler(Looper.getMainLooper()))
    }

    /** All connectivity transitions run on the main looper, including pending repair cancellation. */
    protected fun handleNetworkLost(network: Network) {
                TimingTrace.emit(TracePoint.CONTROL, reason = StopReason.NETWORK_LOST)
                if (repairInProgress && selected == network) {
                    failRepair(generation.get(), "修复已取消：Wi-Fi 已断开，请检查网络后手动连接")
                    return
                }
                examinedNetworks.remove(network)
                if (!running || selected != network) return
                networkChanged("Wi-Fi 已断开；客户端已停止，请联网后手动连接")
    }
    protected fun handleLinkPropertiesChanged(network: Network, lp: LinkProperties) {
                if (repairInProgress) {
                    if (selected == network && NetworkIdentity.key(lp) != fingerprint)
                        failRepair(generation.get(), "修复已取消：网络身份已变化，请手动连接")
                    return
                }
                if (running && selected == network) {
                    if (fingerprint.isNotEmpty() && NetworkIdentity.key(lp) != fingerprint)
                        networkChanged("Wi-Fi 身份已变化；客户端已停止，请手动连接")
                    else activate(network, lp = lp)
                }
    }

    protected open fun mapHttpUrl(network: Network, url: URL): URL = url

    private fun newScope(id: Long) = HttpScope(id, mapUrl = ::mapHttpUrl)

    private fun networkChanged(message: String) {
        running = false
        prefs.edit().putBoolean("manualOff", true).commit()
        invalidate(); selected = null; fingerprint = ""; ticket = ""
        SessionState.change { it.copy(desired = false, phase = Phase.NEEDS_INPUT, network = "none", error = ErrorKind.NETWORK) }
        update(message); stopSelf()
    }

    private fun holdWifi() {
        if (holdingWifi) return
        try {
            // An active request expresses the running session's need for Wi-Fi;
            // it does not require VALIDATED and does not override user Wi-Fi settings.
            cm.requestNetwork(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET).build(), holdCallback, mainHandler)
            holdingWifi = true
            TimingTrace.emit(TracePoint.WIFI_REQUEST, numeric = 1)
        } catch (_: RuntimeException) {
            TimingTrace.emit(TracePoint.WIFI_REQUEST, numeric = 0, error = ErrorKind.NETWORK)
            SessionState.log("系统未接受 Wi-Fi 网络请求；继续监听现有 Wi-Fi")
        }
    }
    private fun releaseWifi() {
        if (!holdingWifi) return
        holdingWifi = false
        try { cm.unregisterNetworkCallback(holdCallback) } catch (_: IllegalArgumentException) { }
        TimingTrace.emit(TracePoint.WIFI_REQUEST, numeric = 0)
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val stop = PendingIntent.getService(this, 1, Intent(this, javaClass).setAction("stop"), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, "session").setSmallIcon(android.R.drawable.stat_sys_upload_done)
            .setContentTitle("湖南校园网 · 测试版").setContentText(text).setContentIntent(open)
            .addAction(Notification.Action.Builder(null, "停止客户端", stop).build()).setOngoing(true).build()
    }
    private fun update(text: String, id: Long? = null) {
        if (Looper.myLooper() != Looper.getMainLooper()) { mainHandler.post { update(text, id) }; return }
        if (destroyed) return
        if (id != null && generation.get() != id) return
        SessionState.change(id) { it.copy(status = text) }
        SessionState.log(text)
        getSystemService(NotificationManager::class.java).notify(1, notification(text))
    }
    @Synchronized private fun invalidate(): Long {
        TimingTrace.emit(TracePoint.CANCEL)
        val id = generation.incrementAndGet()
        repairGate.resetEvidence()
        SessionState.change { it.copy(generation = id, repairAvailable = false, internetAt = 0, internetResult = CheckResult.UNKNOWN, internetEvidence = InternetEvidence.NOT_CHECKED, heartbeatAt = 0, heartbeatResult = CheckResult.UNKNOWN, nextRecoveryAt = 0, heartbeatDueAt = 0, heartbeatDelayMs = 0, durationMs = 0) }
        pending?.cancel(false)
        if (::wakeupScheduler.isInitialized) wakeupScheduler.cancelAll()
        protocol?.cancel()
        requests.cancel()
        requests = newScope(id)
        protocol = null
        return id
    }
    private fun stopCurrent(id: Long) { mainHandler.post { if (generation.get() == id) stopSelf() } }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (repairInProgress && intent?.action == "start") return START_NOT_STICKY
        if (repairInProgress && intent?.action !in listOf("repair", "start")) cancelRepair()
        when (intent?.action) {
            "repair" -> beginRepair()
            "start" -> {
                val revision = prefs.getLong("configRevision", 0)
                // An active command is idempotent, including discovery and logout waits.
                if (running || loggingOut) return START_NOT_STICKY
                configRevision = revision
                prefs.edit().putBoolean("manualOff", false).commit()
                SessionState.change { it.copy(desired = true, phase = Phase.WAITING_WIFI, error = ErrorKind.NONE, protocolCode = "none", retries = 0) }
                running = true
                holdWifi()
                examinedNetworks.clear()
                val network = cm.allNetworks.firstOrNull { cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }
                if (network == null) update("请先在系统设置中连接校园 Wi-Fi") else activate(network, force = true)
            }
            "logout" -> {
                if (loggingOut) return START_NOT_STICKY
                loggingOut = true
                TimingTrace.emit(TracePoint.CONTROL, reason = StopReason.USER_LOGOUT)
                running = false
                prefs.edit().putBoolean("manualOff", true).commit()
                SessionState.change { it.copy(desired = false, phase = Phase.LOGGING_OUT, nextRecoveryAt = 0, status = "正在请求注销，请等待结果") }
                val old = protocol
                val oldTicket = ticket
                if(oldTicket.isBlank()) { old?.cancel(); requests.cancel() } else old?.beginLogout()
                val id = generation.incrementAndGet()
        SessionState.change { it.copy(generation = id, internetAt = 0, internetResult = CheckResult.UNKNOWN, heartbeatAt = 0, heartbeatResult = CheckResult.UNKNOWN, nextRecoveryAt = 0, heartbeatDueAt = 0, heartbeatDelayMs = 0, durationMs = 0) }
                pending?.cancel(false)
        if (::wakeupScheduler.isInitialized) wakeupScheduler.cancelAll()
                worker.execute {
                    try { check(old != null && oldTicket.isNotBlank()) { "没有可注销的本地会话" }; old.call(4, oldTicket); SessionState.change(id) { it.copy(phase = Phase.LOGGED_OUT) }; update("已注销（服务端确认）", id) }
                    catch (_: Exception) { SessionState.change(id) { it.copy(phase = Phase.LOGOUT_UNCONFIRMED) }; update("注销未确认；客户端已停止", id) }
                    finally { old?.cancel(); stopCurrent(id) }
                }
            }
            else -> {
                TimingTrace.emit(TracePoint.CONTROL, reason = StopReason.USER_STOP)
                running = false
                prefs.edit().putBoolean("manualOff", true).commit()
                SessionState.change { it.copy(desired = false, phase = Phase.STOPPED, nextRecoveryAt = 0) }
                invalidate(); update("客户端已停止，未发送注销请求"); stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun cancelRepair() {
        repairInProgress = false
        repairGate.cancel()
        repairProtocol?.cancel(); repairProtocol = null
        pending?.cancel(false)
        SessionState.change { it.copy(repairing = false, repairAvailable = false) }
    }

    private fun repairCurrent(id: Long, network: Network): Boolean = repairInProgress &&
        generation.get() == id && selected == network && !prefs.getBoolean("manualOff", true)

    private fun failRepair(id: Long, message: String) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            mainHandler.post { failRepair(id, message) }; return
        }
        if (generation.get() != id || !repairInProgress) return
        cancelRepair(); repairGate.fail()
        running = false
        prefs.edit().putBoolean("manualOff", true).commit()
        invalidate()
        SessionState.change { it.copy(desired = false, phase = Phase.NEEDS_INPUT, error = ErrorKind.NETWORK, repairing = false) }
        update(message)
        stopSelf()
    }

    /** Explicit user action. Never retry credentials unless our own logout was confirmed. */
    private fun beginRepair() {
        val network = selected ?: return
        val old = protocol ?: return
        val oldTicket = ticket
        val state = SessionState.snapshot()
        if (!running || repairInProgress || state.phase != Phase.AUTHENTICATED || oldTicket.isBlank() ||
            state.internetEvidence != InternetEvidence.PORTAL_REQUIRED || !repairGate.begin(SystemClock.elapsedRealtime())) return
        repairInProgress = true
        running = false
        pending?.cancel(false)
        wakeupScheduler.cancelAll()
        old.beginLogout()
        repairProtocol = old
        protocol = null; ticket = ""
        val id = generation.incrementAndGet()
        requests = newScope(id)
        SessionState.change { it.copy(generation = id, phase = Phase.REPAIRING, repairing = true,
            repairAvailable = false, heartbeatDueAt = 0, nextRecoveryAt = 0) }
        TimingTrace.emit(TracePoint.CONTROL, id, reason = StopReason.USER_REPAIR)
        update("正在修复：请求服务器注销旧会话；可点停止取消", id)
        worker.execute {
            try {
                if (!repairCurrent(id, network)) return@execute
                old.call(4, oldTicket)
                if (!repairCurrent(id, network) || !repairGate.logoutConfirmed(SystemClock.elapsedRealtime())) return@execute
                mainHandler.post {
                    if (!repairCurrent(id, network)) return@post
                    SessionState.change(id) { it.copy(nextRecoveryAt = System.currentTimeMillis() + SessionRepairGate.WAIT_MS) }
                    update("旧会话已注销；按客户端策略等待 100 秒后登录一次，可点停止取消", id)
                    pending = worker.schedule({
                        mainHandler.post resume@{
                            if (!repairCurrent(id, network)) return@resume
                            val lp = cm.getLinkProperties(network)
                            if (lp == null || NetworkIdentity.key(lp) != fingerprint ||
                                !cm.getNetworkCapabilities(network).let { it?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true }) {
                                failRepair(id, "修复已取消：原 Wi-Fi 不再可用，请手动连接")
                                return@resume
                            }
                            if (!repairGate.takeLogin(SystemClock.elapsedRealtime())) {
                                failRepair(id, "修复等待未完成，已停止；请稍后手动连接")
                                return@resume
                            }
                            IdentityCache.clear(this)
                            running = true
                            update("正在修复：重新登录一次并验证外网", id)
                            activate(network, force = true)
                        }
                    }, SessionRepairGate.WAIT_MS, TimeUnit.MILLISECONDS)
                }
            } catch (_: Exception) {
                failRepair(id, "注销未获确认，已停止修复；没有重新提交账号")
            } finally {
                old.cancel()
                if (repairProtocol === old) repairProtocol = null
            }
        }
    }

    @Synchronized private fun activate(network: Network, force: Boolean = false, lp: LinkProperties? = cm.getLinkProperties(network)) {
        if (!running) return
        val key = lp?.let { NetworkIdentity.key(it) }
        if (key == null) {
            selected = network
            update("等待 Wi-Fi IPv4 和默认网关")
            return
        }
        if (!force && selected == network && fingerprint == key) return
        selected = network
        fingerprint = key
        examinedNetworks.add(network)
        val id = invalidate()
        SessionState.change(id) { it.copy(network = network.toString(), phase = Phase.DISCOVERING, error = ErrorKind.NONE, protocolCode = "none") }
        ticket = ""
        // Coalesce link setup callbacks; no authentication for IPv6/DNS-only changes.
        val scope = requests
        val timing = TimingTrace.plan(TaskKind.AUTH, id, 1)
        pending = worker.schedule({
            TimingTrace.emit(TracePoint.ENTER, id, timing)
            try { authenticate(network, id, scope) } finally { TimingTrace.emit(TracePoint.FINISH, id, timing) }
        }, 1, TimeUnit.SECONDS)
    }
    private fun finishDiscovery(id: Long, evidence: InternetEvidence) {
        if (!alive(id)) return
        TimingTrace.emit(TracePoint.CONTROL, id, reason = StopReason.RETRIES_EXHAUSTED)
        running = false
        prefs.edit().putBoolean("manualOff", true).commit()
        invalidate(); selected = null; fingerprint = ""; ticket = ""
        SessionState.change { it.copy(desired = false, phase = Phase.NEEDS_INPUT, error = ErrorKind.NETWORK) }
        val message = if (evidence == InternetEvidence.HTTPS_VERIFIED)
            "本次 Wi-Fi 外网检测通过，但未发现当前门户；本应用未认证。已停止且未提交账号，请核对校园网会话后手动连接。"
        else "Wi-Fi 已连接，但门户发现重试已用尽，外网未确认可用。已停止且未提交账号；请检查网络后手动连接。"
        update(message)
        stopSelf()
    }
    private fun alive(id: Long) = !destroyed && running && !prefs.getBoolean("manualOff", true) && generation.get() == id
    private fun authenticate(network: Network, id: Long, scope: HttpScope, discoveryAttempt: Int = 0) {
        if (!alive(id)) return
        if (prefs.getLong("configRevision", 0) != configRevision) {
            mainHandler.post { if (alive(id)) networkChanged("连接配置已变化；已停止，请手动连接") }
            return
        }
        var authAccepted = false
        try {
            val lp = cm.getLinkProperties(network) ?: error("网络信息尚未就绪")
            val settings = prefs.all
            fun field(k: String) = (settings[k] as? String).orEmpty().trim()
            val username = field("username")
            val password = Credentials(this).load()
            require(username.isNotBlank() && password.isNotBlank()) { "请填写并保存账号密码" }
            val ip = field("ip").ifBlank { lp.linkAddresses.firstOrNull { it.address is java.net.Inet4Address }?.address?.hostAddress ?: "" }
            val gw = field("gateway").ifBlank { lp.routes.firstOrNull { it.isDefaultRoute && it.gateway is java.net.Inet4Address }?.gateway?.hostAddress ?: "" }
            val configuredPortal = field("portal")
            var mac = field("mac")
            var mscgip = field("mscgip")
            var hint: PortalHint? = null
            if (configuredPortal.isBlank() || mac.isBlank() || mscgip.isBlank()) {
                val cached = IdentityCache.load(this,network,ip,gw)
                hint = if (cached != null && InternetCheck.run(network, scope) { alive(id) }) cached else PortalDiscovery.find(network, ip, scope) { alive(id) }?.also {
                    if (alive(id)) IdentityCache.save(this,network,ip,gw,it)
                }
                if (hint == null && configuredPortal.isBlank()) {
                    if (repairInProgress) {
                        failRepair(id, "修复未完成：未发现当前门户，已停止；请检查网络")
                        return
                    }
                    SessionState.change(id) { it.copy(phase = Phase.DISCOVERING, error = ErrorKind.NETWORK) }
                    update("Wi-Fi 已连接，尚未发现当前门户；正在有限复查，尚未提交账号", id)
                    mainHandler.post {
                        if (alive(id)) {
                            val other = cm.allNetworks.firstOrNull { it !in examinedNetworks && cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true }
                            if(other != null) {
                                selected = null; fingerprint = ""
                                activate(other)
                            } else {
                                val delay = DiscoveryRetryPolicy.delaySeconds(discoveryAttempt + 1)
                                if(delay != null) {
                                    SessionState.log("门户尚未发现，${delay} 秒后有限复查；尚未提交认证")
                                    pending = worker.schedule({ if(alive(id)) authenticate(network, id, scope, discoveryAttempt + 1) }, delay, TimeUnit.SECONDS)
                                } else {
                                    // One bounded check after exhaustion, no new recurring schedule.
                                    pending = worker.schedule({
                                        val evidence = InternetCheck.inspect(network, scope) { alive(id) }
                                        mainHandler.post { finishDiscovery(id, evidence) }
                                    }, 0, TimeUnit.SECONDS)
                                }
                            }
                        }
                    }
                    return
                }
            }
            if (!alive(id)) return
            val portal = configuredPortal.ifBlank { hint?.portal ?: error("门户发现失败；请填写当前网络实际门户，未使用旧地址回退") }
            if (mac.isBlank()) mac = hint?.mac ?: ""
            if (mscgip.isBlank()) mscgip = hint?.mscgip ?: ""
            fun ipv4(s: String) = s.split('.').let { p -> p.size == 4 && p.all { oct -> oct.toIntOrNull()?.let { it in 0..255 } == true } }
            require(ipv4(ip) && ipv4(gw) && ipv4(mscgip)) { "请补齐当前 Wi-Fi IPv4、网关和 mscgip" }
            val hex = mac.replace(":", "").replace("-", "")
            require(hex.matches(Regex("[0-9a-fA-F]{12}")) && hex != "020000000000") { "请填写当前 Wi-Fi MAC（可在系统 Wi-Fi 详情中查看）" }
            val normalized = hex.chunked(2).joinToString("-")
            val uri = URL(portal)
            require(uri.protocol == "http" && uri.userInfo == null && ipv4(uri.host) && uri.port in -1..65535 && uri.port != 0 && uri.query == null && uri.ref == null && uri.path in listOf("", "/")) { "门户格式应为 http://IPv4:端口" }
            SessionState.log("实际认证门户 ${uri.protocol}://${uri.host}:${if(uri.port < 0) 80 else uri.port}；来源：${if (configuredPortal.isNotBlank()) "手动覆盖" else hint?.source}")
            val compatible = field("channel") != "windows"
            val host = field("hostname").ifBlank { "campus-client" }
            require(host.length <= 100 && host.all { it.code in 32..126 }) { "测试版主机名请使用最多 100 个英文字符" }
            val profile = if (compatible) {
                val client = field("clientIdMobile").ifBlank { java.util.UUID.randomUUID().toString().also { prefs.edit().putString("clientIdMobile", it).commit() } }
                WireProfile(userAgent = "CCTP/iOSdy/4023", clientId = client)
            } else WireProfile()
            val details = "门户：$portal（${if (configuredPortal.isBlank()) hint?.source else "手动"}）\n" +
                "IPv4：$ip（${if (field("ip").isBlank()) "Wi-Fi" else "手动"}）\n网关：$gw（${if (field("gateway").isBlank()) "Wi-Fi" else "手动"}）\n" +
                "MAC：$normalized（${if (field("mac").isBlank()) "门户发现" else "手动"}）\nmscgip：$mscgip（${if (field("mscgip").isBlank()) "门户发现" else "手动"}）\n主机名：$host\n通道：${if (compatible) "iOS 兼容" else "旧 Windows"}"
            mainHandler.post { if (generation.get() == id) SessionState.details = details }
            SessionState.change(id) { it.copy(phase = Phase.AUTHENTICATING) }
            val engine = Protocol(network, portal.trimEnd('/'), Identity(ip, normalized, gw, mscgip, host), profile, id, scope)
            if (!alive(id)) { engine.cancel(); return }
            protocol = engine
            if (!alive(id)) { engine.cancel(); return }
            update("正在获取票据", id)
            val newTicket = engine.call(0).fields["ticket"] ?: error("门户未返回票据")
            require(newTicket.isNotBlank()) { "票据为空" }
            update("正在认证", id)
            engine.call(1, newTicket, username, password)
            authAccepted = true
            if (!alive(id)) return
            ticket = newTicket
            engine.call(2, ticket)
            val keep = engine.call(3, ticket)
            if (!alive(id)) return
            failures = 0
            SessionState.change(id) { it.copy(heartbeatAt = System.currentTimeMillis(), heartbeatResult = CheckResult.PASS,
                error = ErrorKind.NONE, protocolCode = "none") }
            scheduleKeep(engine, id, interval(keep, id))
            update("认证端点通过，正在检测 Wi-Fi 外网", id)
            val evidence = InternetCheck.inspect(network, scope) { alive(id) }
            if (alive(id)) {
                SessionState.change(id) { it.copy(phase = Phase.AUTHENTICATED) }
                recordInternet(id, evidence)
                // Recheck delayed gateway release twice without submitting the account again.
                scheduleProbe(network, id, if(evidence == InternetEvidence.HTTPS_VERIFIED) 300 else 10)
            }
        } catch (e: Exception) {
            if (!alive(id)) return
            // No automatic auth loop: do not risk repeated password attempts or kick another device.
            mainHandler.post {
                if (generation.get() == id) {
                    if (repairInProgress) {
                        failRepair(id, "重新登录未完成，已停止修复；没有继续尝试")
                        return@post
                    }
                    running = false; protocol?.cancel()
                    SessionState.change(id) { it.copy(phase = Phase.NEEDS_INPUT, protocolCode = (e as? ProtocolFailure)?.code ?: "none", error = classify(e)) }
                    TimingTrace.emit(TracePoint.CONTROL, id, error = classify(e), numeric = (e as? ProtocolFailure)?.code?.toLongOrNull())
                    val message = when(e) {
                        is java.io.IOException -> "网络请求失败（${e.javaClass.simpleName}）"
                        is java.security.GeneralSecurityException -> "凭据不可用，请重新输入密码"
                        is ProtocolFailure -> "协议未确认（码 ${e.code ?: "缺失"}）；已停止自动尝试"
                        else -> "参数或响应格式异常；请检查设置"
                    }
                    update(if (authAccepted) "登录请求成功，后续会话未确认；请查看诊断" else "连接未完成：$message", id)
                    stopSelf()
                }
            }
        }
    }
    private fun classify(e: Exception): ErrorKind = when(e) {
        is java.security.GeneralSecurityException -> ErrorKind.CREDENTIAL_STORAGE
        is ProtocolFailure -> ErrorKind.PROTOCOL
        is java.io.IOException -> if(getSystemService(android.os.PowerManager::class.java).isDeviceIdleMode) ErrorKind.IDLE_WAIT else ErrorKind.NETWORK
        else -> if(protocol == null) ErrorKind.CONFIGURATION else ErrorKind.PROTOCOL
    }
    private fun interval(result: EndpointResult, id: Long): Long {
        val decision = IntervalPolicy.select(result.fields["interval"])
        TimingTrace.emit(TracePoint.INTERVAL, id, kind = TaskKind.HEARTBEAT, numeric = decision.rawValid, source = decision.source)
        SessionState.change(id) { it.copy(heartbeatIntervalSeconds = decision.seconds) }
        return decision.seconds
    }
    @Synchronized private fun scheduleKeep(engine: Protocol, id: Long, seconds: Long) {
        if (!alive(id)) return
        val timing = TimingTrace.plan(TaskKind.HEARTBEAT, id, seconds)
        val due = timing.dueWall
        SessionState.change(id) { it.copy(heartbeatDueAt = due, nextRecoveryAt = if (failures > 0) due else 0) }
        wakeupScheduler.schedule(timing, id, seconds) {
            if (!alive(id)) return@schedule
            TimingTrace.emit(TracePoint.ENTER, id, timing)
            val started = SystemClock.elapsedRealtime()
            try {
                val result = engine.call(3, ticket)
                if (!alive(id)) return@schedule
                failures = 0
                SessionState.change(id) { it.copy(phase = Phase.AUTHENTICATED, heartbeatAt = System.currentTimeMillis(), heartbeatResult = CheckResult.PASS,
                    error = ErrorKind.NONE, protocolCode = "none", retries = 0, nextRecoveryAt = 0, heartbeatDelayMs = maxOf(0, System.currentTimeMillis() - due), durationMs = SystemClock.elapsedRealtime() - started) }
                TimingTrace.emit(TracePoint.FINISH, id, timing)
                scheduleKeep(engine, id, interval(result, id))
            } catch (e: Exception) {
                if (!alive(id)) return@schedule
                TimingTrace.emit(TracePoint.FINISH, id, timing, error = classify(e), numeric = (e as? ProtocolFailure)?.code?.toLongOrNull())
                failures++
                val delay = RetryPolicy.delaySeconds(failures)
                SessionState.change(id) { it.copy(phase = Phase.RECOVERING, heartbeatAt = System.currentTimeMillis(), heartbeatResult = CheckResult.FAIL,
                    error = classify(e), protocolCode = (e as? ProtocolFailure)?.code ?: "none", retries = failures, durationMs = SystemClock.elapsedRealtime() - started) }
                if (delay == null) {
                    mainHandler.post { if (alive(id)) { running = false; SessionState.change(id) { it.copy(phase = Phase.NEEDS_INPUT, nextRecoveryAt = 0) }; update("连续心跳失败，已停止；请检查网络后手动重连", id); stopSelf() } }
                } else { update("心跳暂未确认，保留会话并退避重试", id); scheduleKeep(engine, id, delay) }
            }
        }
    }
    private fun recordInternet(id: Long, evidence: InternetEvidence) {
        if (!alive(id)) return
        repairGate.observe(evidence, SystemClock.elapsedRealtime())
        val repaired = repairInProgress && repairGate.stage == SessionRepairGate.Stage.LOGIN && evidence == InternetEvidence.HTTPS_VERIFIED
        if (repaired) { repairGate.complete(); repairInProgress = false }
        SessionState.change(id) { it.copy(internetAt = System.currentTimeMillis(),
            internetResult = if(evidence == InternetEvidence.HTTPS_VERIFIED) CheckResult.PASS else CheckResult.FAIL,
            internetEvidence = evidence, repairing = repairInProgress,
            repairAvailable = !repairInProgress && repairGate.available(SystemClock.elapsedRealtime()),
            phase = if(repairInProgress) Phase.REPAIRING else Phase.AUTHENTICATED,
            nextRecoveryAt = if(repaired) 0 else it.nextRecoveryAt) }
        update(if(repaired) "修复完成，Wi-Fi 外网检测通过" else if(repairInProgress) "新会话已建立，等待网关放行；最多再复查两次" else "认证接口已接受 · 外网结果已更新", id)
    }
    private fun scheduleProbe(network: Network, id: Long, seconds: Long = 300, attempt: Int = 0) {
        if (!alive(id)) return
        val scope = requests
        val timing = TimingTrace.plan(TaskKind.INTERNET, id, seconds)
        val task: () -> Unit = probe@{
            if (!alive(id)) return@probe
            TimingTrace.emit(TracePoint.ENTER, id, timing)
            val evidence = InternetCheck.inspect(network, scope) { alive(id) }
            TimingTrace.emit(TracePoint.FINISH, id, timing)
            if (!alive(id)) return@probe
            recordInternet(id, evidence)
            if (repairInProgress && seconds < 300 && attempt == 1 && evidence != InternetEvidence.HTTPS_VERIFIED) {
                failRepair(id, "重新登录后仍未确认外网，已停止修复；请检查校园网或使用官方客户端核对")
                return@probe
            }
            if (seconds < 300 && attempt == 0 && evidence != InternetEvidence.HTTPS_VERIFIED) scheduleProbe(network, id, 30, 1)
            else scheduleProbe(network, id)
        }
        if(seconds < 300) pending = worker.schedule(task, seconds, TimeUnit.SECONDS)
        else wakeupScheduler.schedule(timing, id, seconds, task)
    }
    override fun onDestroy() {
        destroyed = true
        val wasActive = running || repairInProgress
        if (repairInProgress) cancelRepair()
        instancesDestroyed.incrementAndGet()
        TimingTrace.emit(TracePoint.CONTROL, reason = StopReason.SERVICE_DESTROYED)
        if (wasActive) SessionState.change { it.copy(phase = Phase.INTERRUPTED, error = ErrorKind.PROCESS_INTERRUPTED, repairing = false, status = "连接服务已结束；请手动连接") }
        running = false; invalidate(); requests.close()
        cm.unregisterNetworkCallback(callback)
        releaseWifi()
        worker.shutdownNow()
        mainHandler.removeCallbacksAndMessages(null)
        stopForeground(STOP_FOREGROUND_REMOVE)
        super.onDestroy()
    }
    override fun onBind(intent: Intent?): IBinder? = null
}





