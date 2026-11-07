package org.esurfing.hunan

import android.net.Network
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.HttpURLConnection

fun main() {
    var cases = 0
    fun scenario(portal: Boolean, primary: Int, secondary: Int, expected: InternetEvidence, empty: Boolean = false, stopDuringRead: Boolean = false) {
        var opened = 0
        var closed = 0
        var alive = true
        val scope = HttpScope(0) { _, url ->
            val index = opened++
            object : HttpURLConnection(url) {
                override fun connect() = Unit
                override fun usingProxy() = false
                override fun disconnect() { closed++ }
                override fun getResponseCode(): Int {
                    val code = if(index == 0) { if(portal) 302 else 200 } else if(index == 1) primary else secondary
                    if(code < 0) throw IOException("fixture")
                    return code
                }
                override fun getHeaderField(name: String?): String? = if(index == 0 && portal && name == "Location") "http://127.0.0.1/?wlanuserip=fixture&mscgip=fixture" else null
                override fun getInputStream(): ByteArrayInputStream {
                    if(stopDuringRead) alive = false
                    return ByteArrayInputStream(if(empty) byteArrayOf() else "fixture".toByteArray())
                }
            }
        }
        check(InternetCheck.inspect(Network(), scope) { alive } == expected)
        check(opened == closed)
        if(primary == 200 && !empty) check(opened == 2)
        scope.cancel()
        check(runCatching { scope.open(Network(), java.net.URL("http://127.0.0.1/")) }.isFailure)
        cases++
    }
    scenario(true, 200, -1, InternetEvidence.HTTPS_VERIFIED)
    scenario(true, -1, -1, InternetEvidence.PORTAL_REQUIRED)
    scenario(false, -1, -1, InternetEvidence.HTTPS_UNREACHABLE)
    scenario(false, -1, 200, InternetEvidence.HTTPS_VERIFIED)
    scenario(false, 403, 200, InternetEvidence.HTTPS_VERIFIED)
    scenario(false, 302, 204, InternetEvidence.HTTPS_UNREACHABLE)
    scenario(false, 200, 200, InternetEvidence.HTTPS_UNREACHABLE, empty = true)
    scenario(false, 200, 200, InternetEvidence.NOT_CHECKED, stopDuringRead = true)
    val stopped = HttpScope(0) { _, _ -> error("Must not issue a request") }
    check(InternetCheck.inspect(Network(), stopped) { false } == InternetEvidence.NOT_CHECKED)
    stopped.cancel()
    println("PASS: ${cases + 1} JVM fake-connection scenarios: redirect+HTTPS, fallback, failures, empty body, cancellation; real HttpScope/InternetCheck, stub Android platform. No device/campus acceptance implied.")
}
