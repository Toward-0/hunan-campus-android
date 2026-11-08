package org.esurfing.hunan

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.*
import org.json.JSONObject
import java.io.File
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

enum class TracePoint { PROCESS_START, EXIT_HISTORY, PLAN, ENTER, FINISH, REQUEST_START, REQUEST_FINISH, CANCEL, CONTROL, INTERVAL, ALARM_DELIVERY, SCHEDULER, WIFI_REQUEST, DISCOVERY }
enum class TaskKind { NONE, AUTH, HEARTBEAT, INTERNET, MODULE, TICKET, LOGIN, STATE, LOGOUT, INITIAL_HEARTBEAT }
enum class StopReason { NONE, USER_STOP, USER_LOGOUT, NETWORK_LOST, REPLACED, SERVICE_DESTROYED, RETRIES_EXHAUSTED, USER_REPAIR }
data class TaskTiming(val number: Long, val kind: TaskKind, val dueWall: Long, val dueElapsed: Long, val dueUptime: Long)

/** Fixed schema only: never accepts exception text, URLs, identities, response bodies or credentials. */
object TimingTrace {
    private val instance = UUID.randomUUID().toString().take(8)
    private val sequence = AtomicLong()
    private var context: Context? = null
    private var directory: File? = null
    private var versionName = "unknown"
    private var versionCode = 0L
    @Synchronized fun initialize(ctx: Context) {
        if (context != null) return
        context = ctx.applicationContext
        try {
            @Suppress("DEPRECATION")
            val installed = ctx.packageManager.getPackageInfo(ctx.packageName, 0)
            versionName = installed.versionName ?: "unknown"
            @Suppress("DEPRECATION")
            versionCode = if (Build.VERSION.SDK_INT >= 28) installed.longVersionCode else installed.versionCode.toLong()
        } catch (_: android.content.pm.PackageManager.NameNotFoundException) { /* Metadata remains explicitly unknown. */ }
          catch (_: RuntimeException) { /* Diagnostics cannot prevent a connection. */ }
        directory = File(ctx.noBackupFilesDir, "timing-v2").apply { mkdirs() }
        emit(TracePoint.PROCESS_START)
        if (Build.VERSION.SDK_INT >= 30) try {
            ctx.getSystemService(ActivityManager::class.java).getHistoricalProcessExitReasons(null, 0, 3).forEach {
                emit(TracePoint.EXIT_HISTORY, numeric = it.reason.toLong(), historicalTime = it.timestamp)
            }
        } catch (_: RuntimeException) { /* Not available on every device. */ }
    }
    fun plan(kind: TaskKind, generation: Long, seconds: Long): TaskTiming {
        val delay = seconds * 1000
        val timing = TaskTiming(sequence.incrementAndGet(), kind, System.currentTimeMillis()+delay, SystemClock.elapsedRealtime()+delay, SystemClock.uptimeMillis()+delay)
        emit(TracePoint.PLAN, generation, timing)
        return timing
    }
    @Synchronized fun emit(point: TracePoint, generation: Long = SessionState.snapshot().generation,
        task: TaskTiming? = null, kind: TaskKind = task?.kind ?: TaskKind.NONE,
        error: ErrorKind = ErrorKind.NONE, reason: StopReason = StopReason.NONE,
        numeric: Long? = null, source: IntervalSource? = null, historicalTime: Long? = null, mode: SchedulerMode? = null,
        discovery: DiscoveryReason? = null, probe: Int? = null, httpCode: Int? = null) {
        val ctx = context ?: return
        val dir = directory ?: return
        try {
            val wall = System.currentTimeMillis()
            val elapsed = SystemClock.elapsedRealtime()
            val uptime = SystemClock.uptimeMillis()
            val nano = System.nanoTime()
            val state = SessionState.snapshot()
            val pm = ctx.getSystemService(PowerManager::class.java)
            val battery = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val row = JSONObject().put("schema", 2).put("process", instance).put("pid", Process.myPid())
                .put("wall", wall).put("elapsed", elapsed)
                .put("uptime", uptime).put("nano", nano).put("tid", Process.myTid())
                .put("point", point.name).put("kind", kind.name).put("generation", generation)
                .put("network", state.network.filter { it.isDigit() }.take(20).ifEmpty { "none" })
                .put("desired", state.desired).put("phase", state.phase.name).put("retries", state.retries)
                .put("internetEvidence", state.internetEvidence.name)
                .put("error", error.name).put("stop", reason.name).put("interactive", pm.isInteractive)
                .put("idle", pm.isDeviceIdleMode).put("lightIdle", if(Build.VERSION.SDK_INT >= 33) pm.isDeviceLightIdleMode else JSONObject.NULL)
                .put("plugged", battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) ?: -1)
                .put("battery", battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1)
                .put("temperatureDeciC", battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1) ?: -1)
            if (task != null) row.put("task", task.number).put("dueWall", task.dueWall).put("dueElapsed", task.dueElapsed).put("dueUptime", task.dueUptime)
            if (numeric != null) row.put("number", numeric)
            if (source != null) row.put("intervalSource", source.name)
            if (mode != null) row.put("schedulerMode", mode.name)
            if (historicalTime != null) row.put("historicalWall", historicalTime)
            if (discovery != null) row.put("discoveryReason", discovery.name)
            if (probe != null && probe in 0..2) row.put("discoveryProbe", probe)
            if (httpCode != null && httpCode in 100..599) row.put("httpCode", httpCode)
            row.put("sampleCostMs", SystemClock.elapsedRealtime() - elapsed)
            val file = File(dir, "trace.jsonl")
            if (file.length() >= 65_536) {
                val previous = File(dir, "trace.previous.jsonl")
                previous.delete()
                if (!file.renameTo(previous)) return
            }
            file.appendText(row.toString()+"\n")
        } catch (_: Exception) { /* Diagnostics must never break a session. */ }
    }
    @Synchronized fun export(): String {
        val dir = directory
        return DiagnosticJsonl.export(versionName, versionCode) { name ->
            dir?.let { File(it, name) }?.takeIf { it.isFile }?.readText()
        }
    }
}
