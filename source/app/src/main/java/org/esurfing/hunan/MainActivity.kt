package org.esurfing.hunan

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.*
import android.text.InputType
import android.view.View
import android.widget.*

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private val fields = linkedMapOf<String, EditText>()
    private val pages = mutableListOf<ScrollView>()
    private val nav = mutableListOf<Button>()
    private lateinit var status: TextView
    private lateinit var logs: TextView
    private lateinit var runtime: TextView
    private lateinit var channel: Spinner
    private lateinit var repairButton: Button
    private lateinit var repairNote: TextView
    private var repairDialog: AlertDialog? = null
    private lateinit var loginButton: Button
    private lateinit var logoutButton: Button
    private lateinit var stopButton: Button
    private lateinit var statusNote: TextView
    private lateinit var diagnosticState: TextView
    private lateinit var backgroundStatus: TextView
    private lateinit var backgroundReminder: TextView
    private var backgroundDialog: AlertDialog? = null
    @Volatile private var diagnosing = false
    private val prefs by lazy { getSharedPreferences("settings", MODE_PRIVATE) }
    private val refresh = object : Runnable {
        override fun run() {
            val snapshot = SessionState.snapshot()
            val now = System.currentTimeMillis()
            val fresh = snapshot.internetAt > 0 && now - snapshot.internetAt in 0..600_000
            val online = snapshot.phase == Phase.AUTHENTICATED && fresh && snapshot.internetEvidence == InternetEvidence.HTTPS_VERIFIED
            val active = snapshot.configurationBlocked()
            repairButton.isEnabled = canRepair(snapshot)
            repairButton.visibility = if(repairButton.isEnabled) View.VISIBLE else View.GONE
            repairNote.text = repairExplanation(snapshot, now)
            loginButton.isEnabled = !snapshot.repairing
            loginButton.visibility = if(active) View.GONE else View.VISIBLE
            stopButton.visibility = if(active || snapshot.repairing) View.VISIBLE else View.GONE
            stopButton.text = if(snapshot.repairing) "取消修复并停止" else "停止连接"
            logoutButton.isEnabled = !snapshot.repairing && snapshot.phase != Phase.LOGGING_OUT
            status.text = when {
                snapshot.repairing -> "正在修复"
                online -> "已连接"
                snapshot.phase == Phase.AUTHENTICATED && fresh && snapshot.internetEvidence == InternetEvidence.PORTAL_REQUIRED -> "外网尚未放行"
                snapshot.phase == Phase.AUTHENTICATED -> "外网待确认"
                snapshot.phase == Phase.AUTHENTICATING -> "正在连接"
                snapshot.phase == Phase.WAITING_WIFI -> "等待校园 Wi-Fi"
                snapshot.phase == Phase.DISCOVERING -> "正在发现门户"
                snapshot.phase == Phase.LOGGING_OUT -> "正在注销"
                snapshot.phase == Phase.RECOVERING -> "正在恢复"
                snapshot.phase == Phase.NEEDS_INPUT -> "需要检查连接"
                snapshot.phase == Phase.LOGGED_OUT -> "已注销"
                snapshot.phase == Phase.INTERRUPTED -> "连接已中断"
                else -> "尚未连接"
            }
            status.setTextColor(if(online) Color.rgb(29,109,80) else Color.rgb(35,49,66))
            statusNote.text = when {
                snapshot.repairing && snapshot.nextRecoveryAt > now -> "旧会话已注销，${(snapshot.nextRecoveryAt-now+999)/1000} 秒后重新连接。"
                snapshot.repairing -> snapshot.status
                online -> "Wi-Fi 外网检测通过 · " + java.text.SimpleDateFormat("HH:mm",java.util.Locale.CHINA).format(java.util.Date(snapshot.internetAt))
                snapshot.repairAvailable -> "账号认证已接受，可以尝试修复当前会话。"
                snapshot.phase == Phase.AUTHENTICATED -> "账号认证已接受，外网暂未确认可用。"
                snapshot.phase == Phase.IDLE -> "先连接校园 Wi-Fi，再开始连接。"
                snapshot.phase == Phase.STOPPED -> "本机服务已停止，服务器会话未注销。"
                else -> snapshot.status
            }
            diagnosticState.text = snapshot.display(now)
            logs.text = SessionState.logs()
            runtime.text = snapshot.details
            handler.postDelayed(this, 1000)
        }
    }
    private fun dp(n: Int) = (n * resources.displayMetrics.density).toInt()
    private fun label(column: LinearLayout, text: String, size: Float = 15f): TextView = TextView(this).apply {
        this.text = text; textSize = size; setTextColor(Color.rgb(35, 49, 66)); setPadding(0, dp(12), 0, dp(6)); column.addView(this)
    }
    private fun input(column: LinearLayout, key: String, title: String, default: String = "", password: Boolean = false) {
        label(column, title)
        val view = EditText(this).apply {
            setSingleLine(true)
            inputType = if(password) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            setText(if(password) "" else prefs.getString(key,default))
            hint = if(password) "留空保留已保存密码" else title
            importantForAutofill = android.view.View.IMPORTANT_FOR_AUTOFILL_NO
        }
        fields[key] = view; column.addView(view)
    }
    private fun button(column: LinearLayout, text: String, action: () -> Unit) = Button(this).apply {
        this.text = text; setAllCaps(false); textSize = 16f
        setTextColor(Color.rgb(29,109,80))
        background = GradientDrawable().apply { setColor(Color.rgb(230,239,233)); cornerRadius=dp(12).toFloat() }
        stateListAnimator=null
        minimumHeight=dp(52)
        setPadding(dp(12),dp(12),dp(12),dp(12))
        layoutParams=LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(12) }
        setOnClickListener { action() }; column.addView(this)
    }
    private fun showPage(index: Int) {
        pages.forEachIndexed { i, page -> page.visibility = if(i==index) android.view.View.VISIBLE else android.view.View.GONE }
        nav.forEachIndexed { i, b -> b.isSelected = i==index; b.alpha = if(i==index) 1f else .55f }
        // Keep focus on the newly selected scroll container. Otherwise Android
        // can focus a button near the bottom and scroll it back into view after
        // the periodically refreshed diagnostic text requests layout.
        pages[index].apply {
            isFocusableInTouchMode = true
            descendantFocusability = android.view.ViewGroup.FOCUS_BEFORE_DESCENDANTS
            requestFocus()
            post { scrollTo(0,0) }
        }
    }
    private fun canRepair(state: SessionSnapshot) = state.repairAvailable &&
        state.phase == Phase.AUTHENTICATED && !state.repairing

    private fun repairExplanation(state: SessionSnapshot, now: Long): String = when {
        state.repairing && state.nextRecoveryAt > now ->
            "旧会话已注销，约 ${(state.nextRecoveryAt-now+999)/1000} 秒后登录一次。可到“连接”页取消修复并停止。"
        state.repairing -> "正在修复当前会话。可到“连接”页查看进度或取消修复并停止。"
        canRepair(state) -> "已确认当前会话持续受到门户拦截，可以尝试修复。点击后需再次确认。"
        state.phase == Phase.LOGGING_OUT -> "正在注销，请等待结果。结束后需手动连接。"
        state.phase in listOf(Phase.WAITING_WIFI, Phase.DISCOVERING, Phase.AUTHENTICATING, Phase.RECOVERING) ->
            "当前连接尚未完成，请先查看“连接”页的状态。"
        state.phase == Phase.AUTHENTICATED && state.internetEvidence == InternetEvidence.HTTPS_VERIFIED &&
            state.internetAt > 0 && now - state.internetAt in 0..600_000 ->
            "最近外网检测通过，暂不需要修复。"
        state.phase == Phase.AUTHENTICATED ->
            "暂未满足修复条件。需连续确认校园网仍要求登录，单次检测失败不会启动修复；每次连接服务最多修复一次。"
        else -> "当前没有可修复的活动会话，请先到“连接”页手动连接。"
    }

    private fun showRepairPrompt() {
        if (repairDialog?.isShowing == true) return
        val state = SessionState.snapshot()
        val dialog = AlertDialog.Builder(this)
        if (canRepair(state)) {
            dialog.setTitle("修复当前连接？")
                .setMessage("将注销当前会话，确认后按客户端策略等待 100 秒，再登录一次。该等待不是已确认的服务器要求。过程中可随时取消并停止；失败后不会循环重试。")
                .setNegativeButton("取消", null)
                .setPositiveButton("开始修复") { _, _ ->
                    val current = SessionState.snapshot()
                    if (current.generation == state.generation && canRepair(current)) command("repair")
                    else toast("连接状态已变化，请重新检查后再修复。")
                }
        } else {
            dialog.setTitle("修复网络")
                .setMessage(repairExplanation(state, System.currentTimeMillis()))
                .setNegativeButton("知道了", null)
                .setPositiveButton("查看连接") { _, _ -> showPage(0) }
        }
        repairDialog = dialog.create().also { it.show() }
    }

    private fun command(action: String) = startForegroundService(Intent(this, SessionService::class.java).setAction(action))
    private fun refreshBackgroundAccess() {
        val access = BackgroundAccess.read(this)
        backgroundStatus.text = access.summary()
        backgroundReminder.text = access.reminder()
    }
    private fun showBatteryPrompt() {
        if(backgroundDialog?.isShowing == true) return
        backgroundDialog = AlertDialog.Builder(this).setTitle("允许锁屏后台运行？")
            .setMessage("校园网需要按服务器要求发送心跳。电池优化可能在长时间锁屏后限制网络和唤醒，使连接中断。允许后台运行可能增加待机耗电；仅在你手动连接后维持会话，不会自动开机登录。\n\n接下来由系统询问是否允许。你也可以暂不开启，仍可正常尝试连接。")
            .setNegativeButton("暂不开启", null)
            .setPositiveButton("允许后台运行") { _, _ -> BackgroundAccess.requestBatteryExemption(this) }
            .create().also { it.show() }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SessionState.initialize(this)
        val root=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setBackgroundColor(Color.rgb(246,248,246)); setPadding(dp(20),dp(12),dp(20),0) }
        label(root,"校园网",26f).setTypeface(null,Typeface.BOLD)
        val tabs=LinearLayout(this); root.addView(tabs)
        val content=FrameLayout(this); root.addView(content,LinearLayout.LayoutParams(-1,0,1f))
        val columns=(0..3).map {
            val column=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(4),dp(8),dp(4),dp(24)) }
            val page=ScrollView(this).apply { addView(column); isFillViewport=true }
            pages.add(page); content.addView(page,FrameLayout.LayoutParams(-1,-1)); column
        }
        listOf("连接","账号","诊断","更多").forEachIndexed { i,name ->
            val tab=Button(this).apply { text=name; setAllCaps(false); minHeight=dp(48); setPadding(0,dp(8),0,dp(8)); setOnClickListener { showPage(i) } }
            nav.add(tab); tabs.addView(tab,LinearLayout.LayoutParams(0,-2,1f))
        }
        val home=columns[0]
        val settings=columns[1]
        status=label(home,"尚未连接",28f).apply {
            setTypeface(null,Typeface.BOLD); setPadding(dp(20),dp(28),dp(20),dp(28))
            background=GradientDrawable().apply { setColor(Color.WHITE); cornerRadius=dp(16).toFloat() }
        }
        statusNote=label(home,"连接校园 Wi-Fi 后开始。",15f)
        backgroundReminder = label(home, "", 13f)
        repairButton = button(home,"修复连接") { showRepairPrompt() }
            .apply { isEnabled = false; visibility=View.GONE }
        label(settings,"校园网账号",22f)
        input(settings,"username","账号")
        input(settings,"password","密码",password=true)
        label(settings,"密码加密保存在本机；留空保留已保存密码。",13f)
        loginButton = button(home,"连接校园网") {
            try {
                val current = SessionState.snapshot()
                check(!current.configurationBlocked()) { current.configurationBlockMessage() }
                require(fields.getValue("username").text.toString().trim().isNotBlank()) { "请输入账号" }
                val password=fields.getValue("password").text.toString()
                if(password.isNotEmpty()) Credentials(this).save(password)
                require(Credentials(this).load().isNotBlank()) { "请输入密码" }
                val changed = password.isNotEmpty() || fields.filterKeys { it != "password" }.any { (k,v) -> prefs.getString(k, "").orEmpty() != v.text.toString().trim() } || prefs.getString("channel", "ios") != if(channel.selectedItemPosition==0) "ios" else "windows"
                val edit=prefs.edit()
                if(changed) edit.putLong("configRevision", prefs.getLong("configRevision", 0) + 1)
                fields.filterKeys { it!="password" }.forEach { (k,v)->edit.putString(k,v.text.toString().trim()) }
                edit.putString("channel",if(channel.selectedItemPosition==0) "ios" else "windows")
                check(edit.commit()) { "配置保存失败" }
                fields.getValue("password").setText("")
                command("start")
                // Reserve the UI immediately, before the asynchronous service command arrives.
                SessionState.change { it.copy(desired = true, phase = Phase.WAITING_WIFI, status = "正在启动连接") }
                toast("已启动；登录可能影响同账号其他设备")
            } catch(e:Exception) { showPage(1); toast(e.message ?: "操作失败") }
        }
        loginButton.setTextColor(Color.WHITE)
        loginButton.background=GradientDrawable().apply { setColor(Color.rgb(29,109,80)); cornerRadius=dp(12).toFloat() }
        button(settings,"保存并连接") {
            val current = SessionState.snapshot()
            if(current.configurationBlocked()) toast(current.configurationBlockMessage())
            else { showPage(0); loginButton.performClick() }
        }
        stopButton=button(home,"停止连接") { command("stop") }
        label(home,"账号和密码在“账号”页管理。",13f)
        button(home,"检查后台运行设置") { showPage(3) }
        button(columns[3],"修复网络") { showRepairPrompt() }
        repairNote = label(columns[3], repairExplanation(SessionState.snapshot(), System.currentTimeMillis()), 13f)
        logoutButton = button(columns[3],"注销并停止") {
            AlertDialog.Builder(this).setTitle("注销校园网？").setMessage("将请求服务器结束当前会话，并停止连接。")
                .setNegativeButton("取消",null).setPositiveButton("注销") { _,_ -> command("logout") }.show()
        }
        label(columns[3],"“停止连接”只停止本机服务，不注销服务器会话。",13f)
        label(columns[3],"后台运行",22f)
        backgroundStatus = label(columns[3], "", 15f)
        label(columns[3],"建议连接前检查以下设置。未开启仍可连接；精确定时和电池豁免也不能保证永久保活。",13f)
        label(columns[3],"连接中修改权限后，新设置从后续任务计划生效；如需立即应用，请停止后手动连接。",13f)
        button(columns[3],"后台定时权限") { BackgroundAccess.openExact(this) }
        button(columns[3],"允许后台运行") { showBatteryPrompt() }
        button(columns[3],"连接通知设置") { BackgroundAccess.requestNotifications(this) }
        label(columns[3],"部分手机还需在系统应用详情中允许后台活动、取消省电限制，或在最近任务中锁定应用。realme、小米、vivo 等系统的名称及入口可能不同；应用无法读取这些厂商开关。",13f)
        button(columns[3],"打开系统应用详情") { BackgroundAccess.openAppDetails(this) }
        refreshBackgroundAccess()
        button(columns[2],"检测 Wi-Fi（不登录）") {
            if(diagnosing) toast("诊断正在进行") else {
                diagnosing=true; showPage(2)
                Thread {
                    try { NetworkDiagnostics.run(applicationContext) }
                    catch(e:Exception) { SessionState.log("诊断失败：${e.javaClass.simpleName}") }
                    finally { diagnosing=false }
                }.start()
            }
        }
        val advanced=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; visibility=View.GONE }
        button(settings,"高级设置  ＋") { advanced.visibility=if(advanced.visibility==View.VISIBLE) View.GONE else View.VISIBLE }
        settings.addView(advanced)
        label(advanced,"认证通道",20f)
        channel=Spinner(this).apply {
            val spinner=this
            adapter=object : BaseAdapter() {
                private val options=listOf("iOS 兼容通道 · 优先验证","旧 Windows 通道 · 未通过放行验收")
                override fun getCount()=options.size
                override fun getItem(position: Int)=options[position]
                override fun getItemId(position: Int)=position.toLong()
                private fun row(position: Int, convertView: View?, parent: android.view.ViewGroup): View =
                    ((convertView as? TextView) ?: TextView(this@MainActivity)).apply {
                    // A plain multiline row avoids the platform spinner item's
                    // single-line text appearance and natural-width measurement.
                    text=options[position]
                    textSize=18f
                    setTextColor(Color.rgb(35,49,66))
                    gravity=android.view.Gravity.CENTER_VERTICAL
                    setSingleLine(false)
                    setHorizontallyScrolling(false)
                    maxLines=Int.MAX_VALUE
                    ellipsize=null
                    minimumHeight=dp(48)
                    setPadding(dp(8),dp(8),dp(8),dp(8))
                    if(parent is AbsListView) {
                        // Preserve ListView's private recycling/forceAdd flags.
                        val existing=layoutParams as? AbsListView.LayoutParams
                        if(existing == null) layoutParams=AbsListView.LayoutParams(-1,-2)
                        else { existing.width=-1; existing.height=-2 }
                    } else if(layoutParams == null) layoutParams=android.view.ViewGroup.LayoutParams(-1,-2)
                    maxWidth=if(spinner.width > 0) spinner.width else resources.displayMetrics.widthPixels-dp(48)
                }
                override fun getView(position: Int, convertView: View?, parent: android.view.ViewGroup): View =
                    row(position,convertView,parent)
                override fun getDropDownView(position: Int, convertView: View?, parent: android.view.ViewGroup): View {
                    // DropDownListView forces a root TextView to scroll horizontally
                    // after getDropDownView. Keep the multiline label inside a plain
                    // container so the framework preserves its wrapping behavior.
                    val container=(convertView as? FrameLayout) ?: FrameLayout(this@MainActivity)
                    val label=row(position,container.getChildAt(0),container)
                    if(label.parent == null) container.addView(label)
                    if(label.layoutParams !is FrameLayout.LayoutParams) label.layoutParams=FrameLayout.LayoutParams(-1,-2)
                    label.isClickable=false; label.isFocusable=false
                    container.isClickable=false; container.isFocusable=false
                    val existing=container.layoutParams as? AbsListView.LayoutParams
                    if(existing == null) container.layoutParams=AbsListView.LayoutParams(-1,-2)
                    else { existing.width=-1; existing.height=-2 }
                    return container
                }
            }
            setSelection(if(prefs.getString("channel","ios")=="windows") 1 else 0)
            addOnLayoutChangeListener { view,left,_,right,_,_,_,_,_ ->
                // Use the actual safe content width, including after font/inset
                // changes, instead of the text's unbounded preferred width.
                (view as Spinner).dropDownWidth=(right-left).coerceAtLeast(1)
            }
        }
        advanced.addView(channel)
        label(advanced,"通常无需修改。留空自动识别；修改后点“保存并连接”。",13f)
        input(advanced,"portal","门户覆盖（http://IPv4:端口）")
        input(advanced,"ip","IPv4 · 留空自动")
        input(advanced,"gateway","默认网关 · 留空自动")
        input(advanced,"mac","当前 Wi-Fi MAC · 留空发现")
        input(advanced,"mscgip","mscgip · 留空发现")
        input(advanced,"hostname","主机名 · 可手动覆盖")
        label(advanced,"本次运行参数与来源",18f)
        runtime=label(advanced,SessionState.details,13f)
        button(columns[3],"清除本机账号密码和设置") {
            AlertDialog.Builder(this).setTitle("清除本机配置？").setMessage("客户端将停止；服务器会话不会因此注销。")
                .setNegativeButton("取消",null).setPositiveButton("清除") { _,_ ->
                    command("stop"); Credentials(this).clear(); IdentityCache.clear(this); prefs.edit().clear().commit()
                    fields.values.forEach { it.setText("") }; channel.setSelection(0); toast("已清除本机配置")
                }.show()
        }
        val diagnostics=columns[2]
        label(diagnostics,"诊断日志",22f)
        diagnosticState=label(diagnostics,"",13f)
        label(diagnostics,"详细信息仅供排查；复制时会移除敏感信息。",13f)
        button(diagnostics,"复制脱敏诊断") {
            getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("校园网诊断","${SessionState.export()}"))
            toast("已复制诊断")
        }
        logs=label(diagnostics,SessionState.logs(),13f).apply { setTextIsSelectable(true) }
        val about=columns[3]
        val installedVersion = packageManager.getPackageInfo(packageName, 0).versionName
        label(about,"$installedVersion · 测试版",20f)
        label(about,"当前版本用于校园网连接、会话修复和资源释放流程验证。认证结果与 Wi-Fi 外网可用性分别判断。")
        label(about,"每次连接服务最多修复一次。100 秒为保守等待策略，不代表已确认的服务端冷却时间。锁屏保活和长期稳定性仍需验证。")
        label(about,"认证协议使用 HTTP 与应用层加密，没有 TLS 连接保护。账号密码只在本机加密保存；不上传到开发者服务器。")
        button(about,"查看开源许可") {
            AlertDialog.Builder(this).setTitle("来源与许可").setMessage(assets.open("LICENSES.txt").bufferedReader().use { it.readText() }).setPositiveButton("关闭",null).show()
        }
        if(Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
            window.statusBarColor = Color.TRANSPARENT
            // API 33's tested system image leaves white navigation glyphs on a
            // light transparent background. Use an explicit high-contrast pair.
            val darkNavigation = Build.VERSION.SDK_INT == 33
            window.navigationBarColor = if(darkNavigation) Color.BLACK else Color.TRANSPARENT
            // Some OEM PhoneWindow implementations throw before the decor exists.
            // Run after setContentView/attachment, when the controller is available.
            root.post {
                window.insetsController?.setSystemBarsAppearance(
                    android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or
                        (if(darkNavigation) 0 else android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS),
                    android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS or android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS)
            }
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout())
                val ime = insets.getInsets(android.view.WindowInsets.Type.ime())
                view.setPadding(dp(20)+bars.left,dp(12)+bars.top,dp(20)+bars.right,maxOf(bars.bottom,ime.bottom))
                insets
            }
        }
        setContentView(root); root.requestApplyInsets(); showPage(0)
    }
    private fun toast(text:String)=Toast.makeText(this,text,Toast.LENGTH_LONG).show()
    override fun onResume(){super.onResume();refreshBackgroundAccess();handler.removeCallbacks(refresh);handler.post(refresh)}
    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if(requestCode == BackgroundAccess.NOTIFICATION_REQUEST) refreshBackgroundAccess()
    }
    override fun onPause(){handler.removeCallbacks(refresh);super.onPause()}
    override fun onDestroy(){repairDialog?.dismiss();repairDialog=null;backgroundDialog?.dismiss();backgroundDialog=null;super.onDestroy()}
}






