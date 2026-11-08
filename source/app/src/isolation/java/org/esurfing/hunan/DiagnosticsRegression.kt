package org.esurfing.hunan

import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.IOException

/** Synthetic-only fixtures. Runs the actual exporter and Android JSON implementation. */
internal object DiagnosticsRegression {
    private fun row(number: Int): String = JSONObject()
        .put("schema", 2).put("process", "1234abcd").put("pid", 1).put("wall", 2L).put("elapsed", 3L)
        .put("uptime", 3L).put("nano", 4L).put("tid", 1).put("point", "CONTROL").put("kind", "NONE")
        .put("generation", 1).put("network", "none").put("desired", false).put("phase", "STOPPED")
        .put("retries", 0).put("internetEvidence", "NOT_CHECKED").put("error", "NONE").put("stop", "USER_STOP")
        .put("interactive", true).put("idle", false).put("lightIdle", JSONObject.NULL).put("plugged", 0)
        .put("battery", 80).put("temperatureDeciC", 250).put("sampleCostMs", 0).put("number", number).toString()

    internal fun parse(text: String): List<JSONObject> = text.lineSequence().filter { it.isNotBlank() }.map {
        val parser = JSONTokener(it)
        val record = parser.nextValue()
        check(record is JSONObject && parser.nextClean() == '\u0000')
        record
    }.toList()

    fun run(progress: (String) -> Unit = {}): JSONArray {
        val cases = JSONArray()
        fun test(id: String, run: () -> Unit) { progress(id); run(); cases.put(JSONObject().put("id", id).put("status", "PASS")) }
        fun export(previous: String? = null, current: String? = null) = DiagnosticJsonl.export("0.2.22-compat-s1", 34) {
            if (it == "trace.previous.jsonl") previous else current
        }.also { check(it.length <= DiagnosticJsonl.MAX_CHARS); check(parse(it).first().getString("type") == "metadata") }
        test("JSON-EMPTY-MISSING") {
            val records = parse(export())
            check(records.size == 1 && records[0].getInt("unreadableFiles") == 0)
            check(parse(export("\n \r\n", "")).size == 1)
        }
        test("JSON-SINGLE-DOUBLE-ORDER") {
            check(parse(export(current = row(1) + "\n")).drop(1).single().getInt("number") == 1)
            check(parse(export(row(1) + "\n", row(2) + "\n")).drop(1).map { it.getInt("number") } == listOf(1, 2))
        }
        test("JSON-NO-FINAL-NEWLINE") {
            check(parse(export(row(1), row(2))).drop(1).map { it.getInt("number") } == listOf(1, 2))
        }
        test("JSON-ROTATION-PARTIAL-RECORDS") {
            val records = parse(export("truncated-prefix}\n" + row(1), "{\"schema\":\n" + row(2)))
            check(records[0].getInt("rejectedRecords") == 2)
            check(records.drop(1).map { it.getInt("number") } == listOf(1, 2))
        }
        for (size in listOf(127999, 128000, 128001)) test("JSON-INPUT-$size") {
            val unit = row(1) + "\n"
            val count = (size - unit.length) / unit.length
            val prefix = unit.repeat(count)
            val padding = size - prefix.length - row(2).length - 1
            check(padding >= 0)
            val input = prefix + row(2).dropLast(1) + " ".repeat(padding) + "}\n"
            check(input.length == size)
            val records = parse(export(current = input))
            check(records.last().getInt("number") == 2)
            check(records.size - 1 + records[0].getInt("truncatedRecords") == count + 1)
            if (size == 128001) {
                // Exact reproduction of the old takeLast defect, with no baseline execution.
                check(DiagnosticJsonl.normalize(input.takeLast(128000).lineSequence().first()) == null)
            }
        }
        test("JSON-BOUNDED-COMPLETE-TAIL") {
            val input = (0 until 400).joinToString("\n") { row(it) } + "\n"
            val records = parse(export(current = input))
            val ids = records.drop(1).map { it.getInt("number") }
            check(records[0].getInt("truncatedRecords") > 0)
            check(ids == (400 - ids.size until 400).toList())
            check(ids.size + records[0].getInt("truncatedRecords") == 400)
            check(records[0].getInt("rejectedRecords") == 0)
        }
        test("JSON-READ-FAILURE") {
            val text = DiagnosticJsonl.export("0.2.22-compat-s1", 34) {
                if (it == "trace.previous.jsonl") throw IOException("synthetic read failure") else row(2)
            }
            val records = parse(text)
            check(records.size == 2 && records[0].getInt("unreadableFiles") == 1)
            check(!text.contains("synthetic read failure"))
            check(parse(DiagnosticJsonl.export("0.2.22-compat-s1", 34) { throw SecurityException() })[0].getInt("unreadableFiles") == 2)
        }
        test("JSON-WHITELIST-AND-TYPES") {
            val sentinel = "SENTINEL_password_ticket_url"
            val bad = listOf(JSONObject(row(1)).put("password", sentinel).toString(),
                JSONObject(row(1)).put("network", sentinel).toString(), JSONObject(row(1)).put("number", "12").toString(),
                JSONObject(row(1)).put("point", sentinel).toString(), JSONObject(row(1)).put("httpCode", 600).toString(),
                JSONObject(row(1)).put("discoveryProbe", 3).toString(), JSONObject(row(1)).put("schema", 1).toString(), row(1) + "garbage")
            val text = export(current = bad.joinToString("\n") + "\n" + row(2))
            check(!text.contains(sentinel))
            check(parse(text)[0].getInt("rejectedRecords") == bad.size && parse(text).size == 2)
        }
        test("JSON-METADATA") {
            val header = parse(export())[0]
            check(header.getInt("versionCode") == 34 && header.getInt("schema") == 2)
            check(header.getString("versionName") == "0.2.22-compat-s1")
            val invalid = DiagnosticJsonl.export("SENTINEL password", -1) { null }
            check(!invalid.contains("SENTINEL") && parse(invalid)[0].getString("versionName") == "unknown")
        }
        return cases
    }
}
