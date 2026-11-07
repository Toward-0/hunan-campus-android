package org.esurfing.hunan
import java.net.URL
internal object TransportPolicy { fun check(url: URL, synthetic: Boolean) { check(synthetic || url.host == "127.0.0.1") } }
