package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Process
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/** One-second diagnostic alarms test cancellation only; they are not protocol heartbeat intervals. */
class AlarmProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val worker = Executors.newSingleThreadScheduledExecutor()
        var scheduler: WakeupScheduler? = null
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            SessionState.initialize(ctx)
            val generation = AtomicLong(0)
            val calls = AtomicInteger()
            val current = WakeupScheduler(ctx, worker) { generation.get() == it }
            scheduler = current
            val fired = CountDownLatch(1)
            current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, 0, 1), 0, 1) { calls.incrementAndGet(); fired.countDown() }
            check(fired.await(15, TimeUnit.SECONDS))
            current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, 0, 1), 0, 1) { calls.incrementAndGet() }
            generation.incrementAndGet()
            current.cancelAll()
            Thread.sleep(6500)
            check(calls.get() == 1)
            val entered = CountDownLatch(1)
            val unblock = CountDownLatch(1)
            worker.execute { entered.countDown(); unblock.await(25, TimeUnit.SECONDS) }
            check(entered.await(1, TimeUnit.SECONDS))
            val timing = TimingTrace.plan(TaskKind.HEARTBEAT, 1, 1)
            current.schedule(timing, 1, 1) { calls.incrementAndGet() }
            var delivered = false
            val deadline = android.os.SystemClock.elapsedRealtime() + 15000
            while(!delivered && android.os.SystemClock.elapsedRealtime() < deadline) {
                delivered = TimingTrace.export().lineSequence().filter { it.startsWith("{") }.map { org.json.JSONObject(it) }
                    .any { it.optString("point") == "ALARM_DELIVERY" && it.optLong("task") == timing.number }
                if(!delivered) Thread.sleep(200)
            }
            check(delivered)
            generation.incrementAndGet()
            current.cancelAll()
            unblock.countDown()
            Thread.sleep(500)
            check(calls.get() == 1)
            val racers = Executors.newFixedThreadPool(2)
            try {
                repeat(200) {
                    val id = generation.get()
                    val go = CountDownLatch(1)
                    val scheduled = racers.submit { go.await(); current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, id, 3600), id, 3600) { calls.incrementAndGet() } }
                    val cancelled = racers.submit { go.await(); generation.incrementAndGet(); current.cancelAll() }
                    go.countDown(); scheduled.get(5, TimeUnit.SECONDS); cancelled.get(5, TimeUnit.SECONDS)
                    check(WakeupDispatch.size() == 0)
                }
            } finally { racers.shutdownNow() }
            check(calls.get() == 1)
            finish(-1, Bundle().apply { putString("result", "PASS: alarm delivery; cancellation before delivery and before worker execution; 200 concurrent schedule/cancel races leave zero callbacks; diagnostic seconds are not heartbeat semantics") })
        } catch(t: Throwable) {
            finish(0, Bundle().apply { putString("result", "FAIL: ${t.javaClass.simpleName}; line=${t.stackTrace.firstOrNull { it.fileName == "AlarmProbe.kt" }?.lineNumber}") })
        } finally { scheduler?.cancelAll(); worker.shutdownNow() }
    }
}

