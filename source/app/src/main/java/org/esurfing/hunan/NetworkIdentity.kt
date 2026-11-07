package org.esurfing.hunan

import android.net.LinkProperties
import java.net.Inet4Address

/** Only fields used by the IPv4 authentication protocol can invalidate a session. */
object NetworkIdentity {
    fun key(ipv4: List<String>, defaultGateways: List<String>): String? {
        val ip = ipv4.distinct().sorted().firstOrNull() ?: return null
        val gateway = defaultGateways.distinct().sorted().firstOrNull() ?: return null
        return "$ip|$gateway"
    }
    fun key(lp: LinkProperties): String? = key(
        lp.linkAddresses.mapNotNull { (it.address as? Inet4Address)?.hostAddress },
        lp.routes.filter { it.isDefaultRoute }.mapNotNull { (it.gateway as? Inet4Address)?.hostAddress }
    )
}
