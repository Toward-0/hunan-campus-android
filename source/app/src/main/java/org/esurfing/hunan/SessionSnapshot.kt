package org.esurfing.hunan

enum class Phase { IDLE, WAITING_WIFI, DISCOVERING, LOGGING_OUT, AUTHENTICATING, AUTHENTICATED, RECOVERING, NEEDS_INPUT, STOPPED, LOGGED_OUT, LOGOUT_UNCONFIRMED, INTERRUPTED, REPAIRING }
enum class CheckResult { UNKNOWN, PASS, FAIL }
enum class InternetEvidence { NOT_CHECKED, HTTPS_VERIFIED, PORTAL_REQUIRED, HTTPS_UNREACHABLE }
enum class ErrorKind { NONE, NETWORK, PROTOCOL, CREDENTIAL_STORAGE, CONFIGURATION, HEARTBEAT, PROCESS_INTERRUPTED, IDLE_WAIT }
enum class SchedulerMode { TIMER, EXACT_LISTENER, INEXACT_LISTENER, TIMER_FALLBACK, EXACT_IDLE_PENDING, INEXACT_IDLE_PENDING, EXACT_IDLE_WITH_TIMER, INEXACT_IDLE_WITH_TIMER }

data class SessionSnapshot(
    val desired: Boolean = false,
    val generation: Long = 0,
    val network: String = "none",
    val phase: Phase = Phase.IDLE,
    val status: String = "尚未连接",
    val details: String = "尚未建立会话；参数来源将在登录时显示。",
    val heartbeatAt: Long = 0,
    val heartbeatResult: CheckResult = CheckResult.UNKNOWN,
    val internetAt: Long = 0,
    val internetResult: CheckResult = CheckResult.UNKNOWN,
    val internetEvidence: InternetEvidence = InternetEvidence.NOT_CHECKED,
    val error: ErrorKind = ErrorKind.NONE,
    val retries: Int = 0,
    val nextRecoveryAt: Long = 0,
    val heartbeatDueAt: Long = 0,
    val heartbeatDelayMs: Long = 0,
    val durationMs: Long = 0,
    val protocolCode: String = "none",
    val heartbeatIntervalSeconds: Long = 250,
    val schedulerMode: SchedulerMode = SchedulerMode.TIMER,
    val repairAvailable: Boolean = false,
    val repairing: Boolean = false
) {
    /** Shared UI guard; apply before any settings or encrypted credential write. */
    fun configurationBlocked(): Boolean = repairing || phase in listOf(
        Phase.WAITING_WIFI, Phase.DISCOVERING, Phase.AUTHENTICATING,
        Phase.AUTHENTICATED, Phase.RECOVERING, Phase.REPAIRING, Phase.LOGGING_OUT)
    fun configurationBlockMessage(): String = when {
        repairing || phase == Phase.REPAIRING -> "请先取消修复并停止，再保存账号；输入内容已保留。"
        phase == Phase.LOGGING_OUT -> "正在注销，请等待结果后再保存账号；输入内容已保留。"
        phase == Phase.AUTHENTICATED || phase == Phase.RECOVERING -> "当前会话仍在运行。切换账号前请在“更多”手动注销并等待结果；输入内容已保留。"
        else -> "当前连接尚未结束，请先在“连接”页停止，再保存账号；输入内容已保留。"
    }
    fun display(now: Long): String {
        val fresh = internetAt > 0 && now - internetAt in 0..600_000
        val online = if (phase == Phase.AUTHENTICATED) {
            if (!fresh) "认证接口已接受 · 外网待复核" else if (internetResult == CheckResult.PASS) "已认证 · 最近外网检测通过" else when(internetEvidence) {
                InternetEvidence.PORTAL_REQUIRED -> "认证接口已接受 · 校园网仍要求登录（外网未放行）"
                InternetEvidence.HTTPS_UNREACHABLE -> "认证接口已接受 · HTTPS 外网异常或待确认"
                else -> "认证接口已接受 · 外网异常或待确认"
            }
        } else status
        val heartFresh = heartbeatAt > 0 && now - heartbeatAt in 0..(heartbeatIntervalSeconds * 1000 + 60000)
        val scheduling = if(schedulerMode in listOf(SchedulerMode.INEXACT_LISTENER, SchedulerMode.TIMER_FALLBACK, SchedulerMode.INEXACT_IDLE_PENDING, SchedulerMode.INEXACT_IDLE_WITH_TIMER)) "后台调度已降级，保活时效未保证" else "后台调度仍需验收"
        val repairHint = if(repairAvailable) "\n持续未放行，可点“一键修复连接”。" else ""
        return "$online\n最近外网检测：${if (internetAt == 0L) "尚无" else java.util.Date(internetAt)}\n心跳最近完成：${if (heartbeatAt == 0L) "尚无" else java.util.Date(heartbeatAt)}\n心跳：$heartbeatResult（${if (heartFresh) "最近结果" else "已过期或未确认"}）；恢复次数：$retries\n$scheduling$repairHint"
    }
    // Export only typed fields. Status/details and raw exception strings never cross this boundary.
    fun event(now: Long): String = listOf(now, desired, generation, network.filter { it.isDigit() }.take(20).ifEmpty { "none" }, phase, heartbeatAt,
        heartbeatResult, internetAt, internetResult, error, retries, nextRecoveryAt, heartbeatDueAt, heartbeatDelayMs, durationMs,
        protocolCode.takeIf { it.matches(Regex("-?[0-9]{1,10}")) } ?: "none", internetEvidence).joinToString("\t")
}

object RetryPolicy {
    fun delaySeconds(failures: Int): Long? = when (failures) { 1 -> 15; 2 -> 30; else -> null }
}

object DiscoveryRetryPolicy {
    fun delaySeconds(attempt: Int): Long? = when(attempt) { 1 -> 10; 2 -> 30; else -> null }
}

enum class IntervalSource { SERVER, MISSING, INVALID_NUMBER, OUT_OF_RANGE }
data class IntervalDecision(val seconds: Long, val rawValid: Long?, val source: IntervalSource)
object IntervalPolicy {
    fun select(raw: String?): IntervalDecision {
        val n = raw?.toLongOrNull()
        val source = when { raw == null -> IntervalSource.MISSING; n == null -> IntervalSource.INVALID_NUMBER; n !in 30..3600 -> IntervalSource.OUT_OF_RANGE; else -> IntervalSource.SERVER }
        return IntervalDecision(if (source == IntervalSource.SERVER) maxOf(15, n!! * 5 / 6) else 250, n?.takeIf { it in 30..3600 }, source)
    }
}


