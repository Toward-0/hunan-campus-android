package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/** Synthetic scheduler callbacks only; no protocol requests or production credentials. */
class AlarmProbe : Instrumentation() {
    private class RecordingWorker : ScheduledThreadPoolExecutor(1) {
        @Volatile var lastTimer: Runnable? = null
        init { removeOnCancelPolicy = true }
        override fun schedule(command: Runnable, delay: Long, unit: TimeUnit): ScheduledFuture<*> {
            if(delay > 0) lastTimer = command
            return super.schedule(command, delay, unit)
        }
        fun drain() {
            val drained = CountDownLatch(1)
            execute { drained.countDown() }
            check(drained.await(5, TimeUnit.SECONDS))
        }
    }
    /** Capture the callback to simulate a broadcast already in flight, with no main-package hook. */
    @Suppress("UNCHECKED_CAST")
    private fun alarm(current: WakeupScheduler): () -> Unit {
        val tickets = current.javaClass.getDeclaredField("tokens").apply { isAccessible = true }.get(current) as Map<*, *>
        val ticket = checkNotNull(tickets[TaskKind.HEARTBEAT])
        val nonce = ticket.javaClass.getDeclaredField("nonce").apply { isAccessible = true }.get(ticket) as String
        val callbacks = WakeupDispatch.javaClass.getDeclaredField("callbacks").apply { isAccessible = true }
            .get(WakeupDispatch) as Map<String, () -> Unit>
        return checkNotNull(callbacks[nonce])
    }
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val worker = RecordingWorker()
        var scheduler: WakeupScheduler? = null
        val unblock = CountDownLatch(1)
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            // Truth table: an installed alarm is preserved only for a non-exempt idle timer.
            // In particular, a failed alarm registration must leave the timer fallback usable.
            val deferred = mutableSetOf<String>()
            var policyCases = 0
            for(origin in listOf(TracePoint.ALARM_DELIVERY, TracePoint.TIMER_DELIVERY))
                for(installed in listOf(false, true)) for(idle in listOf(false, true)) for(exempt in listOf(false, true)) {
                    if(IdleDeliveryPolicy.deferToAlarm(origin, installed, idle, exempt))
                        deferred.add("${origin.name}:$installed:$idle:$exempt")
                    policyCases++
                }
            check(policyCases == 16 && deferred == setOf("TIMER_DELIVERY:true:true:false"))
            for(origin in TracePoint.entries.filter { it != TracePoint.TIMER_DELIVERY })
                check(!IdleDeliveryPolicy.deferToAlarm(origin, true, true, false))
            ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            SessionState.initialize(ctx)
            val generation = AtomicLong(0)
            val calls = AtomicInteger()
            val current = WakeupScheduler(ctx, worker) { generation.get() == it }
            scheduler = current
            val fired = CountDownLatch(1)
            val first = TimingTrace.plan(TaskKind.HEARTBEAT, 0, 1)
            val latency = AtomicLong(-1)
            current.schedule(first, 0, 1) { latency.set(SystemClock.elapsedRealtime() - first.dueElapsed); calls.incrementAndGet(); fired.countDown() }
            check(fired.await(4, TimeUnit.SECONDS))
            check(latency.get() in 0..3000)
            worker.drain()
            check(calls.get() == 1 && WakeupDispatch.size() == 0)

            // Cancellation before either trigger; even already-captured callbacks are inert.
            current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, 0, 3600), 0, 3600) { calls.incrementAndGet() }
            val cancelledAlarm = alarm(current)
            val cancelledTimer = checkNotNull(worker.lastTimer)
            generation.incrementAndGet()
            current.cancelAll()
            cancelledAlarm(); cancelledTimer.run(); worker.drain()
            check(calls.get() == 1)

            // A delivered task may still be queued behind other work when Stop is pressed.
            val entered = CountDownLatch(1)
            worker.execute { entered.countDown(); unblock.await(25, TimeUnit.SECONDS) }
            check(entered.await(1, TimeUnit.SECONDS))
            current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, 1, 3600), 1, 3600) { calls.incrementAndGet() }
            alarm(current).invoke()
            generation.incrementAndGet()
            current.cancelAll()
            unblock.countDown()
            worker.drain()
            check(calls.get() == 1)

            val racers = Executors.newFixedThreadPool(2)
            try {
                // Both delivery closures have already escaped their platform queues.
                // Race and replay them: only one worker task is permitted each time.
                repeat(100) { index ->
                    val id = generation.get()
                    current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, id, 3600), id, 3600) { calls.incrementAndGet() }
                    val broadcast = alarm(current)
                    val timer = checkNotNull(worker.lastTimer)
                    val go = CountDownLatch(1)
                    val a = racers.submit { go.await(); broadcast() }
                    val b = racers.submit { go.await(); timer.run() }
                    go.countDown(); a.get(5, TimeUnit.SECONDS); b.get(5, TimeUnit.SECONDS)
                    broadcast(); timer.run(); worker.drain()
                    check(calls.get() == index + 2)
                    check(WakeupDispatch.size() == 0)
                }

                val id = generation.get()
                current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, id, 3600), id, 3600) { calls.incrementAndGet() }
                val replacedAlarm = alarm(current)
                val replacedTimer = checkNotNull(worker.lastTimer)
                current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, id, 3600), id, 3600) { calls.incrementAndGet() }
                replacedAlarm(); replacedTimer.run(); alarm(current).invoke(); worker.drain()
                check(calls.get() == 102 && WakeupDispatch.size() == 0)

                repeat(200) {
                    val id = generation.get()
                    val go = CountDownLatch(1)
                    val scheduled = racers.submit { go.await(); current.schedule(TimingTrace.plan(TaskKind.HEARTBEAT, id, 3600), id, 3600) { calls.incrementAndGet() } }
                    val cancelled = racers.submit { go.await(); generation.incrementAndGet(); current.cancelAll() }
                    go.countDown(); scheduled.get(5, TimeUnit.SECONDS); cancelled.get(5, TimeUnit.SECONDS)
                    check(WakeupDispatch.size() == 0)
                }
            } finally { racers.shutdownNow() }
            worker.drain()
            check(calls.get() == 102)
            check(worker.queue.isEmpty())
            finish(-1, Bundle().apply { putString("result", "PASS: 16 idle-delivery policy combinations; awake delivery lateness=${latency.get()}ms <=3000ms; 100 dual-trigger races/replays execute once; cancel before delivery/queued execution and replacement; 200 schedule/cancel races; zero callbacks/queued timers; synthetic callbacks are not Doze or protocol validation") })
        } catch(t: Throwable) {
            finish(0, Bundle().apply { putString("result", "FAIL: ${t.javaClass.simpleName}; line=${t.stackTrace.firstOrNull { it.fileName == "AlarmProbe.kt" }?.lineNumber}") })
        } finally { unblock.countDown(); scheduler?.cancelAll(); worker.shutdownNow() }
    }
}

