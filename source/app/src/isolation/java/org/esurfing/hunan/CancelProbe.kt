package org.esurfing.hunan

import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Process
import android.os.SystemClock
import java.net.ServerSocket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class CancelProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        var cycle = 0
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1000)
            repeat(2) {
                cycle++
                val accepted = CountDownLatch(1)
                ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1")).use { server ->
                    server.soTimeout = 10000
                    val thread = Thread {
                        try {
                            server.accept().use { socket ->
                                socket.soTimeout = 5000
                                val reader = socket.getInputStream().bufferedReader()
                                while(true) { val line = reader.readLine() ?: break; if(line.isEmpty()) break }
                                accepted.countDown()
                                Thread.sleep(2000)
                                socket.getOutputStream().write("HTTP/1.1 200 OK\r\nError-Code: 200\r\nContent-Length: 4\r\nConnection: close\r\n\r\nxxxx".toByteArray())
                            }
                        } catch (_: Exception) { /* Client disconnect after cancellation is expected. */ }
                    }.apply { isDaemon = true; start() }
                    ctx.getSharedPreferences("settings", 0).edit().putString("username", "isolated-fixture-user")
                        .putString("portal", "http://127.0.0.1:${server.localPort}").putString("ip", "127.0.0.2")
                        .putString("gateway", "127.0.0.1").putString("mscgip", "127.0.0.1")
                        .putString("mac", "00-11-22-33-44-55").putLong("configRevision", cycle.toLong()).commit()
                    Credentials(ctx).save("isolated-fixture-password")
                    runOnMainSync { ctx.startForegroundService(Intent(ctx, SessionService::class.java).setAction("start")) }
                    check(accepted.await(8, TimeUnit.SECONDS))
                    runOnMainSync { ctx.startForegroundService(Intent(ctx, SessionService::class.java).setAction("stop")) }
                    val deadline = SystemClock.elapsedRealtime() + 3000
                    while(SessionState.snapshot().desired || SessionState.snapshot().phase != Phase.STOPPED || SessionService.instancesCreated.get() != SessionService.instancesDestroyed.get()) {
                        check(SystemClock.elapsedRealtime() < deadline)
                        Thread.sleep(20)
                    }
                    runOnMainSync { /* Drain service destruction before capturing the terminal generation. */ }
                    val generation = SessionState.snapshot().generation
                    thread.join(4000)
                    check(!thread.isAlive)
                    check(!SessionState.snapshot().desired && SessionState.snapshot().phase == Phase.STOPPED)
                    check(SessionState.snapshot().generation == generation)
                }
            }
            Credentials(ctx).clear()
            ctx.getSharedPreferences("settings", 0).edit().clear().commit()
            finish(-1, Bundle().apply { putString("result", "PASS: isolated real service stop during accepted delayed module response, late response rejected, cancel then restart (2 cycles); no real account authentication") })
        } catch(t: Throwable) {
            finish(0, Bundle().apply { putString("result", "FAIL: cycle=$cycle class=${t.javaClass.simpleName}") })
        }
    }
}

