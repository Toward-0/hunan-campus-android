package org.esurfing.hunan

import android.app.AlertDialog
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import org.json.JSONObject
import org.json.JSONArray
import java.io.File

/** Actual UI interaction, synthetic snapshot only; never confirms a live repair. */
class RepairMenuProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val cases = JSONArray()
        var activity: MainActivity? = null
        var stage = "setup"
        try {
            check(targetContext.packageName == "org.esurfing.hunan.isolation")
            val a = startActivitySync(Intent(targetContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
            activity = a; waitForIdleSync()
            fun views(v: View): List<View> = listOf(v) + if(v is ViewGroup) (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
            fun button(text: String) = views(a.window.decorView).filterIsInstance<Button>().single { it.text.toString() == text }
            val field = MainActivity::class.java.getDeclaredField("repairDialog").apply { isAccessible = true }
            fun dialog() = field.get(a) as AlertDialog
            val serviceCount = SessionService.instancesCreated.get()
            val states = listOf(
                "idle" to SessionSnapshot(),
                "waiting-wifi" to SessionSnapshot(phase=Phase.WAITING_WIFI),
                "discovery" to SessionSnapshot(phase=Phase.DISCOVERING),
                "authenticating" to SessionSnapshot(phase=Phase.AUTHENTICATING),
                "logged-out" to SessionSnapshot(phase=Phase.LOGGED_OUT),
                "logging-out" to SessionSnapshot(phase=Phase.LOGGING_OUT),
                "interrupted" to SessionSnapshot(phase=Phase.INTERRUPTED),
                "online" to SessionSnapshot(phase=Phase.AUTHENTICATED,internetEvidence=InternetEvidence.HTTPS_VERIFIED,internetAt=System.currentTimeMillis()),
                "uncertain" to SessionSnapshot(phase=Phase.AUTHENTICATED,internetEvidence=InternetEvidence.HTTPS_UNREACHABLE),
                "portal-pending" to SessionSnapshot(phase=Phase.AUTHENTICATED,internetEvidence=InternetEvidence.PORTAL_REQUIRED),
                "repair-wait" to SessionSnapshot(phase=Phase.REPAIRING,repairing=true,nextRecoveryAt=System.currentTimeMillis()+100000)
            )
            for((name,state) in states) {
                stage=name
                runOnMainSync {
                    SessionState.change { state }
                    button("更多").performClick()
                    check(button("修复网络").isShown && button("修复网络").isEnabled)
                    button("修复网络").performClick()
                    val d=dialog();check(d.isShowing)
                    check(d.getButton(AlertDialog.BUTTON_POSITIVE).text.toString()=="查看连接")
                    d.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()
                }
                check(SessionService.instancesCreated.get()==serviceCount)
                cases.put(name)
            }
            val ready=SessionSnapshot(generation=77,desired=true,phase=Phase.AUTHENTICATED,
                repairAvailable=true,internetEvidence=InternetEvidence.PORTAL_REQUIRED,internetAt=System.currentTimeMillis())
            stage="eligible-cancel-and-duplicate-click"
            runOnMainSync {
                SessionState.change { ready };button("更多").performClick();button("修复网络").performClick()
                val d=dialog();repeat(10){button("修复网络").performClick()};check(dialog()===d)
                check(d.getButton(AlertDialog.BUTTON_POSITIVE).text.toString()=="开始修复")
                d.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()
            }
            check(SessionService.instancesCreated.get()==serviceCount);cases.put(stage)
            for(replacement in listOf(ready.copy(generation=78),ready.copy(phase=Phase.STOPPED,repairAvailable=false))) {
                stage="stale-confirmation-${replacement.phase}-${replacement.generation}"
                runOnMainSync {
                    SessionState.change { ready };button("修复网络").performClick()
                    SessionState.change { replacement }
                    dialog().getButton(AlertDialog.BUTTON_POSITIVE).performClick()
                }
                waitForIdleSync();Thread.sleep(100)
                check(SessionService.instancesCreated.get()==serviceCount);cases.put(stage)
            }
            SessionState.change { SessionSnapshot() }
            File(targetContext.filesDir,"repair-menu-result.json").writeText(JSONObject().put("status","PASS")
                .put("api",android.os.Build.VERSION.SDK_INT).put("model",android.os.Build.MODEL)
                .put("cases",cases).put("serviceCommands",0).toString(2))
            finish(-1,Bundle().apply{putString("result","PASS: persistent repair entry, eligibility explanations, cancel, duplicate click and stale confirmation guards; no network actions")})
        } catch(t:Throwable) {
            finish(0,Bundle().apply{putString("result","FAIL $stage ${t.javaClass.simpleName}")})
        } finally { activity?.let { a -> runOnMainSync { a.finish() } } }
    }
}
