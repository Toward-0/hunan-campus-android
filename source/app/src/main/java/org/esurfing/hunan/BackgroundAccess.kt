package org.esurfing.hunan

import android.Manifest
import android.app.Activity
import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast

/** Capabilities only: opening settings never starts or reconnects a session. */
object BackgroundAccess {
    const val NOTIFICATION_REQUEST = 40
    data class Snapshot(val exact: Boolean?, val batteryExempt: Boolean?, val notifications: Boolean?) {
        private fun state(value: Boolean?, yes: String, no: String) = when(value) {
            true -> yes
            false -> no
            null -> "暂时无法读取"
        }
        fun summary() = "后台定时：${state(exact, "可用", "未开启")}\n" +
            "电池优化：${state(batteryExempt, "已豁免", "仍受限制")}\n" +
            "连接通知：${state(notifications, "已开启", "未开启")}"
        fun reminder() = when {
            batteryExempt != true -> "长时间锁屏可能限制心跳，请在“更多 → 后台运行”检查电池优化。"
            exact != true -> "后台定时受限，锁屏后心跳可能延后，可在“更多 → 后台运行”设置。"
            notifications != true -> "连接通知未开启，可在“更多 → 后台运行”设置，便于查看或停止连接。"
            else -> "后台运行权限已就绪；厂商省电策略仍可能影响锁屏连接。"
        }
    }

    private fun readBoolean(block: () -> Boolean): Boolean? = try { block() } catch (_: RuntimeException) { null }
    fun read(context: Context): Snapshot = Snapshot(
        readBoolean { Build.VERSION.SDK_INT < 31 || context.getSystemService(AlarmManager::class.java).canScheduleExactAlarms() },
        readBoolean { context.getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(context.packageName) },
        readBoolean {
            val notifications = context.getSystemService(NotificationManager::class.java)
            val channel = notifications.getNotificationChannel("session")
            notifications.areNotificationsEnabled() && channel?.importance != NotificationManager.IMPORTANCE_NONE
        }
    )

    private fun appDetails(activity: Activity) = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        Uri.parse("package:${activity.packageName}"))

    private fun open(activity: Activity, vararg candidates: Intent) {
        for(intent in candidates) {
            try { activity.startActivity(intent); return }
            catch (_: RuntimeException) { /* OEM settings may not implement the standard destination. */ }
        }
        Toast.makeText(activity, "系统未提供此设置入口，请在系统设置中查找本应用。", Toast.LENGTH_LONG).show()
    }

    fun openExact(activity: Activity) {
        if(Build.VERSION.SDK_INT >= 31) open(activity,
            Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${activity.packageName}")),
            appDetails(activity))
        else Toast.makeText(activity, "当前系统无需单独授予后台定时权限。", Toast.LENGTH_LONG).show()
    }

    // Called only after the user has read the purpose/cost explanation and tapped the positive button.
    fun requestBatteryExemption(activity: Activity) {
        if(read(activity).batteryExempt == true) {
            open(activity, Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), appDetails(activity))
        } else open(activity,
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${activity.packageName}")),
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), appDetails(activity))
    }

    fun openAppDetails(activity: Activity) = open(activity, appDetails(activity))

    fun requestNotifications(activity: Activity) {
        val preferences = activity.getSharedPreferences("background-access", Context.MODE_PRIVATE)
        if(Build.VERSION.SDK_INT >= 33 && activity.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            (!preferences.getBoolean("notificationRequested", false) || activity.shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS))) {
            preferences.edit().putBoolean("notificationRequested", true).apply()
            try {
                activity.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFICATION_REQUEST)
                return
            } catch (_: RuntimeException) { /* Use the settings page if the runtime prompt is unavailable. */ }
        }
        open(activity, Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, activity.packageName),
            appDetails(activity))
    }
}
