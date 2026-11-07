package org.esurfing.hunan

import android.net.Network
import android.util.Xml
import org.xmlpull.v1.XmlPullParser
import java.io.StringReader
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

class ProtocolFailure(val code: String?) : Exception("Protocol response not accepted")

data class Identity(val ip: String, val mac: String, val gateway: String, val mscgip: String, val hostname: String)
data class EndpointResult(val fields: Map<String, String>)
data class WireProfile(val localTime: String = "00000000k", val contentType: String = "application/octet-stream", val userAgent: String = Protocol.UA, val clientId: String = Protocol.CLIENT)

class Protocol(private val network: Network, private val portal: String, private val identity: Identity, private val profile: WireProfile = WireProfile(), private val traceGeneration: Long = 0, private val scope: HttpScope = HttpScope()) {
    companion object {
        const val UA = "CCTP/WinSVR3/1052"
        const val CLIENT = "c167f455-7b9f-4c0f-a401-df583ab269e2"
        val paths = listOf("ticket", "auth", "state", "keep", "term")
        fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")
        fun parse(text: String): Map<String, String> {
            require(!text.contains("<!DOCTYPE", true)) { "响应包含不支持的 XML 声明" }
            val parser = Xml.newPullParser()
            parser.setInput(StringReader(text))
            val result = mutableMapOf<String, String>()
            var event = parser.eventType
            var tag = ""
            while (event != XmlPullParser.END_DOCUMENT) {
                if (event == XmlPullParser.START_TAG) tag = parser.name
                if (event == XmlPullParser.TEXT && parser.text.isNotBlank()) result[tag] = parser.text.trim()
                event = parser.next()
            }
            return result
        }
    }
    @Volatile private var cancelled = false
    @Volatile private var terminating = false
    @Volatile private var active: HttpURLConnection? = null
    private var heartbeatStarted = false
    private var keepUrl: URL? = null
    private var termUrl: URL? = null
    private val dynamic = profile.userAgent == "CCTP/iOSdy/4023"
    @Volatile private var mobile: NativeSession? = null
    private fun ticketUrl() = URL("$portal/ticket.cgi?wlanuserip=${identity.ip}&mscgip=${identity.mscgip}&wlanusermac=${identity.mac.replace(":", "").replace("-", "").lowercase()}")
    private fun initializeDynamic() {
        val conn = scope.open(network, ticketUrl())
        active = conn
        var requestError = ErrorKind.NONE
        try {
            check(!cancelled)
            conn.requestMethod = "POST"; conn.instanceFollowRedirects = false
            conn.connectTimeout = 5000; conn.readTimeout = 10000; conn.doOutput = true
            conn.setRequestProperty("User-Agent", profile.userAgent)
            conn.setRequestProperty("Client-ID", profile.clientId)
            conn.setRequestProperty("Algo-ID", "00000000-0000-0000-0000-000000000000")
            conn.setRequestProperty("CDC-Checksum", "d41d8cd98f00b204e9800998ecf8427e")
            conn.setRequestProperty("Content-Type", profile.contentType)
            conn.setFixedLengthStreamingMode(0)
            TimingTrace.emit(TracePoint.REQUEST_START, traceGeneration, kind = TaskKind.MODULE)
            conn.outputStream.close()
            val http = conn.responseCode
            val code = conn.getHeaderField("Error-Code")?.trim()?.takeIf { it.matches(Regex("-?[0-9]{1,10}")) }
            require(http == 200 && code == "200") { "动态算法协商失败（HTTP $http，协议码 $code）" }
            val output = java.io.ByteArrayOutputStream()
            conn.inputStream.use { input ->
                val buffer = ByteArray(4096)
                while (output.size() <= 65536) {
                    scope.checkActive(conn)
                    val n = input.read(buffer, 0, minOf(buffer.size, 65537 - output.size()))
                    scope.checkActive(conn)
                    if (n < 0) break
                    output.write(buffer, 0, n)
                }
            }
            require(output.size() <= 65536) { "动态模块超长" }
            val session = NativeSession(output.toByteArray())
            mobile = session
            if (cancelled) { session.close(); error("操作已停止") }
            SessionState.log("iOS 兼容通道动态算法已初始化：${session.algorithm}；模块 ${output.size()} 字节")
        } catch (e: Exception) { requestError = if(e is java.io.IOException) ErrorKind.NETWORK else ErrorKind.PROTOCOL; throw e } finally { TimingTrace.emit(TracePoint.REQUEST_FINISH, traceGeneration, kind = TaskKind.MODULE, error = requestError); scope.finish(conn); active = null }
    }
    private fun mobileXml(ep: Int, ticket: String, username: String, password: String): String {
        val time = java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.US).format(java.util.Date())
        val fields = mutableListOf("user-agent" to profile.userAgent, "client-id" to profile.clientId)
        when (ep) {
            0 -> fields.addAll(listOf("local-time" to time, "host-name" to identity.hostname, "ipv4" to identity.ip,
                "ipv6" to "", "mac" to identity.mac.uppercase().replace(":", "-"), "ostag" to "iPhone iOS 17.0", "gwip" to identity.gateway))
            1 -> fields.addAll(listOf("ticket" to ticket, "local-time" to time, "userid" to username, "passwd" to password))
            2 -> fields.addAll(listOf("ticket" to ticket, "local-time" to time))
            3, 4 -> fields.addAll(listOf("local-time" to time, "host-name" to identity.hostname, "ipv4" to identity.ip,
                "ticket" to ticket, "ipv6" to "", "mac" to identity.mac.uppercase().replace(":", "-"), "ostag" to "iPhone iOS 17.0"))
        }
        return "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n<request>\n" +
            fields.joinToString("\n") { (k,v) -> "    <$k>${escape(v)}</$k>" } + "\n</request>\n"
    }
    private fun sessionUrl(value: String?, path: String): URL {
        require(!value.isNullOrBlank() && value.length <= 8192) { "认证响应缺少有效的 $path 地址" }
        val url = try { URL(URL("$portal/"), value) } catch (_: java.net.MalformedURLException) { error("认证响应的 $path 地址无法解析") }
        require(url.protocol == "http" && url.userInfo == null && url.ref == null &&
            url.host.matches(Regex("[0-9]{1,3}(\\.[0-9]{1,3}){3}")) &&
            url.path == "/$path.cgi" && url.port in -1..65535 && url.port != 0) { "认证响应的 $path 地址格式不支持" }
        return url
    }
    fun cancel() { cancelled = true; scope.cancel(); active?.disconnect(); mobile?.close() }
    fun beginLogout() { terminating = true; scope.interruptInFlight() }
    fun call(ep: Int, ticket: String = "", username: String = "", password: String = ""): EndpointResult {
        val kind = if (ep == 3 && !heartbeatStarted) { heartbeatStarted = true; TaskKind.INITIAL_HEARTBEAT } else requestKind(ep)
        check(!cancelled) { "操作已停止" }
        check(!terminating || ep == 4) { "会话正在注销" }
        if (dynamic && mobile == null) initializeDynamic()
        val mac = identity.mac.uppercase().replace(":", "-")
        val values = when (ep) {
            0 -> arrayOf("Windows 11(26300),64 bit ", profile.localTime, identity.gateway, mac, "", identity.ip, profile.clientId, profile.userAgent, identity.hostname)
            1 -> arrayOf(profile.localTime, ticket, password, username, profile.clientId, profile.userAgent)
            2 -> arrayOf(profile.localTime, ticket, profile.clientId, profile.userAgent)
            3 -> arrayOf(profile.localTime, "<hello>1</hello><conn>1</conn>", mac, "", identity.ip, ticket, profile.clientId, profile.userAgent)
            4 -> arrayOf("1", profile.localTime, ticket, profile.clientId, profile.userAgent)
            else -> error("无效端点")
        }
        // excheck-args intentionally contains nested protocol XML.
        val escaped = values.mapIndexed { index, value -> if (ep == 3 && index == 1) value else escape(value) }.toTypedArray()
        val xml = if (dynamic) mobileXml(ep,ticket,username,password) else NativeCore.xml(ep, escaped) ?: error("报文构建失败")
        val wire = if (dynamic) mobile!!.crypt(xml,false) else NativeCore.crypt(xml, false) ?: error("报文加密失败")
        val macHex = identity.mac.replace(":", "").replace("-", "").lowercase()
        val fallback = URL("$portal/${paths[ep]}.cgi?wlanuserip=${identity.ip}&mscgip=${identity.mscgip}&wlanusermac=$macHex")
        val url = when (ep) { 3 -> keepUrl ?: fallback; 4 -> termUrl ?: fallback; else -> fallback }
        val conn = scope.open(network, url)
        active = conn
        var requestError = ErrorKind.NONE
        try {
            check(!cancelled) { "操作已停止" }
            check(!terminating || ep == 4) { "会话正在注销" }
            conn.requestMethod = "POST"; conn.instanceFollowRedirects = false
            conn.connectTimeout = 5000; conn.readTimeout = 10000; conn.doOutput = true
            conn.setRequestProperty("User-Agent", profile.userAgent)
            conn.setRequestProperty("Algo-ID", mobile?.algorithm ?: "FAB1DCDE-2D24-41CD-8510-2416DC7854CF")
            conn.setRequestProperty("Client-ID", profile.clientId)
            conn.setRequestProperty("Content-Type", profile.contentType)
            val bytes = wire.toByteArray(Charsets.US_ASCII)
            val md5 = MessageDigest.getInstance("MD5").digest(bytes).joinToString("") { "%02x".format(it) }
            conn.setRequestProperty("CDC-Checksum", md5)
            conn.setFixedLengthStreamingMode(bytes.size)
            TimingTrace.emit(TracePoint.REQUEST_START, traceGeneration, kind = kind)
            conn.outputStream.use { it.write(bytes) }
            val http = conn.responseCode
            val code = conn.getHeaderField("Error-Code")?.trim()?.takeIf { it.matches(Regex("-?[0-9]{1,10}")) }
            val body = (if (http in 200..299) conn.inputStream else conn.errorStream)?.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (output.size() <= 65536) {
                    scope.checkActive(conn)
                    val n = stream.read(buffer, 0, minOf(buffer.size, 65537 - output.size()))
                    scope.checkActive(conn)
                    if (n < 0) break
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            } ?: byteArrayOf()
            SessionState.log("${paths[ep]}：HTTP $http，协议码 ${code ?: "缺失"}，${body.size} 字节")
            require(body.size <= 65536) { "响应超长" }
            check(!cancelled) { "操作已停止" }
            require(http == 200) { "门户 HTTP 异常 ($http)" }
            if (code != "0") throw ProtocolFailure(code)
            if (ep == 4 && body.isEmpty()) return EndpointResult(emptyMap())
            val hex = String(body, Charsets.US_ASCII).trim()
            val validLength = if (dynamic) hex.length >= 16 && hex.length % 2 == 0 else hex.length >= 96 && hex.length % 32 == 0
            require(validLength && hex.all { it in "0123456789abcdefABCDEF" }) { "响应密文格式无效" }
            val plain = if (dynamic) mobile!!.crypt(hex,true) else NativeCore.crypt(hex, true) ?: error("响应解密失败")
            val parsed = try { parse(plain) } catch (_: Exception) { error("门户 XML 响应无法解析") }
            if (ep == 1) {
                SessionState.log("认证响应账号与提交账号一致：${parsed["userid"] == username}")
                keepUrl = sessionUrl(parsed["keep-url"], "keep")
                termUrl = sessionUrl(parsed["term-url"], "term")
                SessionState.log("已采用服务器下发的心跳和注销地址（不记录会话参数）")
            }
            val names = parsed.keys.filter { it.matches(Regex("[a-zA-Z0-9_-]{1,40}")) }.sorted().joinToString(",")
            SessionState.log("${paths[ep]} 响应字段：$names")
            for (name in listOf("state", "status", "result", "error-code", "code", "ret", "interval", "level", "keep-retry", "against-interval")) {
                val value = parsed[name] ?: continue
                if (value.matches(Regex("-?[0-9]{1,10}")) || value in listOf("online", "offline", "true", "false")) SessionState.log("${paths[ep]}：$name=$value")
            }
            return EndpointResult(parsed)
        } catch (e: Exception) { requestError = if(e is java.io.IOException) ErrorKind.NETWORK else ErrorKind.PROTOCOL; throw e } finally { TimingTrace.emit(TracePoint.REQUEST_FINISH, traceGeneration, kind = kind, error = requestError); scope.finish(conn); active = null }
    }
    private fun requestKind(ep: Int) = listOf(TaskKind.TICKET, TaskKind.LOGIN, TaskKind.STATE, TaskKind.HEARTBEAT, TaskKind.LOGOUT)[ep]
}




