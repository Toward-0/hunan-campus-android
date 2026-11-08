# 当前状态：v34候选，阶段1未通过

本轮标识为 `s1-json-ui-20261108-01`，版本 **0.2.22-compat-s1 / versionCode 34**。阶段1结论仍为**未通过**，默认留在阶段1。阶段2、3、4没有因为旧版GitHub发布或本次本地构建自动获得授权。

## 版本和证据入口

本次按用户要求同步已固定的v34候选源码、APK、脚本和证据，不重新构建、不安装、不修改Android源码，也不创建新Release。[旧v33 Release](https://github.com/Toward-0/hunan-campus-android/releases/tag/v0.2.21-compat-s1)及其APK、证据继续保留，旧封存发布提交为8cb98b3b69a4e7d4d5d7afddb808a3b9ebd73c21，不强推或改写历史。

本轮最终APK、实际输入和测试的唯一组合以[源码清单](../revisions/v0.2.22-compat-s1/source-manifest.json)、[validation](../revisions/v0.2.22-compat-s1/validation.json)、[构建记录](../revisions/v0.2.22-compat-s1/build-commands-public.json)、[证据索引](../revisions/v0.2.22-compat-s1/evidence-index.json)、[校验和](../revisions/v0.2.22-compat-s1/SHA256SUMS.txt)及[中文报告](../revisions/v0.2.22-compat-s1/阶段1验收报告.txt)为准。相同版本的中间迭代不能互相转记通过；每项保留PASS/FAIL/NOT_RUN/BLOCKED。

[v34手机主APK](../revisions/v0.2.22-compat-s1/ESurfingHunan-0.2.22-compat-s1-candidate-phone.apk?raw=true) SHA256为`DC738FCDC352E1A67B3E456E2D376E25260DEA18D9DB561600709D6DDF682795`；238文件源码清单SHA256为`85E866229FF79660EE560B586B0A04AE2F10B16F287AD5315CB0D1147266A1F9`。仓库source保持实际输入的每字节一致。

`revisions/v0.2.22-compat-s1/`全部243文件保持固定交付原字节，其中“未发布”“未推送”是构建交付当时的历史快照，本次同步不改写；顶层文档说明后续同步，不属于238文件Android构建输入。开发work因模拟器退出核验受阻仍未封存，固定交付的独立哈希绑定保留。

## 19项门槛

最终validation含17项必选和2项可选/补充；必选项非PASS，阶段结论仍为未通过。

| 测试ID | 状态 | 定位 |
|---|---|---|
| JSON-COMPLETE-RECORDS | PASS | 必选 |
| DIAGNOSTIC-CURRENT-STATE | PASS | 必选 |
| UI-API35-COMPLETE | FAIL | 必选 |
| API26-CURRENT-BUILD | FAIL | 必选 |
| API29-CURRENT-BUILD | BLOCKED | 必选 |
| API31-CURRENT-BUILD | NOT_RUN | 必选 |
| API33-CURRENT-BUILD | NOT_RUN | 必选 |
| API35-CURRENT-BUILD | FAIL | 必选 |
| API34-REALME-AFFECTED | FAIL | 必选 |
| ARM64-JNI | PASS | 必选 |
| ARM32-JNI | PASS | 必选 |
| SAFE-STOP-ACCOUNT-REPAIR | PASS | 必选 |
| MAIN-SAME-SIGNATURE-INSTALL | PASS | 必选 |
| CURRENT-MANUAL-REAL-NETWORK | BLOCKED | 可选短测 |
| FINAL-STATIC-APK | PASS | 必选 |
| PROTECTED-BASELINE-UNCHANGED | PASS | 必选 |
| ENVIRONMENT-RESTORATION | BLOCKED | 必选 |
| API36-SUPPLEMENTAL | NOT_RUN | 补充 |
| ARM64-PAGE16384-RUNTIME | BLOCKED | 必选 |

原v33主APK仍绑定原始233文件清单C83DFEAB98CBBA964C53000D9C01B300E98F706DBFBD2D376E0DAB6117F77DEA。发布副本另有E5D4794F2CA708136B5CE8687566200A7F3A184D8D9151BB253595E83737918E清单，仅历史说明中的设备序列号脱敏，不能倒签为旧APK构建输入。本轮清单独立绑定新APK。顶层文档/支持脚本与source实际构建输入分别列清单，source内旧README不是当前版本依据。

## 本轮修改与验证重点

诊断导出使用完整JSON记录边界淘汰最旧记录，保留类型与字段白名单；元数据也是独立JSON，记录截断、拒绝和不可读计数。当前协议错误在新会话及成功心跳后清除，本轮历史失败保留，代次和取消语义不放宽。

大字体界面修订集中于高级设置认证通道的完整文本显示。UI探针绑定前台Activity、选中页、页面内容、窗口和截图哈希，键盘必须真实可见；业务按钮用触摸按下并取消验证可达，不触发登录/注销/修复。逐图视觉检查单独记录，自动PASS不能替代视觉门槛。

本轮约定必选环境：API26/29/31/33/35 x86_64隔离模拟器、API34 realme RMX3820实际ARM64和ARM32进程。API36作为补充，targetSdk仍35。API35覆盖字体1/2×手势/三键×无模拟刘海/高刘海；旧系统及realme按系统实际能力验证受影响组合，无法实现的组合不能假称执行。每项实际结果见validation和中文验收报告。

Android26缺少getconf/awk，不将检测工具缺失误记为APK失败：页大小使用设备端仅提取AT_PAGESZ的白名单查询，并与JNI Os.sysconf返回值交叉核对；恢复脚本不依赖awk。未知页大小不默认写4096。

## 未关闭门槛及范围

- ARM64 / PAGE_SIZE=16384的实际安装、启动、JNI仍缺环境，保持BLOCKED；用户已明确暂无法提供，不再反复询问。64位ELF及APK静态16KB对齐不能替代运行门槛。
- API35大字体系统状态栏字形裁切在应用和系统设置页均有对照，最终120张截图逐图检查中部分组合仍为系统栏视觉FAIL；API26两倍字体也有裁切。应用控件与系统栏分项记录，不通过额外应用padding或自动几何PASS掩盖。
- API29模拟器启动后ADB从offline转为absent；随后Windows拒绝Get-CimInstance进程身份查询，无法可靠核验并关闭残留。没有改用工具或路径绕过。API29本轮APK测试BLOCKED；API31/33必选矩阵及API36补充矩阵NOT_RUN。不得将此环境限制记作APK自身失败，亦不得用旧版结果补齐。
- 本轮最终Lint：主包0错误/15警告，隔离包0错误/34警告；零警告目标FAIL。v33历史主包0错误/15警告、隔离包0错误/33警告仅是历史，不作为新构建结论。
- realme已同签名覆盖至最终v34，用户反馈手动连接成功。约251秒、5次间隔至少60秒的白名单快照仅重复读到同一条已有心跳/HTTPS成功记录，没有取得本观察窗内新增计划心跳证据；实网短测门槛保留BLOCKED，不能写连续联网或后续心跳通过。未增加认证、注销、修复或额外网络探测。
- realme最终ARM64/ARM32 JNI、导出、菜单及ARM64约定安全回归PASS，句柄归零。真机UI仅font1/gesture完成自动检查，其中密码键盘截图内容区域为黑色，人工视觉BLOCKED、原因未证；font2/gesture设置和恢复字体写入返回255，保留FAIL，三键两项NOT_RUN。原系统设置只读核对一致，未换工具重试；最终隔离包已恢复并停止。
- iQOO12/V2307A本轮未连接，历史v33短时联网与64位JNI不能转为本轮v34通过，也不能替代v7a实际运行。
- Doze组合、8小时自然锁屏、连续外网、全面厂商适配、全部进程生命周期及正式签名迁移不在本轮自动执行范围。服务端TTL未知，不推测数值。
- 独立公开下载验证及可选问题模板上传的历史阻塞未假称完成；本轮没有重试被拒绝的浏览器上传/下载或历史AVD清理。

## 产品与安全边界

保持minSdk26、targetSdk35、手机双ARM ABI及既有测试签名；x86_64只用于隔离模拟器。不改协议、生产端点、MAC/客户端标识，不绕过认证或降低TLS校验。不把精确闹钟、电池豁免或通知许可变成连接硬门槛。

真实登录、注销、修复由用户手动发起；网络丢失或身份变化后停止并等待手动连接，进程终止/force-stop/重启后不自动认证。修复仍需确认、自身注销成功、客户端100秒等待、最多一次重登，停止/网络变化/服务结束/证据过期取消。

隔离用例仅使用org.esurfing.hunan.isolation、设备127.0.0.1、合成模块和虚构凭据。主应用不清数据、不卸载、不做破坏性用例。白名单采集不包含账号、密码、票据、密钥、完整抓包或完整日志。

原源码、原交付、发布副本及发布归档共1442个保护文件阶段前后核对；检查结果必须以最终保护审计为准。所有写入位于本轮工作/输出目录；不删除历史交付释放空间，封存后另起修订。设计支持API26起不代表“大部分手机”已验证。
