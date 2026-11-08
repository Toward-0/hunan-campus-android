# 构建、安装与复现

当前候选为 **0.2.24-background / versionCode 36**。本次同步已审核固定交付，不为上传重新构建APK或创建新Release。当前[手机主APK](../revisions/v0.2.24-background/ESurfingHunan-0.2.24-background-candidate-phone.apk?raw=true)、[源码包](../revisions/v0.2.24-background/source.zip?raw=true)、[240文件清单](../revisions/v0.2.24-background/source-manifest.json)、[公开构建命令](../revisions/v0.2.24-background/evidence/build-commands-public.json)、[验证记录](../revisions/v0.2.24-background/validation.json)和[校验和](../revisions/v0.2.24-background/SHA256SUMS.txt)绑定同一v36交付。仓库source保持实际构建输入字节。

主APK SHA256为`BB2555F46E14A06D22B00E961F4BDE03D914BDEF5DB5A0D7CD29F842E2F10CEA`；源码清单SHA256为`9A8F5E695648415AB6DC93042EFC818A1606E73099F616C35EF0297244EF79C0`。仍使用既有测试证书；同签名覆盖安装保留数据，更新后由用户手动连接。名称含isolation的包只用于隔离测试，不安装为普通用户主包，不清除/卸载主应用绕过安装失败。

公开脚本在[tools/v36-background](../tools/v36-background/)，与固定交付scripts.zip的11个文件逐字节一致。构建工具配置和签名密码继续外置；设备脚本要求显式序列号，真实账号操作不由脚本代替。API26控制器公开副本将SDK、运行目录与端口参数化，其实际运行与退出证据见归档；不把衍生脚本语法检查说成再次执行。用于轮转补齐的reconcile_rotation.py拒绝覆盖既有证据。

设计支持Android8.0/API26起、targetSdk35、手机双ARM；本轮实际范围与16 PASS/2 FAIL/2 NOT_RUN见validation，不能把构建成功当作多品牌运行或8小时锁屏通过。realme还需检查独立的“允许完全后台行为”，见[后台运行说明](BACKGROUND_KEEPALIVE.md)。归档报告中的“未推送/仅本地”为构建交付时历史快照，保持原件。

以下保留v34构建交接历史；通用的独立工作目录、工具链与签名保护仍适用，但旧版本/下载入口/本次同步措辞仅指v34。

## v34构建交接历史

当前候选为阶段1修订`s1-json-ui-20261108-01`最终r9、0.2.22-compat-s1 /34，阶段1仍未通过。本次GitHub同步只复制已有固定交付，无新构建、安装、Android源码修改或新Release。旧v33 Release、原APK和233文件绑定继续保留。固定归档内“未发布”“未推送”是构建交付时历史快照，不改写。不得在基线或封存目录直接运行下面脚本。

[下载v34手机主APK](../revisions/v0.2.22-compat-s1/ESurfingHunan-0.2.22-compat-s1-candidate-phone.apk?raw=true)，SHA256为`DC738FCDC352E1A67B3E456E2D376E25260DEA18D9DB561600709D6DDF682795`。238文件[源码清单](../revisions/v0.2.22-compat-s1/source-manifest.json) SHA256为`85E866229FF79660EE560B586B0A04AE2F10B16F287AD5315CB0D1147266A1F9`，仓库source每字节一致；全部文件见[校验和](../revisions/v0.2.22-compat-s1/SHA256SUMS.txt)。

[源码包](../revisions/v0.2.22-compat-s1/source.zip?raw=true)、[工具链](../revisions/v0.2.22-compat-s1/toolchain.json)、[validation](../revisions/v0.2.22-compat-s1/validation.json)、[证据索引](../revisions/v0.2.22-compat-s1/evidence-index.json)和[中文报告](../revisions/v0.2.22-compat-s1/阶段1验收报告.txt)均保留固定原件。19门槛及主要缺口见[当前状态](CURRENT_STATUS.md)。顶层同步文档不属于Android构建输入。

## 在下一份新副本准备环境

先只读核对README、CURRENT_STATUS、FULL_WORKFLOW、AGENTS和最终validation；确认具体计划后，创建新的work/<唯一修订>与outputs/<同名>。复制清单内源码及经审核支持脚本，工具链和现有测试签名允许只读复用。

按source/stage-tools.example.json建立不公开的tools.local.json，配置JDK、Gradle、当前阶段SDK、模拟器工具、已有测试证书、签名环境变量名、输出根及保护根。所有Gradle缓存、SDK可写组件、Android/Java用户目录、临时目录、AVD、CXX/Gradle输出、日志和截图均在新阶段。禁止指向旧目录的可写链接或硬链接。stage-env.ps1校验目录及封存标记；stage_guard.py的明确保护范围必须适配下一修订，不能原封不动指向本轮后继续写入。

保留实际工具链：JDK17.0.16、Gradle8.11.1、AGP8.9.2、Kotlin2.1.20、NDK28.0.13004108、CMake3.22.1、Build Tools35.0.0；minSdk26、targetSdk35。先确认依赖和磁盘可用，再执行离线构建，不升级整套依赖来掩盖问题。既有测试密钥不随交付打包，不生成替代密钥。

## 构建命令形态

签名口令只由用户环境注入配置指定的进程环境变量，不写进脚本、报告或命令行明文。完整参数、环境路径映射、退出码、签名与对齐结果见[公开构建记录](../revisions/v0.2.22-compat-s1/build-commands-public.json)；本地原始记录的哈希在证据索引。以下仅说明经批准的新副本中的命令形态，本次GitHub同步没有执行。

```powershell
$ErrorActionPreference='Stop'
# $Stage、$Output均为新的、经检查的绝对路径。
. "$Stage/source/stage-env.ps1"
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi phone
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi arm32 -IsolationOnly -SkipLint
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi x86_64 -IsolationOnly -SkipLint
```

脚本使用--offline、--no-daemon和当前阶段project-cache；每个外部步骤显式检查退出码，失败抛错中止。输出存在时拒绝覆盖。当前未封存修订内迭代也要保留上一迭代APK、idsig、源码输入及测试记录；封存后必须另起修订。新代码交付code递增，文档归档不增code。

手机主包仅双ARM，x86_64仅隔离构建。最终静态审计分别检查身份、签名、ABI、主包隔离入口排除、适用64位ELF LOAD对齐与最终zipalign16KB；实际ARM64/16KB运行仍须单独环境，不可替代。

## 测试脚本与设备

[scripts.zip](../revisions/v0.2.22-compat-s1/scripts.zip?raw=true)仅含明确审核的16个支持文件，[script-manifest.json](../revisions/v0.2.22-compat-s1/script-manifest.json)记录哈希；原字节亦位于[tools/v34-s1](../tools/v34-s1/)。不得直接运行带旧阶段绑定的脚本；先适配新修订保护范围。全部设备动作显式传serial、包名、APK和SHA256、源码标识与版本，设备重新核对，不能默认上一台仍在线。

- run_device.py：仅隔离包，安装/探针有超时，真实进程位数与JNI句柄释放写入证据；退出清理隔离包，不触碰主应用。
- run_ui.py：仅隔离UI，先记录再恢复字体、导航/刘海覆盖、键盘与隔离通知状态；截图需逐张人工检查，自动PASS不是系统栏视觉通过。
- matrix-suite.py、run_realme_batch.py：串行编排已约定用例，清理或恢复无法证明成功时停止后续，缺证据保留NOT_RUN/BLOCKED。
- main-device.py：只读预检、同签名覆盖安装和白名单快照。覆盖前两次核对manualOff、desired、phase及服务不存在；不调用真实连接、停止、注销或修复。
- restore_revision.py / emulator_process_guard.py：根据匹配的本轮记录恢复隔离测试状态；模拟器退出必须核对serial、qemu、AVD及当前阶段路径，ADB断开与实际进程树退出分别证明。不关闭全局ADB、不删除历史AVD，身份查询拒绝后不得换工具绕过。

API29环境及模拟器退出核验仍受阻，API31/33/36未运行；旧API26停机记录缺少进程树退出证据，交付保留原声明及哈希并归一化BLOCKED。realme字体写入255保留FAIL，后续只读恢复核对一致另列；密码键盘截图全黑的视觉BLOCKED不由自动几何PASS替代。当前开发work因此未封存，不影响固定交付的独立哈希绑定。

adb_client.py复用已运行的本机ADB服务127.0.0.1:5037，不创建ADB凭据。测试回环服务器在设备内部，设备127.0.0.1不是主机127.0.0.1；本轮隔离测试不需要adb reverse，不回退生产端点。若将来改用主机服务器，必须先明确reverse映射、超时和退出清理。

真实认证始终由用户操作。短时实网方案：登录最多1次、注销0次、修复0次，观察最多5分钟；只保留正常心跳和既有预算探测，代理额外网络探测0次，白名单状态快照间隔至少60秒。认证失败、网络/身份变化、用户停止或到时结束观察；不自动重登、注销或修复，不因失败追加次数。此观察不能证明持续外网、Doze或8小时锁屏表现。

## 安装和恢复边界

同签名install -r保留主应用数据，安装失败停止，不自动卸载、清数据或加降级参数。主包测试证书SHA256：2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229。正式签名迁移和低code回退不保证覆盖或无损数据迁移。

破坏性和故障注入只作用隔离包。不要导出主应用凭据、完整日志或抓包；从入口就使用字段白名单。用户已归因于旧客户端未注销的换机事件不重新列为APK缺陷，原始历史证据不倒改。

第三方LICENSE、NOTICE、来源及cJSON/LZMA/OkHttp/Okio声明保留。当前源码清单仅绑定source/实际输入；顶层说明和支持脚本使用独立supplement/script清单，不能混淆成原v33构建输入。
