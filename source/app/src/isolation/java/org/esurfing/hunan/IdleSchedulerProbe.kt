package org.esurfing.hunan

import android.app.*
import android.content.Intent
import android.os.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit

/** Synthetic timers only: no credentials, protocol, Wi-Fi changes or network requests. */
class IdleProbeService : Service() {
    override fun onBind(intent: Intent?) = null
    override fun onCreate() {
        super.onCreate()
        check(packageName == "org.esurfing.hunan.isolation")
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("idle-probe", "隔离锁屏调度测试", NotificationManager.IMPORTANCE_LOW))
        startForeground(90, Notification.Builder(this, "idle-probe")
            .setSmallIcon(android.R.drawable.stat_notify_sync).setContentTitle("隔离调度测试 · 无校园网请求").build())
    }
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int) = START_NOT_STICKY
}

class IdleSchedulerProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val ctx = targetContext
        val worker = ScheduledThreadPoolExecutor(1).apply { removeOnCancelPolicy = true }
        var active = true
        val scheduler = WakeupScheduler(ctx, worker) { active }
        val samples = JSONArray()
        val result = JSONObject().put("testId", "FORCED-IDLE-SCHEDULER").put("samples", samples)
            .put("api", Build.VERSION.SDK_INT).put("status", "FAIL")
        try {
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            SessionState.initialize(ctx)
            ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            ctx.startForegroundService(Intent(ctx, IdleProbeService::class.java))
            val pm = ctx.getSystemService(PowerManager::class.java)
            val am = ctx.getSystemService(AlarmManager::class.java)
            result.put("batteryExempt", pm.isIgnoringBatteryOptimizations(ctx.packageName))
                .put("exactAllowed", Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms())
            sendStatus(1, Bundle().apply { putString("result", "READY_FOR_IDLE") })
            // The host forces idle after READY, restores it in a finally block.
            Thread.sleep(12000)
            repeat(3) {
                val finished = CountDownLatch(1)
                val timing = TimingTrace.plan(TaskKind.HEARTBEAT, 0, 30)
                scheduler.schedule(timing, 0, 30) {
                    samples.put(JSONObject().put("delayMs", (SystemClock.elapsedRealtime()-timing.dueElapsed).coerceAtLeast(0))
                        .put("idle", pm.isDeviceIdleMode).put("interactive", pm.isInteractive))
                    finished.countDown()
                }
                check(finished.await(75, TimeUnit.SECONDS))
            }
            check(samples.length() == 3)
            repeat(samples.length()) { check(samples.getJSONObject(it).getBoolean("idle")); check(samples.getJSONObject(it).getLong("delayMs") <= 3000) }
            result.put("status", "PASS")
        } catch (t: Throwable) {
            result.put("exception", t.javaClass.simpleName)
        } finally {
            active = false
            scheduler.cancelAll(); worker.shutdownNow()
            ctx.stopService(Intent(ctx, IdleProbeService::class.java))
            result.put("callbacksAfter", WakeupDispatch.size())
            File(ctx.filesDir, "idle-scheduler.json").writeText(result.toString())
            finish(if(result.optString("status") == "PASS") -1 else 0, Bundle().apply { putString("result", result.toString()) })
        }
    }
}
