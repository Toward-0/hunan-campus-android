package org.esurfing.hunan

import android.app.Instrumentation
import android.net.Network
import android.os.Bundle
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject

/** In-memory responses only; never opens any network socket. */
class DiscoveryProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        var stage = "setup"
        try {
            check(targetContext.packageName == "org.esurfing.hunan.isolation")
            SessionState.initialize(targetContext)
            val base = URL("http://127.0.0.1/")
            val good = "http://127.0.0.1:1234/?wlanuserip=127.0.0.2&wlanusermac=001122334455&mscgip=127.0.0.1"
            fun evaluate(code: Int, location: String?, reason: DiscoveryReason) {
                stage = reason.name
                val result = PortalDiscovery.evaluate(code, location, base, "127.0.0.2", "synthetic")
                check(result.reason == reason)
                check((result.hint != null) == (reason == DiscoveryReason.FOUND))
                sendStatus(1, Bundle().apply { putString("case", stage) })
            }
            evaluate(200, good, DiscoveryReason.NOT_REDIRECT)
            evaluate(302, null, DiscoveryReason.LOCATION_MISSING)
            evaluate(302, "x".repeat(8193), DiscoveryReason.LOCATION_TOO_LONG)
            evaluate(302, "http://[", DiscoveryReason.LOCATION_INVALID)
            evaluate(302, "http://127.0.0.1/?wlanuserip=127.0.0.2", DiscoveryReason.IDENTITY_MISSING)
            evaluate(302, good.replace("127.0.0.2", "127.0.0.3"), DiscoveryReason.IP_MISMATCH)
            evaluate(302, good.replace("http:", "https:"), DiscoveryReason.TARGET_REJECTED)
            evaluate(302, good, DiscoveryReason.FOUND)
            val parcel = android.os.Parcel.obtain()
            val network = try { parcel.writeInt(1); parcel.setDataPosition(0); Network.CREATOR.createFromParcel(parcel) } finally { parcel.recycle() }
            var opened = 0
            var closed = 0
            val scope = HttpScope(0) { _, _ ->
                val index = opened++
                object : HttpURLConnection(base) {
                    override fun connect() = Unit
                    override fun usingProxy() = false
                    override fun disconnect() { closed++ }
                    override fun getResponseCode(): Int { if(index == 0) throw java.io.IOException("private-synthetic-sentinel"); return 302 }
                    override fun getHeaderField(name: String?): String? = if(index == 1) null else good
                }
            }
            stage = "network-fallback-resource-release"
            check(PortalDiscovery.find(network, "127.0.0.2", scope)?.portal == "http://127.0.0.1:1234")
            scope.close(); check(opened == 3 && closed == 3)
            val cancelled = HttpScope(0) { _, _ -> error("Must not open a cancelled request") }
            check(PortalDiscovery.find(network, "127.0.0.2", cancelled) { false } == null); cancelled.close()
            stage = "fixed-schema-privacy"
            val exported = TimingTrace.export()
            check(!exported.contains("private-synthetic-sentinel") && !exported.contains("wlanusermac") && !exported.contains("127.0.0.2"))
            val rows = exported.lines().filter { it.isNotBlank() }.map { JSONObject(it) }.filter { it.optString("point") == "DISCOVERY" }
            check(rows.takeLast(3).map { it.getString("discoveryReason") } == listOf("NETWORK_ERROR", "LOCATION_MISSING", "FOUND"))
            check(rows.takeLast(3).map { it.getInt("discoveryProbe") } == listOf(0,1,2))
            check(rows.last().getInt("httpCode") == 302)
            finish(-1, Bundle().apply { putString("result", "PASS: 8 response classes, network fallback, cancellation, release, typed private-data-free trace") })
        } catch(t: Throwable) { finish(0, Bundle().apply { putString("result", "FAIL $stage ${t.javaClass.simpleName}") }) }
    }
}
