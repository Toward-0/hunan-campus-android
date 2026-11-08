package org.esurfing.hunan

import android.content.Context
import java.io.File

object SessionState {
    const val MAX_LINES = 1024
    @Volatile private var value = SessionSnapshot()
    private val lines = ArrayDeque<String>()
    private var directory: File? = null
    private var initialized = false
    @Synchronized fun initialize(context: Context) {
        if (initialized) return
        initialized = true
        directory = File(context.noBackupFilesDir, "diagnostics").apply { mkdirs() }
        val desired = !context.getSharedPreferences("settings", 0).getBoolean("manualOff", true)
        value = value.copy(desired = desired, phase = if (desired) Phase.INTERRUPTED else Phase.IDLE,
            error = if (desired) ErrorKind.PROCESS_INTERRUPTED else ErrorKind.NONE,
            status = if (desired) "上次连接已中断；请手动连接" else "尚未连接")
        record()
        TimingTrace.initialize(context)
    }
    fun snapshot() = value
    var status: String
        get() = value.status
        set(text) { change { it.copy(status = text) } }
    var details: String
        get() = value.details
        set(text) { change { it.copy(details = text) } }
    @Synchronized fun change(id: Long? = null, transform: (SessionSnapshot) -> SessionSnapshot) {
        if (id != null && id != value.generation) return
        value = transform(value)
        record()
    }
    private fun record() {
        val dir = directory ?: return
        try {
            val file = File(dir, "events.tsv")
            if (file.length() >= 65_536) {
                val previous = File(dir, "events.previous.tsv")
                previous.delete()
                if (!file.renameTo(previous)) return
            }
            file.appendText(value.event(System.currentTimeMillis()) + "\n")
        } catch (_: java.io.IOException) { /* Logging cannot end the session. */ }
    }
    @Synchronized fun log(message: String) {
        // Local legacy diagnostics only, never included in the export.
        lines.addLast("${android.os.SystemClock.elapsedRealtime()/1000}s ${message.take(1000)}")
        while (lines.size > MAX_LINES) lines.removeFirst()
    }
    @Synchronized fun logs() = lines.joinToString("\n")
    @Synchronized fun export(): String {
        return TimingTrace.export()
    }
}



