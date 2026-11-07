package org.esurfing.hunan

import android.content.Context

/** Derived network identity only; no account, password, ticket or module keys. */
object IdentityCache {
    fun save(context: Context, network: android.net.Network, ip: String, gateway: String, hint: PortalHint) {
        context.getSharedPreferences("identity-cache", 0).edit()
            .putString("ip",ip).putString("gateway",gateway).putString("portal",hint.portal)
            .putString("mac",hint.mac).putString("mscgip",hint.mscgip)
            .putLong("networkHandle", network.networkHandle)
            .putInt("boot", android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.BOOT_COUNT, -1))
            .putLong("observed",System.currentTimeMillis()).commit()
    }
    fun load(context: Context, network: android.net.Network, ip: String, gateway: String): PortalHint? {
        val p=context.getSharedPreferences("identity-cache",0)
        val age=System.currentTimeMillis()-p.getLong("observed",0)
        val boot = android.provider.Settings.Global.getInt(context.contentResolver, android.provider.Settings.Global.BOOT_COUNT, -1)
        if (boot < 0 || p.getInt("boot", -2) != boot || p.getLong("networkHandle", -1) != network.networkHandle) return null
        if(age !in 0L..86400000L || p.getString("ip",null)!=ip || p.getString("gateway",null)!=gateway) return null
        val portal=p.getString("portal",null) ?: return null
        val mac=p.getString("mac",null) ?: return null
        val msc=p.getString("mscgip",null) ?: return null
        return PortalHint(portal,mac,msc,"同次开机、同 Wi-Fi 网络及 IP/网关缓存（外网重新验证通过）")
    }
    fun clear(context: Context) { context.getSharedPreferences("identity-cache",0).edit().clear().commit() }
}
