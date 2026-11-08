package org.esurfing.hunan

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.accessibility.AccessibilityNodeInfo
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/** Isolated synthetic UI only. Business buttons receive DOWN/CANCEL, never UP/click. */
class UiProbe : Instrumentation() {
    @Volatile private var resumedActivity: Activity? = null
    private val titles = listOf("连接", "账号", "诊断", "更多")
    private val rows = JSONArray()
    private val controls = JSONArray()
    private val independentFailures = JSONArray()
    private var popupDebug: JSONObject? = null

    private lateinit var activity: Activity
    private var step = "setup"

    override fun callActivityOnResume(activity: Activity) {
        super.callActivityOnResume(activity); resumedActivity = activity
    }
    override fun callActivityOnPause(activity: Activity) {
        if (resumedActivity === activity) resumedActivity = null
        super.callActivityOnPause(activity)
    }
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    private fun views(v: View): List<View> = listOf(v) +
        if (v is ViewGroup) (0 until v.childCount).flatMap { views(v.getChildAt(it)) } else emptyList()
    private fun <T> onMain(action: () -> T): T {
        var value: T? = null; var failure: Throwable? = null
        runOnMainSync { try { value = action() } catch (t: Throwable) { failure = t } }
        failure?.let { throw it }
        @Suppress("UNCHECKED_CAST")
        return value as T
    }
    private fun settle() { waitForIdleSync(); SystemClock.sleep(250) }
    private fun awaitCondition(message: String, condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 5000
        while (!condition()) {
            check(SystemClock.elapsedRealtime() < deadline) { message }; SystemClock.sleep(100)
        }
    }
    private fun tab(title: String): Button = views(activity.window.decorView)
        .filterIsInstance<Button>().single { it.text.toString() == title }
    private fun currentScroll(): ScrollView = views(activity.window.decorView)
        .filterIsInstance<ScrollView>().single { it.isShown }
    private fun bounds(view: View): Rect {
        val xy = IntArray(2); view.getLocationOnScreen(xy)
        return Rect(xy[0], xy[1], xy[0] + view.width, xy[1] + view.height)
    }
    private fun safeBounds(): Rect {
        val root = activity.window.decorView
        val safe = bounds(root)
        val visibleFrame = Rect(); root.getWindowVisibleDisplayFrame(visibleFrame)
        check(safe.intersect(visibleFrame)) { "Empty visible window" }
        if (Build.VERSION.SDK_INT >= 30) {
            val insets = checkNotNull(root.rootWindowInsets)
            val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            val ime = insets.getInsets(WindowInsets.Type.ime())
            val screen = bounds(root)
            check(safe.intersect(Rect(screen.left + bars.left, screen.top + bars.top,
                screen.right - bars.right, screen.bottom - maxOf(bars.bottom, ime.bottom)))) {
                "No content area outside system bars, cutout and keyboard"
            }
        }
        return safe
    }
    private fun textFits(view: TextView): Boolean {
        val layout = view.layout ?: return false
        if (layout.lineCount == 0) return true
        val contentWidth = view.width - view.compoundPaddingLeft - view.compoundPaddingRight
        return layout.getLineBottom(layout.lineCount - 1) <= view.height - view.compoundPaddingTop - view.compoundPaddingBottom &&
            (0 until layout.lineCount).all {
                layout.getEllipsisCount(it) == 0 && (view is EditText ||
                    (layout.getLineLeft(it) >= -1f && layout.getLineRight(it) <= contentWidth + 1f))
            }
    }
    private fun assertControl(view: View, label: String): JSONObject {
        check(view.isShown && view.width > 0 && view.height > 0) { "Control hidden: $label" }
        val actual = bounds(view); val local = Rect()
        val full = view.getLocalVisibleRect(local) && local.contains(0, 0, view.width, view.height)
        check(full && safeBounds().contains(actual)) { "Control obscured: $label" }
        val fits = view !is TextView || textFits(view)
        check(fits) { "Control text clipped: $label" }
        return JSONObject().put("label", label).put("bounds", actual.toShortString())
            .put("safeBounds", safeBounds().toShortString()).put("fullyVisible", true)
            .put("textFits", fits).put("enabled", view.isEnabled).put("clickable", view.isClickable)
    }
    private fun scrollTo(view: View) {
        onMain { view.requestRectangleOnScreen(Rect(0, 0, view.width, view.height), true) }; settle()
    }
    private fun touch(view: View, completeClick: Boolean) {
        val box = onMain {
            check(resumedActivity === activity && activity.hasWindowFocus()) { "Touch target activity is not foreground" }
            if (completeClick) check(view is Spinner || (view is Button && (view.text.toString() in titles || view.text.toString() == "高级设置  ＋"))) {
                "Complete click is restricted to navigation and local selection controls"
            }
            assertControl(view, "touch target"); bounds(view)
        }
        val downTime = SystemClock.uptimeMillis()
        fun inject(action: Int) {
            val event = MotionEvent.obtain(downTime, SystemClock.uptimeMillis(), action,
                box.exactCenterX(), box.exactCenterY(), 0)
            try { sendPointerSync(event) } finally { event.recycle() }
        }
        var released = false
        try {
            inject(MotionEvent.ACTION_DOWN)
            if (completeClick) { inject(MotionEvent.ACTION_UP); released = true }
            else {
                SystemClock.sleep((ViewConfiguration.getTapTimeout() + 30).toLong())
                check(onMain { view.isPressed }) { "Touch missed intended button" }
            }
        } finally { if (!released) inject(MotionEvent.ACTION_CANCEL) }
        settle()
    }
    private fun windowSelectedTitle(node: AccessibilityNodeInfo): List<String> {
        val found = mutableListOf<String>()
        if (node.isVisibleToUser && node.isSelected && node.text?.toString() in titles) found.add(node.text.toString())
        for (i in 0 until node.childCount) node.getChild(i)?.let { child ->
            try { found.addAll(windowSelectedTitle(child)) } finally { child.recycle() }
        }
        return found
    }
    private fun assertPage(expected: Int): JSONObject {
        val actual = onMain {
            check(resumedActivity === activity && activity.hasWindowFocus()) { "Activity instance is not foreground" }
            val selected = titles.filter { tab(it).isSelected }
            check(selected == listOf(titles[expected])) { "Selected tab differs from expected page" }
            val scroll = currentScroll()
            val text = views(scroll).filterIsInstance<TextView>().map { it.text.toString() }
            val markers = listOf("账号和密码在“账号”页管理。", "校园网账号", "诊断日志", "修复网络")
            check(markers[expected] in text) { "Visible page content differs from selected tab" }
            check(views(scroll).filterIsInstance<EditText>().isNotEmpty() == (expected == 1)) { "Unexpected input-page identity" }
            val header = views(activity.window.decorView).filterIsInstance<TextView>().single { it.text.toString() == "校园网" }
            assertControl(header, "校园网"); titles.forEach { assertControl(tab(it), it) }
            JSONObject().put("pageIndex", expected).put("pageTitle", selected.single()).put("contentMarker", markers[expected])
                .put("activity", activity.javaClass.name).put("activityInstance", System.identityHashCode(activity))
                .put("safeBounds", safeBounds().toShortString())
        }
        var observed: AccessibilityNodeInfo? = null
        awaitCondition("Active accessibility window did not match the focused page") {
            val node = uiAutomation.rootInActiveWindow
            if (node != null && node.packageName?.toString() == targetContext.packageName &&
                windowSelectedTitle(node) == listOf(titles[expected])) {
                observed = node; true
            } else { node?.recycle(); false }
        }
        val active = checkNotNull(observed)
        try {
            check(active.packageName?.toString() == targetContext.packageName) { "Foreign foreground package" }
            check(windowSelectedTitle(active) == listOf(titles[expected])) { "Foreground screenshot page differs from activity" }
            actual.put("foregroundPackage", active.packageName.toString()).put("windowId", active.windowId)
        } finally { active.recycle() }
        return actual
    }
    private fun snap(name: String, page: Int) {
        step = name; settle()
        val row = assertPage(page).put("name", name)
        val image = checkNotNull(uiAutomation.takeScreenshot())
        val file = File(targetContext.filesDir, "ui-$name.png")
        try { file.outputStream().use { check(image.compress(Bitmap.CompressFormat.PNG, 100, it)) } }
        finally { image.recycle() }
        val after = assertPage(page)
        check(row.getInt("windowId") == after.getInt("windowId")) { "Window changed during screenshot" }
        row.put("screenshot", file.name).put("sha256", MessageDigest.getInstance("SHA-256")
            .digest(file.readBytes()).joinToString("") { "%02x".format(it.toInt() and 255) })
        onMain {
            val root = activity.window.decorView
            row.put("displayBounds", bounds(root).toShortString())
            if (Build.VERSION.SDK_INT >= 30) {
                val inset = checkNotNull(root.rootWindowInsets)
                row.put("imeVisible", inset.isVisible(WindowInsets.Type.ime()))
                    .put("systemInsets", inset.getInsets(WindowInsets.Type.systemBars()).toString())
                    .put("cutoutInsets", inset.getInsets(WindowInsets.Type.displayCutout()).toString())
                    .put("imeInsets", inset.getInsets(WindowInsets.Type.ime()).toString())
            }
        }
        rows.put(row)
    }
    private fun hideKeyboard() {
        onMain { activity.getSystemService(InputMethodManager::class.java)
            .hideSoftInputFromWindow(activity.window.decorView.windowToken, 0) }; settle()
        if (Build.VERSION.SDK_INT >= 30) awaitCondition("Keyboard failed to hide") {
            onMain { activity.window.decorView.rootWindowInsets?.isVisible(WindowInsets.Type.ime()) == false }
        }
    }
    private fun imeVisible(): Boolean {
        if (Build.VERSION.SDK_INT >= 30)
            return activity.window.decorView.rootWindowInsets?.isVisible(WindowInsets.Type.ime()) == true
        // adjustResize shrinks the pre-30 decor. Compare the visible frame with
        // the physical display, not the already resized decor height.
        val frame = Rect(); activity.window.decorView.getWindowVisibleDisplayFrame(frame)
        val metrics = android.util.DisplayMetrics()
        @Suppress("DEPRECATION")
        activity.windowManager.defaultDisplay.getRealMetrics(metrics)
        return metrics.heightPixels - frame.bottom > activity.resources.displayMetrics.density * 100
    }
    private fun focusWithKeyboard(field: EditText, label: String, screenshot: String) {
        step = screenshot
        scrollTo(field)
        onMain { check(field.requestFocus()) { "Input could not obtain focus" } }
        // IMM learns the served editor on the next UI traversal, not within the
        // same callback that changed focus. Keep this separate from requestFocus.
        settle()
        onMain { activity.getSystemService(InputMethodManager::class.java)
            .showSoftInput(field, InputMethodManager.SHOW_IMPLICIT) }
        awaitCondition("Keyboard did not become visible") { onMain { imeVisible() } }
        scrollTo(field)
        controls.put(onMain { assertControl(field, label) }
            .put("pageIndex", 1).put("interaction", "focus-with-visible-keyboard"))
        snap(screenshot, 1)
    }
    private fun verifyDropdown(channel: Spinner) {
        step = "dropdown"
        hideKeyboard(); scrollTo(channel)
        val originatingWindow = assertPage(1).getInt("windowId")
        val options = listOf("iOS 兼容通道 · 优先验证", "旧 Windows 通道 · 未通过放行验收")
        val originalIndex = onMain { channel.selectedItemPosition }
        var popupWindowId: Int? = null
        var popupDismissed = false
        var deferredFailure: Throwable? = null
        fun popupSnapshot(): JSONObject {
            onMain { check(resumedActivity === activity && tab("账号").isSelected) { "Dropdown lost its originating account page" } }
            val safe = onMain { safeBounds() }
            val popup = checkNotNull(uiAutomation.rootInActiveWindow) { "No active popup window" }
            try {
                popupDebug = JSONObject().put("substep", "window-identity").put("originatingWindowId", originatingWindow)
                    .put("windowId", popup.windowId).put("packageMatches", popup.packageName?.toString() == targetContext.packageName)
                    .put("options", JSONArray())
                check(popup.packageName?.toString() == targetContext.packageName && popup.windowId != originatingWindow) {
                    "Active window is not the isolated dropdown"
                }
                popupWindowId = popup.windowId
                val entries = JSONArray()
                options.forEach { option ->
                    val nodes = popup.findAccessibilityNodeInfosByText(option)
                    try {
                        val exact = nodes.filter { it.text?.toString() == option }
                        val matching = nodes.filter { it.isVisibleToUser && it.text?.toString() == option }
                        val diagnostic = JSONObject().put("label",option).put("matchCount",exact.size).put("visibleCount",matching.size)
                            .put("nodes", JSONArray().apply { exact.forEach { node ->
                                val box=Rect(); node.getBoundsInScreen(box)
                                put(JSONObject().put("visible",node.isVisibleToUser).put("bounds",box.toShortString()).put("insideSafeBounds",safe.contains(box)))
                            } })
                        popupDebug!!.getJSONArray("options").put(diagnostic)
                        val box = Rect(); if(matching.size == 1) matching.single().getBoundsInScreen(box)
                        entries.put(JSONObject().put("label", option).put("bounds", box.toShortString())
                            .put("safeBounds", safe.toShortString()).put("fullyVisible", !box.isEmpty && safe.contains(box))
                            .put("textLayoutStatus", "NOT_RUN").put("manualVisualRequired", true))
                    } finally { nodes.forEach { it.recycle() } }
                }
                popupDebug!!.put("substep", "option-exact-visible")
                val diagnostics=popupDebug!!.getJSONArray("options")
                check((0 until diagnostics.length()).all { diagnostics.getJSONObject(it).getInt("visibleCount") == 1 }) {
                    "Popup exact visible option mismatch"
                }
                popupDebug!!.put("substep", "option-safe-bounds")
                check((0 until entries.length()).all { entries.getJSONObject(it).getBoolean("fullyVisible") }) {
                    "Popup option is outside safe area"
                }
                popupDebug!!.put("substep", "complete")
                return JSONObject().put("windowId", popup.windowId).put("options", entries)
            } finally { popup.recycle() }
        }
        try {
            step = "dropdown-open"
            // Exercise the original adapter unchanged. Accessibility identifies
            // the real popup; its painted text is checked in the visual review.
            touch(channel, true)
            var observed: JSONObject? = null
            awaitCondition("Both exact visible dropdown options did not appear") {
                try { observed = popupSnapshot(); true } catch (_: IllegalStateException) { false }
            }
            val before = checkNotNull(observed)
            val file = File(targetContext.filesDir, "ui-dropdown.png")
            val bitmap = checkNotNull(uiAutomation.takeScreenshot())
            try { file.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) } }
            finally { bitmap.recycle() }
            val after = popupSnapshot()
            check(before.toString() == after.toString()) { "Dropdown window or option bounds changed during screenshot" }
            rows.put(JSONObject().put("name", "dropdown").put("pageIndex", 1).put("pageTitle", "账号")
                .put("captureKind", "channel-dropdown").put("activity", activity.javaClass.name)
                .put("activityInstance", System.identityHashCode(activity)).put("foregroundPackage", targetContext.packageName)
                .put("windowId", before.getInt("windowId")).put("popupOptions", before.getJSONArray("options"))
                .put("manualVisualRequired", true).put("textLayoutStatus", "NOT_RUN").put("adapterUnchanged", true)
                .put("screenshot", file.name).put("sha256", MessageDigest.getInstance("SHA-256").digest(file.readBytes())
                    .joinToString("") { "%02x".format(it.toInt() and 255) }))
            step = "dropdown-cancel"
            sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
            popupDismissed = true
            settle(); assertPage(1)
            check(onMain { channel.selectedItemPosition == originalIndex }) { "Cancelling dropdown changed the selected option" }
            controls.put(JSONObject().put("label", "认证通道下拉选项").put("pageIndex", 1)
                .put("interaction", "open-original-popup-and-back-cancel").put("businessClickInvoked", false)
                .put("selectedIndexBefore", originalIndex).put("selectedIndexAfter", originalIndex)
                .put("textLayoutStatus", "NOT_RUN").put("manualVisualRequired", true))
        } catch (failure: Throwable) {
            val active = uiAutomation.rootInActiveWindow
            try {
                if(active?.packageName?.toString() == targetContext.packageName && resumedActivity === activity) {
                    val file = File(targetContext.filesDir, "ui-dropdown-failure.png")
                    val bitmap = checkNotNull(uiAutomation.takeScreenshot())
                    try { file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) } } finally { bitmap.recycle() }
                    rows.put(JSONObject().put("name", "dropdown-failure").put("pageIndex", 1).put("pageTitle", "账号")
                        .put("captureKind", "dropdown-diagnostic-only").put("foregroundPackage", targetContext.packageName)
                        .put("windowId", active.windowId).put("screenshot", file.name)
                        .put("sha256", MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it.toInt() and 255) }))
                }
            } finally { active?.recycle() }
            deferredFailure = failure
        } finally {
            if (!popupDismissed && popupWindowId != null) {
                val active = uiAutomation.rootInActiveWindow
                val stillPopup = active?.windowId == popupWindowId && active?.packageName?.toString() == targetContext.packageName
                active?.recycle()
                if (stillPopup) { sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK); settle() }
            }
        }
        step = "dropdown-return-to-account"
        assertPage(1)
        check(onMain { channel.selectedItemPosition == originalIndex }) { "Dropdown cleanup changed the selected option" }
        deferredFailure?.let { failure ->
            independentFailures.put(JSONObject().put("testId", "channel-dropdown").put("status", "FAIL")
                .put("reason",failure.message).put("substep",popupDebug?.optString("substep")))
        }
    }
    override fun onStart() {
        val report = JSONObject().put("testId", "S1-UI").put("api", Build.VERSION.SDK_INT).put("model", Build.MODEL)
            .put("fullVisualAcceptance", "NOT_RUN").put("businessClicks", 0).put("systemBarVisualReviewRequired", true)
        val serviceCount = SessionService.instancesCreated.get()
        try {
            check(targetContext.packageName == "org.esurfing.hunan.isolation")
            check(!SessionState.snapshot().configurationBlocked()) { "An isolated session is still active" }
            val prefs = targetContext.getSharedPreferences("settings", 0)
            check(prefs.edit().clear().putBoolean("manualOff", true).putString("username", "synthetic-ui-user").commit())
            Credentials(targetContext).clear()
            activity = startActivitySync(Intent(targetContext, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
            awaitCondition("MainActivity did not obtain focus") { onMain { resumedActivity === activity && activity.hasWindowFocus() } }
            val automation = uiAutomation
            automation.serviceInfo = automation.serviceInfo.apply {
                flags = flags or android.accessibilityservice.AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            }
            automation.waitForIdle(200, 5000)
            report.put("fontScale", activity.resources.configuration.fontScale)
            for (page in titles.indices) {
                step = "select-page$page"; hideKeyboard(); touch(onMain { tab(titles[page]) }, true)
                snap("page$page", page)
                val buttons = onMain { views(currentScroll()).filterIsInstance<Button>().filter { it.isShown } }
                for ((index, button) in buttons.withIndex()) {
                    step = "page$page-control$index"; scrollTo(button)
                    val row = onMain { assertControl(button, button.text.toString()) }
                    check(button.isEnabled && button.isClickable) { "Required button disabled" }
                    touch(button, false)
                    controls.put(row.put("pageIndex", page).put("interaction", "touch-down-cancel").put("businessClickInvoked", false))
                }
                onMain { currentScroll().fullScroll(View.FOCUS_DOWN) }; settle(); snap("page$page-bottom", page)
                if (page == 1) {
                    val inputs = onMain { views(currentScroll()).filterIsInstance<EditText>().filter { it.isShown } }
                    check(inputs.size == 2) { "Expected account and password fields before advanced settings" }
                    for ((index, field) in inputs.withIndex()) {
                        focusWithKeyboard(field, if (index == 0) "账号输入" else "密码输入",
                            if (index == 0) "keyboard" else "keyboard-password")
                    }
                    hideKeyboard()
                    val toggle = onMain { views(currentScroll()).filterIsInstance<Button>().single { it.text.toString() == "高级设置  ＋" } }
                    scrollTo(toggle); touch(toggle, true)
                    val channel = onMain { views(currentScroll()).filterIsInstance<Spinner>().single { it.isShown } }
                    scrollTo(channel)
                    controls.put(onMain {
                        val selected = channel.selectedView as TextView
                        check(selected.text.toString() == "iOS 兼容通道 · 优先验证") { "Channel option/index changed" }
                        assertControl(selected, "认证通道当前选项")
                    }.put("pageIndex", 1).put("interaction", "selected-option-text-without-ellipsis"))
                    verifyDropdown(channel)
                    step = "advanced-input-set"
                    val advancedInputs = onMain { views(currentScroll()).filterIsInstance<EditText>().filter { it.isShown }.drop(2) }
                    val advancedLabels = listOf("门户覆盖输入", "IPv4输入", "默认网关输入", "MAC输入", "mscgip输入", "主机名输入")
                    check(advancedInputs.size == advancedLabels.size) { "Advanced input set is incomplete" }
                    for ((index, field) in advancedInputs.withIndex()) {
                        step = "advanced-input-$index-visibility"
                        scrollTo(field)
                        controls.put(onMain { assertControl(field, advancedLabels[index]) }
                            .put("pageIndex", 1).put("interaction", "scrolled-into-safe-area"))
                        if (index == 0 || index == advancedInputs.lastIndex) {
                            val name = if (index == 0) "advanced-first" else "advanced-last"
                            snap(name, 1)
                            focusWithKeyboard(field, advancedLabels[index], "$name-keyboard")
                            hideKeyboard()
                        }
                    }
                    scrollTo(toggle); touch(toggle, true)
                }
            }
            check(SessionService.instancesCreated.get() == serviceCount) { "UI probe created a session service" }
            report.put("status", if(independentFailures.length() == 0) "PASS" else "FAIL").put("sessionServicesCreated", 0)
            if(independentFailures.length() > 0) report.put("failedStep", "independent-dropdown-check")
        } catch (t: Throwable) {
            report.put("status", "FAIL").put("failedStep", step).put("exception", t.javaClass.simpleName)
                .put("reason", t.message).put("line", t.stackTrace.firstOrNull { it.fileName == "UiProbe.kt" }?.lineNumber)
        } finally {
            if (::activity.isInitialized) {
                try { hideKeyboard() } catch (_: Throwable) { }
                onMain { activity.finish() }
            }
        }
        report.put("screens", rows).put("controls", controls).put("independentFailures", independentFailures).put("popupDebug",popupDebug)
        File(targetContext.filesDir, "ui-result.json").writeText(report.toString(2))
        finish(if (report.optString("status") == "PASS") -1 else 0, Bundle().apply { putString("result", report.toString()) })
    }
}
