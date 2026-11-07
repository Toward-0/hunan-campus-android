package org.esurfing.hunan

import android.app.Instrumentation
import android.os.Bundle
import android.os.Process
import java.security.KeyStore
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText

/** Destructive operations are guarded by application ID and UID separation before opening storage. */
class CredentialProbe : Instrumentation() {
    private var verifyUpgrade = false
    override fun onCreate(arguments: Bundle?) { verifyUpgrade = arguments?.getString("mode") == "verifyUpgrade"; super.onCreate(arguments); start() }
    override fun onStart() {
        var stage = 0
        try {
            val ctx = targetContext
            check(ctx.packageName == "org.esurfing.hunan.isolation")
            val marker = java.io.File(ctx.filesDir, "isolated-upgrade-marker")
            if(verifyUpgrade) {
                check(marker.readText() == "isolated-upgrade-fixture")
                finish(-1, Bundle().apply { putString("result", "PASS: isolated same-signature upgrade preserved app-private marker") })
                return
            }
            val vault = ctx.getSharedPreferences("vault", 0)
            val credentials = Credentials(ctx)
            credentials.clear()
            stage = 1
            check(credentials.load().isEmpty())
            credentials.save("isolated-fixture-a")
            check(credentials.load() == "isolated-fixture-a")
            check(vault.all.values.none { it.toString().contains("isolated-fixture") })
            stage = 2
            credentials.save("isolated-fixture-b")
            check(credentials.load() == "isolated-fixture-b")
            vault.edit().putString("cipher", "corrupted-fixture").commit()
            check(runCatching { credentials.load() }.isFailure)
            credentials.save("isolated-fixture-c")
            check(credentials.load() == "isolated-fixture-c")
            stage = 3
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry("campus-v1") }
            marker.writeText("isolated-upgrade-fixture")
            check(runCatching { credentials.load() }.isFailure)
            credentials.save("isolated-fixture-d")
            check(credentials.load() == "isolated-fixture-d")
            stage = 4
            vault.edit().remove("iv").commit()
            check(runCatching { credentials.load() }.isFailure)
            credentials.save("isolated-fixture-e")
            check(credentials.load() == "isolated-fixture-e")
            credentials.clear()
            check(credentials.load().isEmpty())
            stage = 5
            // Route any accidentally started work to a loopback endpoint, with synthetic identity only.
            ctx.getSharedPreferences("settings", 0).edit().putString("username", "isolated-fixture-user")
                .putString("portal", "http://127.0.0.1:18995").putString("ip", "127.0.0.2")
                .putString("gateway", "127.0.0.1").putString("mscgip", "127.0.0.1")
                .putString("mac", "00-11-22-33-44-55").commit()
            credentials.save("isolated-ui-old")
            val activity = startActivitySync(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            fun views(v: View): List<View> = listOf(v) + if(v is ViewGroup) (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
            val all = views(activity.window.decorView)
            val password = all.filterIsInstance<EditText>().first { it.hint.toString() == "留空保留已保存密码" }
            val save = all.filterIsInstance<Button>().first { it.text.toString() == "保存并登录" }
            runOnMainSync {
                password.setText("")
                save.performClick()
                activity.startForegroundService(Intent(activity, SessionService::class.java).setAction("stop"))
            }
            check(credentials.load() == "isolated-ui-old")
            runOnMainSync {
                password.setText("isolated-ui-new")
                save.performClick()
                activity.startForegroundService(Intent(activity, SessionService::class.java).setAction("stop"))
            }
            check(credentials.load() == "isolated-ui-new")
            credentials.clear()
            ctx.getSharedPreferences("settings", 0).edit().clear().commit()
            KeyStore.getInstance("AndroidKeyStore").apply { load(null); deleteEntry("campus-v1") }
            finish(-1, Bundle().apply { putString("result", "PASS: UID-isolated storage corruption/missing key/IV/resave/clear, actual UI blank-password preservation and password replacement; not permanent key-invalidation acceptance") })
        } catch (t: Throwable) {
            finish(0, Bundle().apply { putString("result", "FAIL: stage=$stage class=${t.javaClass.simpleName}") })
        }
    }
}
