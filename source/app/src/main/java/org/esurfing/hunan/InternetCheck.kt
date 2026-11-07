package org.esurfing.hunan

import android.net.Network
import java.net.HttpURLConnection
import java.net.URL

object InternetCheck {
    fun run(network: Network, scope: HttpScope? = null, alive: () -> Boolean = { true }): Boolean =
        inspect(network, scope, alive) == InternetEvidence.HTTPS_VERIFIED

    fun inspect(network: Network, scope: HttpScope? = null, alive: () -> Boolean = { true }): InternetEvidence {
        if (scope == null) return HttpScope().use { inspect(network, it, alive) }
        if(!alive()) return InternetEvidence.NOT_CHECKED
        var portalRequired = false
        var portal: HttpURLConnection? = null
        var portalError = ErrorKind.NONE
        try {
            portal = scope.open(network, URL("http://www.baidu.com/"))
            portal.connectTimeout = 4000; portal.readTimeout = 4000
            portal.instanceFollowRedirects = false; portal.useCaches = false
            TimingTrace.emit(TracePoint.REQUEST_START, scope.generation, kind = TaskKind.INTERNET, numeric = 0)
            val code = portal.responseCode
            SessionState.log("认证后 Wi-Fi 门户复查：HTTP $code")
            val location = portal.getHeaderField("Location").orEmpty()
            if (code in 300..399 && location.contains("wlanuserip=", true) && location.contains("mscgip=", true)) {
                SessionState.log("接入设备仍返回门户重定向，外网尚未确认放行")
                portalRequired = true
            }
        } catch (e: Exception) {
            portalError = ErrorKind.NETWORK
            SessionState.log("Wi-Fi 门户复查：${e.javaClass.simpleName}：${e.message?.take(180)}")
        } finally { TimingTrace.emit(TracePoint.REQUEST_FINISH, scope.generation, kind = TaskKind.INTERNET, numeric = 0, error = portalError); portal?.let { scope.finish(it) } }
        for ((name, url) in listOf("百度 HTTPS" to "https://www.baidu.com/", "哔哩哔哩 HTTPS" to "https://www.bilibili.com/")) {
            if(!alive()) return InternetEvidence.NOT_CHECKED
            var conn: HttpURLConnection? = null
            var checkError = ErrorKind.NONE
            try {
                conn = scope.open(network, URL(url))
                conn.connectTimeout = 4000; conn.readTimeout = 4000; conn.instanceFollowRedirects = false
                conn.useCaches = false
                TimingTrace.emit(TracePoint.REQUEST_START, scope.generation, kind = TaskKind.INTERNET, numeric = 1)
                val code = conn.responseCode
                val bytes = if (code == 200) conn.inputStream.use { it.read(ByteArray(256)) } else -1
                SessionState.log("Wi-Fi 外网检测：$name HTTP $code，读取 ${maxOf(0, bytes)} 字节")
                if (!alive()) return InternetEvidence.NOT_CHECKED
                if (code == 200 && bytes > 0) return InternetEvidence.HTTPS_VERIFIED
            } catch (e: Exception) {
                checkError = ErrorKind.NETWORK
                SessionState.log("Wi-Fi 外网检测：$name ${e.javaClass.simpleName}：${e.message?.take(180)}")
            } finally { TimingTrace.emit(TracePoint.REQUEST_FINISH, scope.generation, kind = TaskKind.INTERNET, numeric = 1, error = checkError); conn?.let { scope.finish(it) } }
        }
        if (!alive()) return InternetEvidence.NOT_CHECKED
        return if (portalRequired) InternetEvidence.PORTAL_REQUIRED else InternetEvidence.HTTPS_UNREACHABLE
    }
}






