package org.esurfing.hunan

import android.app.Instrumentation
import android.net.Network
import android.os.Bundle
import android.os.Process
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/** Fake connections only: no account, campus traffic, settings or credential writes. */
class InternetProbe : Instrumentation() {
    private var live = false
    override fun onCreate(arguments: Bundle?) { live = arguments?.getString("mode") == "live"; super.onCreate(arguments); start() }
    override fun onStart() {
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            check(!live) { "Live endpoints are forbidden in isolation" }
            val parcel = android.os.Parcel.obtain()
            val fakeNetwork = try { parcel.writeInt(1); parcel.setDataPosition(0); Network.CREATOR.createFromParcel(parcel) } finally { parcel.recycle() }
            var count = 0
            fun scenario(portal: Boolean, primary: Int, secondary: Int, expected: InternetEvidence, empty: Boolean = false) {
                var opened = 0
                var closed = 0
                val scope = HttpScope(0) { _, url ->
                    val index = opened++
                    object : HttpURLConnection(url) {
                        override fun connect() = Unit
                        override fun usingProxy() = false
                        override fun disconnect() { closed++ }
                        override fun getResponseCode(): Int {
                            val status = if(index == 0) { if(portal) 302 else 200 } else if(index == 1) primary else secondary
                            if(status < 0) throw IOException("synthetic failure")
                            return status
                        }
                        override fun getHeaderField(name: String?): String? =
                            if(index == 0 && portal && name == "Location") "http://127.0.0.1/?wlanuserip=fixture&mscgip=fixture" else null
                        override fun getInputStream() = ByteArrayInputStream(if(empty) byteArrayOf() else "fixture".toByteArray())
                    }
                }
                check(InternetCheck.inspect(fakeNetwork, scope) == expected)
                check(opened == closed)
                if(primary == 200 && !empty) check(opened == 2) // No needless second HTTPS request.
                scope.cancel()
                count++
            }
            scenario(true, 200, -1, InternetEvidence.HTTPS_VERIFIED)
            scenario(true, -1, -1, InternetEvidence.PORTAL_REQUIRED)
            scenario(false, -1, -1, InternetEvidence.HTTPS_UNREACHABLE)
            scenario(false, -1, 200, InternetEvidence.HTTPS_VERIFIED)
            scenario(false, 403, 200, InternetEvidence.HTTPS_VERIFIED)
            scenario(false, 302, 204, InternetEvidence.HTTPS_UNREACHABLE)
            scenario(false, 200, 200, InternetEvidence.HTTPS_UNREACHABLE, empty = true)
            val cancelled = HttpScope(0) { _, _ -> error("Cancelled check must not open a request") }
            check(InternetCheck.inspect(fakeNetwork, cancelled) { false } == InternetEvidence.NOT_CHECKED)
            cancelled.cancel()
            finish(-1, Bundle().apply { putString("stream", "PASS: ${count + 1} isolated internet evidence/HTTPS fallback/empty body/cancellation scenarios; no campus requests") })
        } catch (e: Exception) {
            finish(0, Bundle().apply { putString("stream", "FAIL: ${e.javaClass.simpleName}") })
        }
    }
}
