package android.net
class Network {
    val socketFactory: javax.net.SocketFactory get() = javax.net.SocketFactory.getDefault()
    fun getAllByName(host: String): Array<java.net.InetAddress> {
        check(host == "127.0.0.1" || host == "localhost") { "JVM fixture cannot reach external hosts" }
        return java.net.InetAddress.getAllByName(host)
    }
    fun openConnection(url: java.net.URL): java.net.URLConnection {
        check(url.host == "127.0.0.1")
        return url.openConnection()
    }
}
