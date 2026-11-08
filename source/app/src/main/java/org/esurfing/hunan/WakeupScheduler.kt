package org.esurfing.hunan

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
import android.os.SystemClock
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** An alarm without a live session callback cannot log in or start a service. */
object WakeupDispatch {
    private val callbacks = ConcurrentHashMap<String, () -> Unit>()
    fun register(token: String, callback: () -> Unit) { callbacks[token] = callback }
    fun cancel(token: String) { callbacks.remove(token) }
    fun deliver(token: String) { callbacks.remove(token)?.invoke() }
    fun size() = callbacks.size
}
class WakeupReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if(intent.action != "org.esurfing.hunan.WAKE_TASK") return
        val token = intent.getStringExtra("token") ?: return
        if(!token.matches(Regex("[0-9a-f-]{36}"))) return
        SessionState.initialize(context)
        WakeupDispatch.deliver(token)
    }
}

/** An idle alarm grants a temporary execution window that an ordinary timer cannot supply. */
internal object IdleDeliveryPolicy {
    fun deferToAlarm(origin: TracePoint, alarmInstalled: Boolean, idle: Boolean, batteryExempt: Boolean): Boolean =
        origin == TracePoint.TIMER_DELIVERY && alarmInstalled && idle && !batteryExempt
}

/** Explicit capability checks; bounded request wake lock; no boot receiver or automatic authentication. */
class WakeupScheduler(context: Context, private val worker: ScheduledExecutorService, private val alive: (Long) -> Boolean) {
    private val app = context.applicationContext
    private val alarms = app.getSystemService(AlarmManager::class.java)
    private val power = app.getSystemService(PowerManager::class.java)
    private val tokens = ConcurrentHashMap<TaskKind, Ticket>()
    private inner class Ticket(val timing: TaskTiming, val generation: Long) {
        val nonce = UUID.randomUUID().toString()
        val cancelled = AtomicBoolean()
        val delivered = AtomicBoolean()
        // Accessed only under the scheduler lock; a PendingIntent alone is not proof of registration.
        var alarmInstalled = false
        var pending: PendingIntent? = null
        var future: ScheduledFuture<*>? = null
        @Volatile var wake: PowerManager.WakeLock? = null
        fun release() { val lock = wake; if(lock != null) synchronized(lock) { if(lock.isHeld) lock.release() } }
        fun cancelTriggers() {
            WakeupDispatch.cancel(nonce)
            pending?.let {
                // OEM alarm services can disappear or reject cancellation. The local
                // callback/claim guards still make any late broadcast harmless.
                try { alarms.cancel(it) } catch (_: RuntimeException) { }
                try { it.cancel() } catch (_: RuntimeException) { }
            }
            future?.cancel(false)
        }
        fun cancel() {
            cancelled.set(true)
            cancelTriggers()
            release()
        }
    }
    @Synchronized fun cancelAll() {
        tokens.values.toList().forEach { if(tokens.remove(it.timing.kind, it)) it.cancel() }
    }
    @Synchronized fun schedule(timing: TaskTiming, generation: Long, seconds: Long, task: () -> Unit) {
        if(!alive(generation)) return
        val ticket = Ticket(timing, generation)
        tokens.put(timing.kind, ticket)?.cancel()
        fun deliver(point: TracePoint) {
            // Installation, replacement, cancellation and claiming share this lock.
            // A timer and an already-in-flight broadcast must never run two requests.
            synchronized(this@WakeupScheduler) {
                if(ticket.cancelled.get() || !alive(generation)) return
                if(point == TracePoint.TIMER_DELIVERY && ticket.alarmInstalled) {
                    val defer = try {
                        IdleDeliveryPolicy.deferToAlarm(point, ticket.alarmInstalled,
                            power.isDeviceIdleMode, power.isIgnoringBatteryOptimizations(app.packageName))
                    } catch (_: RuntimeException) {
                        // If an OEM capability query fails, preserve the registered wake-up path.
                        true
                    }
                    // Another app may briefly wake the CPU during Doze. Consuming our alarm
                    // here would discard its execution window while our network is restricted.
                    if(defer) return
                }
                if(!ticket.delivered.compareAndSet(false, true)) return
                ticket.cancelTriggers()
            }
            TimingTrace.emit(point, generation, timing)
            try {
                val lock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ESurfing:request")
                lock.setReferenceCounted(false)
                synchronized(lock) { ticket.wake = lock; if(!ticket.cancelled.get()) lock.acquire(60_000) }
                worker.execute {
                    try { if(!ticket.cancelled.get() && alive(generation)) task() }
                    finally { ticket.release(); tokens.remove(timing.kind, ticket) }
                }
            } catch (_: RuntimeException) {
                ticket.release(); tokens.remove(timing.kind, ticket)
                TimingTrace.emit(TracePoint.FINISH, generation, timing, error = ErrorKind.NETWORK)
            }
        }
        WakeupDispatch.register(ticket.nonce) { deliver(TracePoint.ALARM_DELIVERY) }
        var exact = false
        var mode = SchedulerMode.TIMER_FALLBACK
        try {
            val intent = Intent(app, WakeupReceiver::class.java).setAction("org.esurfing.hunan.WAKE_TASK").putExtra("token", ticket.nonce)
            ticket.pending = PendingIntent.getBroadcast(app, timing.kind.ordinal + 100, intent, PendingIntent.FLAG_CANCEL_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            exact = Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()
            mode = if(exact) SchedulerMode.EXACT_IDLE_WITH_TIMER else SchedulerMode.INEXACT_IDLE_WITH_TIMER
            try {
                if(exact) alarms.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!)
                else alarms.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!)
            } catch (_: SecurityException) {
                mode = SchedulerMode.INEXACT_IDLE_WITH_TIMER
                alarms.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!)
            }
            ticket.alarmInstalled = true
        } catch (_: RuntimeException) {
            mode = SchedulerMode.TIMER_FALLBACK
        }
        try {
            // A normal timer avoids inexact-alarm batching while the CPU is awake.
            // It cannot wake a sleeping CPU; the idle alarm remains the wake-up path.
            // Use the original monotonic deadline, not time spent installing alarms.
            val remaining = maxOf(0, timing.dueElapsed - SystemClock.elapsedRealtime())
            ticket.future = worker.schedule(Runnable { deliver(TracePoint.TIMER_DELIVERY) }, remaining, TimeUnit.MILLISECONDS)
        } catch (_: java.util.concurrent.RejectedExecutionException) {
            tokens.remove(timing.kind, ticket); ticket.cancel()
            TimingTrace.emit(TracePoint.FINISH, generation, timing, error = ErrorKind.NETWORK)
            return
        }
        if(!alive(generation)) { tokens.remove(timing.kind, ticket); ticket.cancel() }
        SessionState.change(generation) { it.copy(schedulerMode = mode) }
        TimingTrace.emit(TracePoint.SCHEDULER, generation, timing, mode = mode, numeric = if(exact) 1 else 0)
    }
}
