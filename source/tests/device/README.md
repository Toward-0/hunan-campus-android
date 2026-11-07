# 真机 JNI 检查

本目录源码是独立 app_process 检查入口，不是 APK 的导出接口。NativeStress.java 定义测试用 NativeCore 并验证已捕获样本的解密/重加密一致性；MobileStress.java 验证动态句柄生命周期。

使用 JDK 17 编译 --release 11；用 SDK d8 转换 classes.dex；从已构建 APK 提取 arm64-v8a/libhunan_core.so，和 dex 一起推送至 /data/local/tmp。样本与动态模块由本机测试环境另行提供，不在源码包中分发。

```sh
CLASSPATH=/data/local/tmp/esurfing-check.dex app_process -Dhunan.library=/data/local/tmp/libhunan_core.so /system/bin org.esurfing.hunan.NativeStress /data/local/tmp/esurfing-samples.txt
CLASSPATH=/data/local/tmp/esurfing-check.dex app_process -Dhunan.library=/data/local/tmp/libhunan_core.so /system/bin org.esurfing.hunan.MobileStress /data/local/tmp/ios.zsm
```

NativeStress 的输入为每行一条十六进制密文，不输出解出的明文。MobileStress 输入为已取得的受支持动态 ZSM 模块。不要将个人账号样本放入交付压缩包。

本轮真机结果：3 份样本逐字节比对、补零与字段顺序、旧模块 4000 次并发调用；动态模块 100 次创建/释放、UTF-8/块边界、失效句柄、容量回收、4000 次并发往返及释放后重启均通过。这不是整个 Android Service 100 次启动/停止的验收结论。
