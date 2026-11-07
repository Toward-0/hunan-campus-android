package org.esurfing.hunan

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.PowerManager
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

/** Explicit capability checks; bounded request wake lock; no boot receiver or automatic authentication. */
class WakeupScheduler(context: Context, private val worker: ScheduledExecutorService, private val alive: (Long) -> Boolean) {
    private val app = context.applicationContext
    private val alarms = app.getSystemService(AlarmManager::class.java)
    private val power = app.getSystemService(PowerManager::class.java)
    private val tokens = ConcurrentHashMap<TaskKind, Ticket>()
    private inner class Ticket(val timing: TaskTiming, val generation: Long) {
        val nonce = UUID.randomUUID().toString()
        val cancelled = AtomicBoolean()
        var pending: PendingIntent? = null
        var future: ScheduledFuture<*>? = null
        @Volatile var wake: PowerManager.WakeLock? = null
        fun release() { val lock = wake; if(lock != null) synchronized(lock) { if(lock.isHeld) lock.release() } }
        fun cancel() {
            cancelled.set(true)
            WakeupDispatch.cancel(nonce)
            pending?.let { alarms.cancel(it); it.cancel() }
            future?.cancel(false)
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
        fun deliver() {
            WakeupDispatch.cancel(ticket.nonce)
            if(ticket.cancelled.get() || !alive(generation)) return
            TimingTrace.emit(TracePoint.ALARM_DELIVERY, generation, timing)
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
        WakeupDispatch.register(ticket.nonce) { deliver() }
        val intent = Intent(app, WakeupReceiver::class.java).setAction("org.esurfing.hunan.WAKE_TASK").putExtra("token", ticket.nonce)
        ticket.pending = PendingIntent.getBroadcast(app, timing.kind.ordinal + 100, intent, PendingIntent.FLAG_CANCEL_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val exact = Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms()
        var mode = if(exact) SchedulerMode.EXACT_IDLE_PENDING else SchedulerMode.INEXACT_IDLE_PENDING
        try {
            if(exact) alarms.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!)
            else alarms.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!)
        } catch (_: SecurityException) {
            mode = SchedulerMode.INEXACT_IDLE_PENDING
            try { alarms.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, timing.dueElapsed, ticket.pending!!) }
            catch (_: RuntimeException) { mode = SchedulerMode.TIMER_FALLBACK; ticket.future = worker.schedule({ deliver() }, seconds, TimeUnit.SECONDS) }
        }
        if(!alive(generation)) { tokens.remove(timing.kind, ticket); ticket.cancel() }
        SessionState.change(generation) { it.copy(schedulerMode = mode) }
        TimingTrace.emit(TracePoint.SCHEDULER, generation, timing, mode = mode, numeric = if(exact) 1 else 0)
    }
}
