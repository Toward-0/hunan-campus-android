# 湖南校园网 Android 验证版

当前阶段为兼容性基建，版本 **0.2.19-compat-s1 / versionCode 31**，基于用户指定的 0.2.18-stability / 30 源码副本。仅在新的阶段工作目录中开发；旧 work/outputs 和缓存均为只读。

## 支持目标与证据边界

- minSdk 26、compileSdk 35、targetSdk 35 保持不变。
- 手机主包为 arm64-v8a + armeabi-v7a。x86_64 和 arm32 单 ABI 包仅用于隔离测试。
- 计划矩阵为 API 26/29/31/33/34/35/36；实际通过项以对应交付的 validation.json 和中文验收报告为准。
- 16KB 的 ELF、APK ZIP 对齐及实际 PAGE_SIZE=16384 运行分别验收。静态检查不替代运行，x86_64 不替代 ARM64，64 位安装不替代 32 位 JNI。
- 本阶段不宣称“大部分安卓手机已通过”、长时锁屏稳定或正式商店发布就绪。历史文档中的设备/版本测试结果只作为历史证据。

## 保留的行为

简约四页界面保留。认证接受与 Wi-Fi HTTPS 可用分别判断；单个 HTTPS 失败不会触发修复。网络丢失或身份变化后停止，等待手动连接，不自动提交账号。

修复须用户确认。只有自身注销取得既有协议认可的成功响应后，才按客户端策略等待 100 秒并至多重登一次；100 秒不是已确认的服务器要求。停止、网络变化、服务结束取消待执行修复。进程被终止、force-stop 或重启后不自动恢复认证，不自动开机启动。

每代连接使用自己的传输资源和选定网络的 DNS/SocketFactory，结束后取消并释放；保留代次检查及 POST 禁止自动重放。认证协议、生产端点、MAC/客户端标识策略、Keystore/AES-GCM 凭据格式及测试证书不变。

## 本阶段变更

增加双 ARM 构建与隔离 x86_64 变体；审查 JNI 句柄、长度转换和 LZMA，补充分配失败清理与极端计数溢出保护。处理 API 35 系统栏、刘海和键盘 insets，以分版本资源设置浅色系统栏主题，修复API33三键导航图标对比度；按钮随字体增长，切页时把焦点交给滚动容器以避免大字体下自动跳到底部。

主包不包含 instrumentation、合成模块及故障注入。org.esurfing.hunan.isolation 包的实际测试请求仅在设备自身 127.0.0.1；纯假连接不产生网络 I/O，不将回环测试称为真实 TLS 或校园认证验收。

## 构建与复现

完整操作见 [阶段1复现与真机操作](docs/阶段1复现与真机操作.md)。唯一推荐构建入口为新副本中的 build-stage.ps1，显式传入新的 OutputRoot；build-local.ps1 是它的兼容包装。不要在旧基线运行 Gradle、格式化、清理或测试，也不要使用旧文档中的输出路径。

工具链保持 JDK 17.0.16 / Gradle 8.11.1 / AGP 8.9.2 / Kotlin 2.1.20 / NDK 28.0.13004108 / CMake 3.22.1 / Build Tools 35.0.0。可写 Gradle、SDK、Android/模拟器用户目录、临时文件、构建输出和签名输出均位于当前阶段；测试密钥只读取复用，不打包输出。

主包名 org.esurfing.hunan，隔离包名 org.esurfing.hunan.isolation。自动脚本只安装和操作隔离包，显式指定序列号及 APK，核对 supported ABIs、退出码与安装后 SHA256。所有真实认证仍需用户按单独确认的方案执行；不为测试清除主应用数据。

## 文档与许可

稳定化规则见 [稳定化审查](docs/稳定化审查.md)，原生审查见 [阶段1原生审查](docs/阶段1原生审查.md)。旧 docs 中的阶段范围及旧版本结论不覆盖本阶段的双 ARM 授权，也不能替代本次构建证据。

ESurfingClient-Hunan / ESurfingClient-CVersion 采用 Apache-2.0，保留 vendor/hunan 中的 LICENSE/NOTICE；LZMA SDK 解码器为 Igor Pavlov 的公有领域实现。OkHttp/Okio 许可及来源保留于 third-party 和 APK 许可页面。源码包不含用户凭据或签名私钥。
