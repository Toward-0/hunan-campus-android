package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket

/** Actual production diagnostic transitions, with synthetic credentials and device loopback only. */
class DiagnosticsProbe : Instrumentation() {
    private var mode = "export"
    override fun onCreate(arguments: Bundle?) { mode = arguments?.getString("mode") ?: mode; super.onCreate(arguments); start() }
    override fun onStart() {
        val runStartedWall = System.currentTimeMillis()
        val result = JSONObject().put("testId", "S1-DIAGNOSTICS").put("mode", mode).put("status", "FAIL")
            .put("api", android.os.Build.VERSION.SDK_INT).put("process64", Process.is64Bit())
        val cases = JSONArray()
        var server: ServerSocket? = null
        var cipher: NativeSession? = null
        var stage = "setup"
        var expected = JSONObject()
        var waitStarted = 0L
        var waitBudget = 0L
        fun await(timeout: Long = 15000, condition: () -> Boolean) {
            waitStarted = SystemClock.elapsedRealtime(); waitBudget = timeout
            val end = waitStarted + timeout
            while (!condition()) { check(SystemClock.elapsedRealtime() < end); Thread.sleep(25) }
        }
        fun historyFailureCount(): Int = synchronized(SessionState) {
            // Wait for the observed snapshot's synchronized record append; never race rotation.
            listOf("events.previous.tsv", "events.tsv").sumOf { name ->
                File(targetContext.noBackupFilesDir, "diagnostics/$name").takeIf { it.isFile }?.useLines { lines ->
                    lines.count {
                        val fields = it.split('\t')
                        (fields.getOrNull(0)?.toLongOrNull() ?: Long.MIN_VALUE) >= runStartedWall && fields.getOrNull(15) == "777"
                    }
                } ?: 0
            }
        }
        fun diagnosticState(): JSONObject {
            val state = SessionState.snapshot()
            val now = System.currentTimeMillis()
            val power = targetContext.getSystemService(android.os.PowerManager::class.java)
            val alarms = targetContext.getSystemService(android.app.AlarmManager::class.java)
            return JSONObject().put("phase", state.phase.name).put("error", state.error.name)
                .put("protocolCode", state.protocolCode.takeIf { it == "none" || it.matches(Regex("-?[0-9]{1,10}")) } ?: "other")
                .put("heartbeatResult", state.heartbeatResult.name).put("internetEvidence", state.internetEvidence.name)
                .put("retries", state.retries).put("desired", state.desired)
                .put("heartbeatIntervalSeconds", state.heartbeatIntervalSeconds)
                .put("heartbeatDueInMs", if (state.heartbeatDueAt == 0L) JSONObject.NULL else state.heartbeatDueAt - now)
                .put("heartbeatAgeMs", if (state.heartbeatAt == 0L) JSONObject.NULL else now - state.heartbeatAt)
                .put("schedulerMode", state.schedulerMode.name)
                .put("exactAlarmCapable", android.os.Build.VERSION.SDK_INT < 31 || alarms.canScheduleExactAlarms())
                .put("interactive", power.isInteractive).put("idle", power.isDeviceIdleMode)
                .put("loginRequests", StabilityFixture.count("/auth.cgi"))
                .put("keepRequests", StabilityFixture.count("/keep.cgi"))
                .put("logoutRequests", StabilityFixture.count("/term.cgi"))
                .put("syntheticErrorsRemaining", StabilityFixture.protocolErrorsRemaining.get())
                .put("historyStartWall", runStartedWall).put("currentRunFailureEvents", historyFailureCount())
                .put("waitBudgetMs", waitBudget)
                .put("waitElapsedMs", if (waitStarted == 0L) 0 else SystemClock.elapsedRealtime() - waitStarted)
        }
        fun command(action: String) = runOnMainSync {
            targetContext.startForegroundService(Intent(targetContext, StabilityService::class.java).setAction(action))
        }
        fun stopped() = await {
            SessionService.instancesCreated.get() == SessionService.instancesDestroyed.get() &&
                OwnedHttpTransport.owners.get() == 0 && OwnedHttpTransport.connections.get() == 0 &&
                HttpScope.queuedDeadlines() == 0 && WakeupDispatch.size() == 0
        }
        fun record(id: String) {
            cases.put(JSONObject().put("id", id).put("status", "PASS").apply {
                if (mode == "session") put("expected", expected).put("actual", diagnosticState())
            })
            sendStatus(1, Bundle().apply { putString("case", id) })
        }
        try {
            check(targetContext.packageName == "org.esurfing.hunan.isolation")
            check(mode in listOf("export", "session"))
            if (mode == "export") {
                stage = "json-boundaries"
                val rows = DiagnosticsRegression.run { stage = it }
                for (i in 0 until rows.length()) cases.put(rows.getJSONObject(i))
                SessionState.initialize(targetContext)
                val exported = SessionState.export()
                val actual = DiagnosticsRegression.parse(exported)
                @Suppress("DEPRECATION")
                val installed = targetContext.packageManager.getPackageInfo(targetContext.packageName, 0)
                check(actual[0].getString("versionName") == installed.versionName)
                @Suppress("DEPRECATION")
                check(actual[0].getLong("versionCode") == installed.versionCode.toLong())
                check(exported.length <= DiagnosticJsonl.MAX_CHARS && actual.size > 1)
                File(targetContext.filesDir, "diagnostics-export.jsonl").writeText(exported)
                record("JSON-ACTUAL-COPY-ENTRY")
            } else {
                targetContext.startActivity(Intent(targetContext, FixtureActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                Thread.sleep(1000)
                StabilityFixture.module = targetContext.assets.open("synthetic-module.zsm").use { it.readBytes() }
                cipher = NativeSession(StabilityFixture.module)
                StabilityFixture.cipher = cipher
                val listening = ServerSocket(0, 32, InetAddress.getByName("127.0.0.1")); server = listening
                StabilityFixture.port = listening.localPort
                StabilityFixture.portal = false; StabilityFixture.persistent = true; StabilityFixture.logoutConfirmed = true
                StabilityFixture.primaryTimeout = false; StabilityFixture.discoveryUnavailable = false
                StabilityFixture.delayPath = ""; StabilityFixture.responseGate = null; StabilityFixture.counts.clear()
                Thread {
                    try { while (!listening.isClosed) { val socket = listening.accept(); StabilityFixture.executor.execute { StabilityFixture.serve(socket) } } }
                    catch (_: Exception) { }
                }.apply { name = "fixture-diagnostics-accept"; isDaemon = true; start() }
                val prefs = targetContext.getSharedPreferences("settings", 0)
                check(prefs.edit().clear().putBoolean("manualOff", true).putString("username", "isolated-fixture-user")
                    .putString("portal", "http://127.0.0.1:${listening.localPort}").putString("ip", "127.0.0.2")
                    .putString("gateway", "127.0.0.1").putString("mscgip", "127.0.0.1").putString("mac", "00-11-22-33-44-55").commit())
                IdentityCache.clear(targetContext); Credentials(targetContext).save("isolated-fixture-password")
                stage = "effective-failure-retained"
                expected = JSONObject().put("phase", "NEEDS_INPUT").put("protocolCode", "777").put("error", "PROTOCOL").put("loginRequests", 1)
                StabilityFixture.protocolErrorPath = "/auth.cgi"; StabilityFixture.protocolErrorsRemaining.set(1)
                command("start")
                await { SessionState.snapshot().phase == Phase.NEEDS_INPUT }
                stopped()
                check(SessionState.snapshot().protocolCode == "777" && SessionState.snapshot().error == ErrorKind.PROTOCOL)
                val firstFailureEvents = historyFailureCount()
                check(firstFailureEvents > 0 && StabilityFixture.count("/auth.cgi") == 1)
                record("STATE-EFFECTIVE-FAILURE-RETAINED")
                stage = "manual-login-success"
                expected = JSONObject().put("phase", "AUTHENTICATED").put("protocolCode", "none").put("error", "NONE").put("loginRequests", 2)
                    .put("minimumCurrentRunFailureEvents", firstFailureEvents)
                command("start")
                await { SessionState.snapshot().phase == Phase.AUTHENTICATED && SessionState.snapshot().internetEvidence == InternetEvidence.HTTPS_VERIFIED }
                check(SessionState.snapshot().protocolCode == "none" && SessionState.snapshot().error == ErrorKind.NONE)
                // This bounded fixture produces far less than the two retained 64KB event files;
                // it checks preservation during recovery, not indefinite retention across rotations.
                check(historyFailureCount() >= firstFailureEvents && StabilityFixture.count("/auth.cgi") == 2)
                record("STATE-FAILED-LOGIN-THEN-SUCCESS")
                stage = "heartbeat-fixture-interval"
                expected = JSONObject().put("heartbeatIntervalSeconds", 25).put("loginRequests", 2)
                check(SessionState.snapshot().heartbeatIntervalSeconds == 25L)
                val keepBeforeFault = StabilityFixture.count("/keep.cgi")
                stage = "heartbeat-await-protocol-failure"
                expected = JSONObject().put("phase", "RECOVERING").put("protocolCode", "777")
                    .put("minimumKeepRequests", keepBeforeFault + 1).put("loginRequests", 2).put("waitBudgetMs", 150000)
                StabilityFixture.protocolErrorPath = "/keep.cgi"; StabilityFixture.protocolErrorsRemaining.set(1)
                // Functional diagnostic recovery only. Android alarm delivery is not a 25-second SLA;
                // preserve the production scheduler and report the actual capability and observation budget.
                await(150000) { SessionState.snapshot().phase == Phase.RECOVERING && SessionState.snapshot().protocolCode == "777" }
                check(StabilityFixture.count("/keep.cgi") > keepBeforeFault)
                val heartbeatFailureEvents = historyFailureCount()
                check(heartbeatFailureEvents > firstFailureEvents)
                result.put("observedHeartbeatFailure", diagnosticState())
                stage = "heartbeat-await-success"
                expected = JSONObject().put("phase", "AUTHENTICATED").put("protocolCode", "none").put("error", "NONE")
                    .put("retries", 0).put("loginRequests", 2).put("logoutRequests", 0).put("waitBudgetMs", 150000)
                    .put("minimumCurrentRunFailureEvents", heartbeatFailureEvents)
                await(150000) { SessionState.snapshot().phase == Phase.AUTHENTICATED && SessionState.snapshot().heartbeatResult == CheckResult.PASS }
                stage = "heartbeat-success-invariants"
                check(SessionState.snapshot().protocolCode == "none" && SessionState.snapshot().error == ErrorKind.NONE && SessionState.snapshot().retries == 0)
                check(historyFailureCount() >= heartbeatFailureEvents && StabilityFixture.count("/auth.cgi") == 2 && StabilityFixture.count("/term.cgi") == 0)
                record("STATE-HEARTBEAT-FAILURE-THEN-SUCCESS")
                stage = "stale-generation"
                expected = JSONObject().put("snapshotUnchanged", true).put("loginRequests", 2).put("logoutRequests", 0)
                val before = SessionState.snapshot()
                SessionState.change(before.generation - 1) { it.copy(error = ErrorKind.PROTOCOL, protocolCode = "888") }
                check(SessionState.snapshot() == before)
                record("STATE-STALE-GENERATION-REJECTED")
                command("stop"); stopped()
                result.put("loginRequests", StabilityFixture.count("/auth.cgi")).put("logoutRequests", StabilityFixture.count("/term.cgi"))
            }
            result.put("status", "PASS")
        } catch (t: Throwable) {
            result.put("status", "FAIL").put("case", stage).put("exception", t.javaClass.simpleName)
                .put("line", t.stackTrace.firstOrNull { it.fileName == "DiagnosticsProbe.kt" }?.lineNumber ?: -1)
                .put("expected", expected)
            if (mode == "session") result.put("actual", diagnosticState())
        } finally {
            if (mode == "session") {
                try {
                    runOnMainSync { targetContext.stopService(Intent(targetContext, StabilityService::class.java)) }
                    stopped()
                } catch (_: Throwable) { result.put("status", "FAIL").put("cleanup", "service-resources") }
                server?.close(); StabilityFixture.closeSockets(); cipher?.close()
                StabilityFixture.protocolErrorPath = ""; StabilityFixture.protocolErrorsRemaining.set(0)
                result.put("handlesAfter", NativeCore.liveMobileHandles())
                if (NativeCore.liveMobileHandles() != 0) result.put("status", "FAIL")
            }
            result.put("cases", cases)
            File(targetContext.filesDir, "diagnostics-$mode.json").writeText(result.toString(2))
        }
        finish(if (result.optString("status") == "PASS") -1 else 0, Bundle().apply { putString("result", result.toString()) })
    }
}
