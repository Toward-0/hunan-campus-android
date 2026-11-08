package org.esurfing.hunan

import org.json.JSONObject
import org.json.JSONTokener
import java.io.IOException

/** A second, typed allowlist at the export boundary; raw file text is never exported. */
internal object DiagnosticJsonl {
    const val MAX_CHARS = 128_000
    private val required = setOf("schema", "process", "pid", "wall", "elapsed", "uptime", "nano", "tid",
        "point", "kind", "generation", "network", "desired", "phase", "retries", "internetEvidence",
        "error", "stop", "interactive", "idle", "lightIdle", "plugged", "battery", "temperatureDeciC", "sampleCostMs")
    private val numbers = setOf("pid", "wall", "elapsed", "uptime", "nano", "tid", "generation", "retries",
        "plugged", "battery", "temperatureDeciC", "sampleCostMs", "task", "dueWall", "dueElapsed", "dueUptime", "number", "historicalWall")
    private val booleans = setOf("desired", "interactive", "idle")
    private val enums = mapOf(
        "point" to TracePoint.entries.map { it.name }.toSet(),
        "kind" to TaskKind.entries.map { it.name }.toSet(),
        "phase" to Phase.entries.map { it.name }.toSet(),
        "internetEvidence" to InternetEvidence.entries.map { it.name }.toSet(),
        "error" to ErrorKind.entries.map { it.name }.toSet(),
        "stop" to StopReason.entries.map { it.name }.toSet(),
        "intervalSource" to IntervalSource.entries.map { it.name }.toSet(),
        "schedulerMode" to SchedulerMode.entries.map { it.name }.toSet(),
        "discoveryReason" to DiscoveryReason.entries.map { it.name }.toSet())
    private val allowed = numbers + booleans + enums.keys + setOf("schema", "process", "network", "lightIdle", "discoveryProbe", "httpCode")
    private fun integral(value: Any) = value is Byte || value is Short || value is Int || value is Long

    internal fun normalize(line: String): String? = try {
        val parser = JSONTokener(line)
        val input = parser.nextValue() as? JSONObject
        if (input == null || parser.nextClean() != '\u0000') null else {
            val keys = input.keys().asSequence().toSet()
            if (!keys.containsAll(required) || !allowed.containsAll(keys)) null else {
                val output = JSONObject()
                var valid = true
                for (key in keys) {
                    val value = input.get(key)
                    val accepted = when {
                        key in numbers -> integral(value)
                        key in booleans -> value is Boolean
                        key in enums -> value is String && value in enums.getValue(key)
                        key == "schema" -> integral(value) && (value as Number).toLong() == 2L
                        key == "process" -> value is String && value.matches(Regex("[0-9a-f]{8}"))
                        key == "network" -> value is String && (value == "none" || value.matches(Regex("[0-9]{1,20}")))
                        key == "lightIdle" -> value is Boolean || value === JSONObject.NULL
                        key == "discoveryProbe" -> integral(value) && (value as Number).toLong() in 0L..2L
                        key == "httpCode" -> integral(value) && (value as Number).toLong() in 100L..599L
                        else -> false
                    }
                    if (!accepted) { valid = false; break }
                    output.put(key, value)
                }
                if (valid) output.toString() else null
            }
        }
    } catch (_: org.json.JSONException) { null }

    /** Each file is parsed separately, including a complete last line without a newline. */
    internal fun export(versionName: String, versionCode: Long, read: (String) -> String?): String {
        val records = ArrayDeque<String>()
        var rejected = 0
        var unreadable = 0
        var truncated = 0
        var recordChars = 0
        for (name in listOf("trace.previous.jsonl", "trace.jsonl")) {
            val text = try { read(name) } catch (_: IOException) { unreadable++; null }
                catch (_: SecurityException) { unreadable++; null }
            text?.lineSequence()?.filter { it.isNotBlank() }?.forEach { line ->
                val record = normalize(line)
                if (record == null) rejected++ else { records.addLast(record); recordChars += record.length + 1 }
            }
        }
        fun metadata() = JSONObject().put("type", "metadata").put("schema", 2)
            .put("versionName", versionName.takeIf { it.matches(Regex("[0-9A-Za-z.+_-]{1,80}")) } ?: "unknown")
            .put("versionCode", versionCode.coerceAtLeast(0))
            .put("truncatedRecords", truncated).put("rejectedRecords", rejected).put("unreadableFiles", unreadable).toString()
        var header = metadata()
        while (header.length + 1 + recordChars > MAX_CHARS && records.isNotEmpty()) {
            recordChars -= records.removeFirst().length + 1
            truncated++
            header = metadata()
        }
        return buildString(header.length + 1 + recordChars) {
            append(header).append('\n')
            records.forEach { append(it).append('\n') }
        }
    }
}
