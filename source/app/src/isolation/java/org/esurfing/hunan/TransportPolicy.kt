package org.esurfing.hunan
import java.net.URL
/** Every real isolation socket must stay on device loopback; mock objects do no I/O. */
internal object TransportPolicy {
    fun check(url: URL, synthetic: Boolean) {
        check(synthetic || (url.protocol == "http" && url.host == "127.0.0.1" && url.port in 1..65535)) { "Isolation blocks non-loopback transport" }
    }
}
