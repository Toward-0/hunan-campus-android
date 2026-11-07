package org.esurfing.hunan
import android.app.Instrumentation
import android.content.Intent
import android.os.Bundle
import android.os.Build
import android.graphics.Bitmap
import android.graphics.Rect
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.*
import org.json.JSONObject
import org.json.JSONArray
import java.io.File

/** Screenshots are limited to the isolated app, which contains only synthetic settings. */
class UiProbe : Instrumentation() {
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        val rows=JSONArray()
        val report=JSONObject().put("testId","S1-UI").put("api",Build.VERSION.SDK_INT).put("model",Build.MODEL)
        try {
            check(targetContext.packageName=="org.esurfing.hunan.isolation")
            val prefs=targetContext.getSharedPreferences("settings",0)
            check(prefs.edit().clear().putBoolean("manualOff",true).putString("username","synthetic-ui-user").commit())
            Credentials(targetContext).clear()
            val activity=startActivitySync(Intent(targetContext,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(700)
            report.put("fontScale",activity.resources.configuration.fontScale)
            fun views(v: View): List<View> = listOf(v)+if(v is ViewGroup) (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
            fun snap(name: String) {
                waitForIdleSync();Thread.sleep(350)
                var foreground: String? = null
                val deadline=android.os.SystemClock.elapsedRealtime()+5000
                do {
                    foreground=uiAutomation.rootInActiveWindow?.packageName?.toString()
                    if(foreground==targetContext.packageName) break
                    Thread.sleep(100)
                } while(android.os.SystemClock.elapsedRealtime()<deadline)
                report.put("lastForegroundPackage",foreground)
                check(foreground==targetContext.packageName) { "Unexpected foreground; no screenshot captured" }
                val image=checkNotNull(uiAutomation.takeScreenshot())
                File(targetContext.filesDir,"ui-$name.png").outputStream().use { image.compress(Bitmap.CompressFormat.PNG,100,it) };image.recycle()
                val row=JSONObject().put("name",name)
                runOnMainSync {
                    val root=activity.window.decorView
                    val buttons=JSONArray()
                    for(v in views(root).filterIsInstance<Button>().filter { it.isShown }) {
                        val rect=Rect();val visible=v.getGlobalVisibleRect(rect)
                        val textLayout=v.layout
                        val fits=textLayout==null || textLayout.getLineBottom(textLayout.lineCount-1)<=v.height-v.compoundPaddingTop-v.compoundPaddingBottom
                        check(fits) { "Button text clipped" }
                        buttons.put(JSONObject().put("label",v.text.toString()).put("visible",visible).put("bounds",rect.toShortString()).put("textFits",fits))
                    }
                    row.put("buttons",buttons)
                    if(Build.VERSION.SDK_INT>=30) {
                        val inset=root.rootWindowInsets
                        row.put("imeVisible",inset?.isVisible(android.view.WindowInsets.Type.ime()))
                            .put("systemInsets",inset?.getInsets(android.view.WindowInsets.Type.systemBars())?.toString())
                    }
                }
                rows.put(row)
            }
            for((index,label) in listOf("连接","账号","诊断","更多").withIndex()) {
                runOnMainSync { views(activity.window.decorView).filterIsInstance<Button>().first { it.text.toString()==label }.performClick() }
                snap("page$index")
                if(index==1) {
                    runOnMainSync {
                        val field=views(activity.window.decorView).filterIsInstance<EditText>().first { it.isShown }
                        field.requestFocus();activity.getSystemService(InputMethodManager::class.java).showSoftInput(field,InputMethodManager.SHOW_IMPLICIT)
                    }
                    Thread.sleep(800);snap("keyboard")
                    runOnMainSync { activity.getSystemService(InputMethodManager::class.java).hideSoftInputFromWindow(activity.window.decorView.windowToken,0) }
                }
                runOnMainSync { views(activity.window.decorView).filterIsInstance<ScrollView>().first { it.isShown }.fullScroll(View.FOCUS_DOWN) }
                snap("page$index-bottom")
            }
            runOnMainSync { activity.finish() }
            report.put("status","PASS").put("screens",rows)
        } catch(t: Throwable) { report.put("status","FAIL").put("exception",t.javaClass.simpleName).put("line",t.stackTrace.firstOrNull { it.fileName=="UiProbe.kt" }?.lineNumber).put("screens",rows) }
        File(targetContext.filesDir,"ui-result.json").writeText(report.toString(2))
        finish(if(report.optString("status")=="PASS") -1 else 0,Bundle().apply { putString("result",report.toString()) })
    }
}
