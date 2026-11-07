package org.esurfing.hunan

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import java.net.HttpURLConnection
import java.net.URL

/** Does not load credentials or send authentication requests. */
object NetworkDiagnostics {
    fun run(context: Context) {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val wifi = cm.allNetworks.firstOrNull {
            cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        }
        if (wifi == null) { SessionState.log("网络诊断：未发现已连接 Wi-Fi"); return }
        val caps = cm.getNetworkCapabilities(wifi)
        val lp = cm.getLinkProperties(wifi)
        SessionState.log("网络诊断：Wi-Fi=$wifi，默认网络=${cm.activeNetwork == wifi}，IPv4/网关就绪=${lp?.let { NetworkIdentity.key(it) } != null}")
        SessionState.log("INTERNET=${caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)}，VALIDATED=${caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)}，CAPTIVE_PORTAL=${caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_CAPTIVE_PORTAL)}")
        val ip = lp?.linkAddresses?.firstOrNull { it.address is java.net.Inet4Address }?.address?.hostAddress
        if (ip != null) {
            val hint = PortalDiscovery.find(wifi, ip)
            if (hint == null) SessionState.log("未发现匹配当前 Wi-Fi 身份的门户；没有使用固定地址回退")
        }
        InternetCheck.run(wifi)
        SessionState.log("网络诊断结束；未提交账号或认证请求")
    }
}


