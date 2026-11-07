package org.esurfing.hunan

import android.net.Network
import android.net.Uri
import java.net.HttpURLConnection
import java.net.URL

data class PortalHint(val portal: String, val mac: String, val mscgip: String, val source: String)
enum class DiscoveryReason { FOUND, NOT_REDIRECT, LOCATION_MISSING, LOCATION_TOO_LONG, LOCATION_INVALID,
    IDENTITY_MISSING, IP_MISMATCH, TARGET_REJECTED, NETWORK_ERROR, CANCELLED }
data class DiscoveryResult(val hint: PortalHint?, val reason: DiscoveryReason)

object PortalDiscovery {
    /** Same accepted identity/endpoint policy as before; reasons never contain response data. */
    internal fun evaluate(code: Int, location: String?, base: URL, ip: String, source: String): DiscoveryResult {
        fun rejected(reason: DiscoveryReason) = DiscoveryResult(null, reason)
        if (code !in 300..399) return rejected(DiscoveryReason.NOT_REDIRECT)
        if (location == null) return rejected(DiscoveryReason.LOCATION_MISSING)
        if (location.length > 8192) return rejected(DiscoveryReason.LOCATION_TOO_LONG)
        return try {
            val resolved = URL(base, location)
            val uri = Uri.parse(resolved.toString())
            val mac = uri.getQueryParameter("wlanusermac") ?: return rejected(DiscoveryReason.IDENTITY_MISSING)
            val msc = uri.getQueryParameter("mscgip") ?: return rejected(DiscoveryReason.IDENTITY_MISSING)
            if (uri.getQueryParameter("wlanuserip") != ip) return rejected(DiscoveryReason.IP_MISMATCH)
            val ipv4 = Regex("[0-9]{1,3}(\\.[0-9]{1,3}){3}")
            if (resolved.protocol != "http" || resolved.userInfo != null || !resolved.host.matches(ipv4) ||
                !msc.matches(ipv4) || !mac.replace(":", "").replace("-", "").matches(Regex("[0-9a-fA-F]{12}")))
                return rejected(DiscoveryReason.TARGET_REJECTED)
            val portal = "http://${resolved.host}:${if (resolved.port == -1) 80 else resolved.port}"
            DiscoveryResult(PortalHint(portal, mac, msc, source), DiscoveryReason.FOUND)
        } catch (_: Exception) { rejected(DiscoveryReason.LOCATION_INVALID) }
    }

    fun find(network: Network, ip: String, scope: HttpScope? = null, alive: () -> Boolean = { true }): PortalHint? {
        if (scope == null) return HttpScope().use { find(network, ip, it, alive) }
        val probes = listOf(
            "forward.cgi" to "http://192.168.99.99/forward.cgi",
            "百度 HTTP" to "http://www.baidu.com/",
            "腾讯 HTTP" to "http://www.qq.com/"
        )
        for ((index, probe) in probes.withIndex()) {
            if (!alive()) return null
            val (source, address) = probe
            var conn: HttpURLConnection? = null
            var requestError = ErrorKind.NONE
            var reason = DiscoveryReason.NETWORK_ERROR
            var httpCode: Int? = null
            try {
                conn = scope.open(network, URL(address))
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 3000; conn.readTimeout = 3000; conn.useCaches = false
                TimingTrace.emit(TracePoint.REQUEST_START, scope.generation, kind = TaskKind.AUTH)
                val code = conn.responseCode
                httpCode = code
                if (!alive()) { reason = DiscoveryReason.CANCELLED; return null }
                val result = evaluate(code, conn.getHeaderField("Location"), conn.url, ip, source)
                reason = result.reason
                SessionState.log("门户发现 $source：HTTP $code，${reason.name}")
                if (result.hint != null) return result.hint
            } catch (_: Exception) {
                requestError = ErrorKind.NETWORK
                reason = if (alive()) DiscoveryReason.NETWORK_ERROR else DiscoveryReason.CANCELLED
                SessionState.log("门户发现 $source：${reason.name}")
            } finally {
                TimingTrace.emit(TracePoint.DISCOVERY, scope.generation, kind = TaskKind.AUTH,
                    error = requestError, discovery = reason, probe = index, httpCode = httpCode)
                TimingTrace.emit(TracePoint.REQUEST_FINISH, scope.generation, kind = TaskKind.AUTH, error = requestError)
                conn?.let { scope.finish(it) }
            }
        }
        return null
    }
}
