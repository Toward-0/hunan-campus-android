# 证据索引

本目录是经过审查的选择性导出，不是原手机证据目录的完整副本。本次没有重建或运行Android测试。

| 文件 | 用途 |
|---|---|
| original-source-manifest.json | 原v33构建输入的233项清单；文件SHA256为C83DFEAB98CBBA964C53000D9C01B300E98F706DBFBD2D376E0DAB6117F77DEA |
| original-build-binding.json | 原源码清单与四个APK的绑定 |
| source-manifest.json | 仓库source/发布副本的233项清单；有一份文档隐私替换，与原构建清单不同 |
| publication-changes.json | 发布副本与原封存源码的差异，包含前后SHA256 |
| v33-source-changes.json、v32-to-v33.patch | 原v32→v33源码修订，保留原样 |
| curated-validation.json | 三轮原归档的48条验收记录，逐项白名单摘要及原始证据引用/哈希 |
| static-build-evidence.json | 原v33工具链、ELF LOAD、签名、zipalign及Lint摘要 |
| build-commands.json | 原构建完整参数、退出码与环境字段；仅把本机路径映射成明确占位符 |
| support-script-manifest.json | tools/v33-history/历史支持脚本哈希与来源 |
| ../SHA256SUMS.txt | 本仓库交接文件的SHA256清单（排除自身和.git） |

验收摘要里的 `archivePath` 是原工作区的相对归档定位，`includedInRepository:false` 表示原文件仅本地保存。仓库里没有这些原始手机日志、截图或完整报告；不能把哈希引用当作已上传原件。发布只选择必要字段，不包含序列号、账号、密码、票据、网络身份或完整抓包。

48条记录包含36 PASS、3 BLOCKED、2 FAIL、7 NOT_RUN，属于不同用途的归档条目，存在历史时点与后续补充关系，**不是独立实验数或成功率分母**。阶段1仍FAIL。早期v33报告的实网NOT_RUN原样保留，后续iQOO和realme的同APK实网PASS另列，不倒改历史记录。

适用64位库的16KB ELF对齐、APK zipalign通过不能替代ARM64/16384运行证据。当前v33 API35模拟器为x86_64/4096；旧API矩阵的v32证据只作为历史引用。

没有上传签名私钥、控制台令牌、ADB密钥、SDK/缓存或未审核压缩包。工具脚本属于历史复现备份，执行前先在新的阶段目录参数化并检查权限、设备及路径，见 docs/BUILD_AND_INSTALL.md。
