# 湖南校园网 Android

当前归档版本 **0.2.21-compat-s1 / versionCode 33**。这是持续开发的私有项目，**阶段1整体未通过**，不是已完成的兼容性或后台稳定性承诺。

当前已有 realme RMX3820（Android 14 / API 34）和用户称为 iQOO 12 的 vivo V2307A（Android 15 / API 35）上该版本的实际联网成功证据。iQOO 对照中高级项为空，仅由用户输入账号密码并手动连接成功；该结果只覆盖记录的设备、网络与短时窗口。

## 从这里继续

- [当前进度、验证边界和未解决问题](docs/CURRENT_STATUS.md)
- [完整开发、测试、交付流程](docs/FULL_WORKFLOW.md)
- [下次对话可直接使用的提示词](docs/NEXT_PROMPT.md)
- [构建、安装和工具使用说明](docs/BUILD_AND_INSTALL.md)
- [证据与哈希说明](evidence/README.md)
- [协作约束](AGENTS.md)

`source/` 保存 v33 工程。其内部 README 和部分复现文档保留旧版本时点的说明，**当前进度以本页和 docs/ 为准**。运行代码与构建文件保持 v33 原样；只有一份历史操作文档中的设备序列号被替换为占位符，见 `evidence/publication-changes.json`。原 APK 构建绑定使用 `original-source-manifest.json`，发布副本使用新的 `source-manifest.json`，两者不可混称。

## APK

| 文件 | 用途 | 包名 / ABI |
|---|---|---|
| [candidate-phone](artifacts/main/ESurfingHunan-0.2.21-compat-s1-candidate-phone.apk) | 主应用；真实认证只能由用户手动执行 | org.esurfing.hunan / arm64-v8a + armeabi-v7a |
| [isolation-phone](artifacts/isolation/ESurfingHunan-0.2.21-compat-s1-isolation-phone.apk) | 隔离测试 | org.esurfing.hunan.isolation / 双 ARM |
| [isolation-arm32](artifacts/isolation/ESurfingHunan-0.2.21-compat-s1-isolation-arm32.apk) | 支持32位设备上的实际32位JNI测试 | armeabi-v7a |
| [isolation-x86_64](artifacts/isolation/ESurfingHunan-0.2.21-compat-s1-isolation-x86_64.apk) | 匹配模拟器的隔离测试 | x86_64 |

主 APK SHA256：`7D73C1C63A746E5747E1A41D4100ED83F9036C0C4C0BC6A721E4513E6320AE2D`。

设计支持 minSdk 26、targetSdk 35；手机交付双 ARM。ARM64/16KB 实际运行环境仍缺失；API35 大字体状态栏裁切仍未解决；完整约定矩阵不能用旧构建结果替代。没有8小时自然锁屏或全厂商适配结论。

## 连接和修复规则

“更多 → 修复网络”入口常驻，但执行仍受安全条件约束。用户确认、自身注销得到协议认可的成功、客户端等待策略、至多一次重新登录缺一不可。停止连接/关闭 Wi-Fi 不等于服务端注销。105 的协议含义和根因尚未确认，连接恢复也不等于已修复其根因。

网络丢失或身份变化、进程终止、强制停止及重启后不自动认证。不自动开机登录，不自动重放账号 POST，不修改协议、生产端点或 MAC/客户端标识策略。

## 仓库边界

本仓库含筛选源码、APK、可复现脚本和白名单证据摘要；原始本机封存证据以哈希引用。无签名私钥、用户凭据、完整抓包、原始手机日志、SDK或缓存。仍需开发者自行配置工具链及由用户持有的既有测试签名；不承诺下载后无需配置即可构建。第三方代码保留自身许可，尚未为整个项目新增许可证。
