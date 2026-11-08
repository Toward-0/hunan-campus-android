# 湖南校园网 Android

当前候选为 **0.2.24-background / versionCode 36**，处理通用 Android 后台心跳调度与权限提示，设计支持 **Android 8.0 / API26 起**。本次同步源码、已审核的65文件固定交付及11个公开复现脚本，不创建新Release。设计支持范围不等于多品牌手机已经验证；已有兼容性缺口和长期锁屏测试仍按实际状态保留。

[下载v36手机主APK](revisions/v0.2.24-background/ESurfingHunan-0.2.24-background-candidate-phone.apk?raw=true) · [中文报告](revisions/v0.2.24-background/保活专项报告.txt) · [validation](revisions/v0.2.24-background/validation.json) · [全部校验和](revisions/v0.2.24-background/SHA256SUMS.txt) · [源码清单](revisions/v0.2.24-background/source-manifest.json) · [源码包](revisions/v0.2.24-background/source.zip?raw=true) · [复现脚本](tools/v36-background/)

普通使用者安装名称含`candidate-phone`的主包；`isolation`包只用于开发测试。同签名覆盖保留本地数据，更新后由用户手动连接，不通过卸载或清数据绕过安装问题。

| v36绑定项 | SHA256 |
|---|---|
| 手机主APK | `BB2555F46E14A06D22B00E961F4BDE03D914BDEF5DB5A0D7CD29F842E2F10CEA` |
| 240文件源码清单 | `9A8F5E695648415AB6DC93042EFC818A1606E73099F616C35EF0297244EF79C0` |
| 既有测试签名证书 | `2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229` |

本轮在 realme RMX3820/API34 发现，独立的“允许完全后台行为”关闭时，系统把本应用两个闹钟额外延后三天；开启后附加延期消失。随后保留原会话完成 311.81 秒 USB 连接下的普通锁屏观察，取得同代次新增成功心跳与外网结果，交付延迟分别 13ms、6ms。初次真实短测失败、复测原收集器漏采轮转记录的失败及补齐后的通过分别保留。尚未验证拔电待机、8小时自然锁屏或其他品牌真机。

realme本机实测入口：应用“更多”→“打开系统应用详情”→“耗电管理”→“允许完全后台行为”→允许。标准电池豁免、精确定时和最近任务锁定不能替代这个独立开关。其他品牌的具体入口未实机验证，详见[后台保活修订](docs/BACKGROUND_KEEPALIVE.md)。

本轮20项记录为**16 PASS / 2 FAIL / 2 NOT_RUN**：两条FAIL分别保留初次真实短测及复测原收集器漏采记录；补齐轮转证据后的短测独立PASS。完整Doze矩阵和8小时自然锁屏未运行。实际覆盖API34 realme ARM64及API26/API35 x86_64模拟器；当前ARM32运行、ARM64/16KB、拔电待机和其他品牌真机未验证。Lint主包0错误/16警告，隔离包0错误/36警告。

仓库`source/`的240文件保持v36构建输入原字节；本次顶层说明和同步不重新构建APK。`revisions/v0.2.24-background/`保留固定交付原件，其中“未推送”“仅本地”等文字描述构建交付当时的快照；本次同步不改写这些历史原件。v34固定归档也保持不变。当前状态与接续要求见[当前状态](docs/CURRENT_STATUS.md)和[下一轮接续](docs/NEXT_PROMPT.md)。

## v34 历史发布说明

以下保留v34发布时的说明，其中“当前”“本轮”、下载入口和测试结论仅指v34，不代表当前v36源码与交付。

使用校园网账号密码连接湖南校园网，查看连接和外网状态，并在条件满足时由用户确认修复。保留简约四页界面。

当前仓库候选是经用户确认的**阶段1修订 `s1-json-ui-20261108-01`**，版本 **0.2.22-compat-s1 / versionCode 34**，最终迭代r9。**阶段1未通过，不进入阶段2、3或4。** 本次按用户要求同步已有源码、APK、脚本和证据；不重新构建、不安装、不修改Android源码，也不创建新Release。

[下载v34手机主APK](revisions/v0.2.22-compat-s1/ESurfingHunan-0.2.22-compat-s1-candidate-phone.apk?raw=true)。名称含`isolation`的APK只用于开发测试。[旧v33 Release](https://github.com/Toward-0/hunan-campus-android/releases/tag/v0.2.21-compat-s1)、旧APK及旧证据继续保留，不以本次同步覆盖。历史[使用指南](docs/USER_GUIDE.md)明确适用v33，其下载与哈希不能替代本页v34入口。

| 绑定项 | SHA256 |
|---|---|
| v34主APK | `DC738FCDC352E1A67B3E456E2D376E25260DEA18D9DB561600709D6DDF682795` |
| 本轮238文件源码清单 | `85E866229FF79660EE560B586B0A04AE2F10B16F287AD5315CB0D1147266A1F9` |
| 既有测试签名证书 | `2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229` |

[全部校验和](revisions/v0.2.22-compat-s1/SHA256SUMS.txt) · [源码清单](revisions/v0.2.22-compat-s1/source-manifest.json) · [源码包](revisions/v0.2.22-compat-s1/source.zip?raw=true) · [脚本包](revisions/v0.2.22-compat-s1/scripts.zip?raw=true) · [中文验收报告](revisions/v0.2.22-compat-s1/阶段1验收报告.txt) · [validation](revisions/v0.2.22-compat-s1/validation.json)

## 本轮修改

- 诊断导出改为按完整 JSON 记录裁切并重新执行字段白名单校验；输出元数据也使用 JSON，不再产生首条半记录。
- 当前错误状态在新会话和成功心跳后清除；本轮历史失败仍保留，不改变认证协议和调度策略。
- 高级设置的认证通道选项支持大字体换行，保留完整的未验收提示。
- 隔离 UI 探针绑定前台 Activity、选中页面、内容标识、截图哈希和真实键盘状态，检查业务控件触达时不触发认证操作。
- 构建和测试的可写目录参数化，所有缓存、AVD、日志及产物限制在本轮工作区。

## 使用与边界

普通使用者只安装 `ESurfingHunan-0.2.22-compat-s1-candidate-phone.apk`；名称含 `isolation` 的包仅供开发测试。覆盖前核对交付哈希和既有测试签名。不要卸载或清除主应用数据来绕过安装失败。

直接连接校园 Wi-Fi 后，在账号页手动点击一次“保存并连接”。真实登录、注销和修复由用户操作。网络丢失或身份变化后停止，进程终止、force-stop、重启后不自动认证。修复仍需确认，仅自身注销成功后按客户端100秒等待策略至多重登一次，取消保护保持。

更换手机前应在旧手机仍有会话时手动“注销并停止”；停止连接不等于服务端注销。

## 支持与证据

设计基线保持 **minSdk26、targetSdk35、手机双 ARM ABI**。x86_64仅用于隔离模拟器。本次实际运行证据限API26/35 x86_64模拟器及API34 realme RMX3820 ARM64/ARM32进程，页大小均4096；用例与限制逐项见[validation](revisions/v0.2.22-compat-s1/validation.json)。iQOO本轮未连接；v33或中间迭代通过不转记最终APK通过，不能宣称“大部分安卓手机”已验证。

ARM64 / 16KB 实际运行环境仍缺失，保持 BLOCKED。API35 大字体系统状态栏字形裁切有系统设置页对照；最终截图中部分组合仍存在裁切，系统栏视觉门槛保留 FAIL，不能用应用控件几何检查代替。静态 ELF/ZIP 对齐不等于16KB运行通过。API29 环境启动及进程核验受阻，API31/33/36 未完成本轮矩阵。Doze组合、8小时自然锁屏、全面厂商适配和完整进程生命周期没有在本轮自动获得授权。

现用测试签名，不生成或接管正式密钥；未来换签不保证直接覆盖。反馈只提供型号、系统、应用版本和操作现象，不提交账号、密码、票据、密钥、完整抓包或完整设备日志。

## 开发与归档

工程在`source/`，238文件严格保持[本轮清单](revisions/v0.2.22-compat-s1/source-manifest.json)每字节一致；`tools/v34-s1/`对应固定脚本包16文件。历史源码内旧README不是当前版本依据。原v33 APK仍绑定原始233文件清单C83DFE…DEA，发布副本的一处文档脱敏不能倒签原APK输入。

`revisions/v0.2.22-compat-s1/`为固定交付243文件的逐字节副本。其中“未推送”“未发布”等措辞是**构建交付时的历史快照**，本次同步不改写这些文件。顶层文档说明本次同步，独立于Android构建输入。

19项门槛详见[当前状态表](docs/CURRENT_STATUS.md)，仍有FAIL、BLOCKED及NOT_RUN。除上述系统栏和矩阵缺口外，realme密码键盘截图内容区全黑、人工视觉BLOCKED；font2设置及恢复写入255保留FAIL，三键两项NOT_RUN。约251秒5次白名单快照未取得观察窗内新增心跳/HTTPS，短测BLOCKED。模拟器退出核验仍受阻，开发work未封存。Lint实际主包0错误/15警告、隔离包0错误/34警告，不能宣称零警告。

先读 [当前状态](docs/CURRENT_STATUS.md)、[构建与安装](docs/BUILD_AND_INSTALL.md)、[接续要求](docs/NEXT_PROMPT.md)和[完整流程](docs/FULL_WORKFLOW.md)。封存后再改必须另起工作及输出目录。第三方许可和来源说明均保留。
