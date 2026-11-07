# 构建、安装与复现入口

此交接没有重建 APK，没有手机操作。现有 APK 与原始 v33 源码清单绑定；发布源码只对一份历史说明替换了设备序列号。不要直接在仓库基线执行构建或测试。

## 准备新修订

1. 阅读当前状态，提交5—8行实施计划，经用户确认后开始。
2. 创建新的 `work/<唯一阶段名>/source/` 与 `outputs/<同名>/`，复制 `source/`。先核对 `evidence/source-manifest.json`，保留原始构建绑定和本次发布差异。
3. 原脚本含历史工具链引用，必须在新副本中参数化 JDK、Gradle、SDK 和测试签名位置；核查所有写入路径。工具链/已有测试签名可只读复用；Gradle缓存、SDK可写部分、Android/Java用户目录、临时目录、AVD、CMake/Gradle输出及日志都进入新阶段，不能用可写链接指回封存目录。
4. 工具链记录为 JDK17.0.16、Gradle8.11.1、AGP8.9.2、Kotlin2.1.20、NDK28.0.13004108、CMake3.22.1、Build Tools35.0.0。需要本地提供依赖缓存/SDK；仓库没有这些大文件。不得为构建方便整体升级依赖。
5. 测试签名私钥由用户本地保管，本仓库不含密钥。不生成替代测试密钥冒充同签名。正式签名只制定密钥自持方案。

既有构建入口位于 `source/build-stage.ps1` 和 `source/stage-env.ps1`。参数化完成后的命令形态为：

```powershell
$ErrorActionPreference = 'Stop'
# $Stage 和 $Output 是经确认的新目录绝对路径，不是归档源码目录。
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi phone
if ($LASTEXITCODE -ne 0) { throw 'phone 构建失败，停止后续步骤' }
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi arm32 -IsolationOnly -SkipLint
if ($LASTEXITCODE -ne 0) { throw 'arm32 构建失败' }
& "$Stage/source/build-stage.ps1" -OutputRoot $Output -BuildAbi x86_64 -IsolationOnly -SkipLint
if ($LASTEXITCODE -ne 0) { throw 'x86_64 构建失败' }
```

原入口执行 `--offline --no-daemon`，记录完整命令/环境/退出码，zipalign、测试签名、签名验证及最终 `zipalign -c -P 16 -v 4`。完整原构建命令的筛选记录见 evidence；没有在本次交接重新执行。ELF LOAD 对齐、最终ZIP对齐与实际16KB环境运行必须分别验收。

## 脚本边界

`source/tests/device/Verify-Compatibility.ps1` 与 `Restore-Compatibility.ps1` 接受显式 Adb、Aapt、Serial、Package、Apk、EvidenceDirectory，限制隔离包并检查退出码、超时、ABI和哈希。先 Environment，再决定是否安装32位包；不能在只支持arm64的iQOO上制造v7a通过结果。

`tools/v33-history/` 是经过审核的历史脚本备份，不是无需配置的通用工具。`SEALED` 禁止原位执行。按需复制到**新的阶段根**，而不是其 source 子目录，保留明确的设备参数；新阶段配置 sdk/、source/、evidence/、pack/ 及对应 outputs/。`stage_guard.py` 的保护根需在新副本中扩展为实际历史根，保留SEALED检查。v33专项文件名与审计断言也必须匹配目标版本，不得盲目替换版本后沿用旧结论。

`adb_client.py` 连接已经运行的本机ADB服务127.0.0.1:5037，不创建ADB凭据；使用带必填serial的上层工具，不直接调用其未强制serial的CLI push分支。`run_device.py` 只执行隔离探针，`run_ui.py` 仅操作隔离UI并记录/恢复字体等设置，`device_main.py` 仅安装或读固定字段，不发连接/注销/修复命令。该脚本只覆盖审核过的v33升级路径，不支持任意来源旧APK。

未上传一次性报告编排器、包含历史设备基线路径的清理器、含个人解释器路径的启动脚本或原 scripts.zip。它们可能把固定结论写成新结果，不能用来生成未来“通过”记录。

## 安装、停止和回退

安装前指定 `$DeviceSerial`、`$Package`、`$Apk` 和SDK工具路径，核对设备online/authorized、supported ABIs、API、PAGE_SIZE、APK SHA256、包名、版本和签名。保留设备原应用数据；只使用同签名的 `install -r`，安装失败停止，不自动卸载、清数据或使用降级参数。任何安装会中断进程，应选择用户可接受的窗口。

当前主包证书SHA256：`2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229`。换正式签名未必能覆盖测试签名；旧versionCode回退也受Android和数据格式限制，不承诺无损降级。

隔离测试每项使用既有脚本的超时及失败即停止策略。停止/恢复只针对隔离包和本轮已记录的设置，不停止主应用会话，不清除其数据。模拟器停止需核对serial及 `ro.kernel.qemu=1`；不关全局ADB服务，不按名称批量杀进程。

真实认证始终由用户操作。短时连接方案应预先规定：本轮登录≤1、注销0、修复0，最多观察5分钟；保留正常心跳与既有有预算探测，不增加轮询。失败或超时由用户停止连接，读字段白名单后分析，不连续重试。需要注销或修复的方案另行明确次数、停止条件与失败处理。

## 许可证和来源

保留 vendor/hunan 的 LICENSE/NOTICE、cJSON许可头、LZMA声明、OkHttp/Okio许可和 provenance。上游NOTICE中的旧Windows凭据格式说明及git历史描述属于上游历史；本Android凭据使用Keystore，新仓库没有导入该旧git历史。仓库没有为全部代码新增统一许可证。
