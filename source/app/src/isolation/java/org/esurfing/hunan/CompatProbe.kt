package org.esurfing.hunan

import android.app.Instrumentation
import android.os.Bundle
import android.os.Build
import android.os.Process
import android.system.Os
import android.system.OsConstants
import org.json.JSONObject
import java.io.File

/** Public synthetic fixtures only. No network, account reads, or main-package access. */
class CompatProbe : Instrumentation() {
    private external fun nativeBits(): Int
    private external fun nativeAbi(): String
    private external fun failAllocation(index: Int)
    override fun onCreate(arguments: Bundle?) { super.onCreate(arguments); start() }
    override fun onStart() {
        var step = "guard"
        val row = JSONObject().put("testId","S1-JNI").put("api",Build.VERSION.SDK_INT)
            .put("manufacturer",Build.MANUFACTURER).put("model",Build.MODEL)
            .put("supportedAbis",Build.SUPPORTED_ABIS.joinToString(","))
            .put("process64",Process.is64Bit()).put("pageSize",Os.sysconf(OsConstants._SC_PAGESIZE))
        try {
            check(targetContext.packageName == "org.esurfing.hunan.isolation")
            NativeCore.liveMobileHandles() // Load the library before test-only JNI calls.
            row.put("nativeBits",nativeBits()).put("loadedAbi",nativeAbi())
            check(nativeBits() == if(Process.is64Bit()) 64 else 32)
            val module=targetContext.assets.open("synthetic-module.zsm").use { it.readBytes() }
            val bad=targetContext.assets.open("synthetic-short.zsm").use { it.readBytes() }
            step="truncated"
            var rejected=0
            for(length in 0 until module.size) {
                check(NativeCore.createMobile(module.copyOf(length))==0L) { "truncation $length" };rejected++
            }
            for(bytes in listOf(bad,ByteArray(65537),module.copyOf().apply { this[0]=0 },module.copyOf().apply { this[41]=(-1).toByte() })) {
                check(NativeCore.createMobile(bytes)==0L);rejected++
            }
            row.put("malformedRejected",rejected)
            step="roundtrip"
            repeat(200) {
                val handle=NativeCore.createMobile(module);check(handle!=0L)
                for(text in listOf("A","A".repeat(7),"A".repeat(8),"A".repeat(15),"A".repeat(16),"A".repeat(17),"A".repeat(4096),"中文😀")) {
                    val data=text.toByteArray();val encrypted=checkNotNull(NativeCore.cryptMobile(handle,data,false))
                    check(data.contentEquals(NativeCore.cryptMobile(handle,encrypted,true)))
                }
                check(NativeCore.cryptMobile(handle,byteArrayOf(65,0,66),false)==null)
                NativeCore.releaseMobile(handle);NativeCore.releaseMobile(handle)
                check(NativeCore.cryptMobile(handle,byteArrayOf(65),false)==null)
                check(NativeCore.liveMobileHandles()==0)
            }
            row.put("cycles",200)
            step="capacity"
            val handles=LongArray(8) { NativeCore.createMobile(module).also { check(it!=0L) } }
            check(NativeCore.createMobile(module)==0L)
            handles.forEach { NativeCore.releaseMobile(it) }
            step="allocation-failure"
            for(code in 1..9) {
                val fixture=targetContext.assets.open("synthetic-type-$code.zsm").use { it.readBytes() }
                NativeSession(fixture).use { check(it.crypt(it.crypt("type-$code",false),true)=="type-$code") }
                repeat(20) { index ->
                    failAllocation(index)
                    val handle=NativeCore.createMobile(fixture)
                    failAllocation(-1)
                    if(handle!=0L) NativeCore.releaseMobile(handle)
                    check(NativeCore.liveMobileHandles()==0)
                }
            }
            NativeSession(module).use { check(it.crypt(it.crypt("after-failure",false),true)=="after-failure") }
            row.put("syntheticAlgorithms",9).put("allocationFailurePositionsPerAlgorithm",20).put("handlesAfter",NativeCore.liveMobileHandles()).put("status","PASS")
        } catch(t: Throwable) {
            row.put("status","FAIL").put("step",step).put("exception",t.javaClass.simpleName)
                .put("line",t.stackTrace.firstOrNull { it.fileName=="CompatProbe.kt" }?.lineNumber)
        } finally { runCatching { failAllocation(-1) } }
        File(targetContext.filesDir,"compat-jni.json").writeText(row.toString(2))
        finish(if(row.optString("status")=="PASS") -1 else 0,Bundle().apply { putString("result",row.toString()) })
    }
}
