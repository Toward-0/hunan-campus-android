"""Package reviewed source and explicitly supplied current-build evidence only.

Do not run until the final build and tests are complete. Use --snapshot-input
before the final build, then --results evidence/delivery-results.json to package.
Private configuration, original device logs, SDKs and credentials are excluded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile


STATUS = {"PASS", "FAIL", "NOT_RUN", "BLOCKED"}
VERSION = 36
VERSION_NAME = "0.2.24-background"
CERT = "2df9ad39258e06a0174c45862dbd3bf1611d566e0dead5cae43a26a213b1b229"
SCRIPTS = ("package-current.py", "run-current-build.ps1", "adb_client.py", "run_isolation.py", "run_idle.py", "install_main.py", "device_read.py", "observe_main.py", "inspect_runtime.py", "reconcile_rotation.py", "api26_controller_public.py")
FORBIDDEN_PARTS = {"build", ".gradle", ".cxx", "cxx", "sdk", "gradle-user", "avd", "__pycache__"}
FORBIDDEN_NAMES = {"local.properties", "tools.local.json", ".env", "adbkey", "adbkey.pub"}
FORBIDDEN_SUFFIXES = {".keystore", ".jks", ".p12", ".pem", ".key", ".apk", ".pcap", ".pcapng", ".pyc"}
NEW_SOURCE_SUFFIXES = {".kt", ".java", ".xml", ".txt", ".md", ".ps1", ".py", ".kts", ".c", ".h", ".cmake", ".gradle", ".json", ".properties", ".bat", ".sh", ".yml", ".yaml"}
TESTS = (
    ("BUILD-DUAL-ARM", "主包及隔离包构建成功，保留 minSdk26 / targetSdk35 和双 ARM ABI"),
    ("SIGNATURE-ALIGNMENT", "签名等于既有测试证书；最终 APK 的 16KB ZIP 对齐检查成功"),
    ("LINT", "完成当前主包与隔离包 Lint，分别报告错误和警告数"),
    ("REALME-INSTALL", "在已连接 realme 同签名覆盖安装当前 APK，保留主应用数据"),
    ("ALARM-RACE-CANCEL", "定时器与闹钟只交付一次；取消及代次变化后不执行旧任务；无残留回调"),
    ("SCHEDULER-IDLE-MATRIX", "分别记录实际 Doze、权限、调度模式、样本数及延迟，不把定时器称为唤醒保证"),
    ("DIAGNOSTIC-EXPORT", "完整 JSON 白名单导出包含后台能力及实际交付来源"),
    ("SESSION-SAFETY", "隔离包验证停止、代次取消及资源释放，不增加自动认证"),
    ("REAL-NETWORK-SHORT", "用户手动连接后取得观察窗内新增的心跳和外网证据"),
    ("NATURAL-LOCK-8H", "真实拔电自然锁屏至少8小时；报告心跳间隔、断线和耗电"),
    ("ARM64-JNI", "当前隔离包在实际ARM64进程完成异常输入、200次循环及句柄归零"),
    ("MAIN-ISOLATION-EXCLUSION", "当前主包Manifest、DEX组件和原生库不含隔离测试入口"),
    ("SOURCE-BUILD-BINDING", "最终源码与构建前清单一致，明确重构建与已测APK的哈希关系"),
    ("ENVIRONMENT-RESTORATION", "强制休眠、隔离包电池豁免和屏幕状态按测试前状态恢复并记录退出码"),
    ("PROTECTED-V34-BASELINE", "v34保护基线238个源码文件前后SHA256均不变"),
    ("API26-REGRESSION", "当前v36在API26隔离模拟器完成调度、诊断、100次会话循环和JNI回归"),
    ("API35-FORCED-IDLE", "当前v36在API35实际深度Doze下完成3个合成任务，逐样本延迟<=3000ms，回调归零且恢复设置"),
    ("REALME-OEM-BACKGROUND-POLICY", "同一应用后台行为开关前后核对OEM附加闹钟延期，设置结果与锁屏联网结果分开记录"),
    ("REAL-NETWORK-FIRST-ATTEMPT", "保留OEM设置调整前的实际v36短测结果，不以复测覆盖原始失败"),
    ("REAL-NETWORK-RAW-COLLECTOR", "保留OEM设置调整后原收集器的轮转漏采结果，补齐证据单独说明"),
)
HISTORY_GAPS = [
    "v34 阶段1未通过；本专项不将历史测试结论改为当前版本通过。",
    "ARM64 / 16KB 实机运行环境缺失；静态对齐不能替代运行验证。",
    "既有大字体系统状态栏裁切、API矩阵和realme键盘视觉缺口不属于本次已解决结论。",
    "8小时自然锁屏、全面厂商适配、全部进程生命周期及耗电仍须独立证据。",
]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git(repo: Path, *args: str, accepted=(0,)) -> bytes:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    if result.returncode not in accepted:
        raise RuntimeError("Git command failed: " + " ".join(args[:2]))
    return result.stdout


def source_paths(repo: Path) -> list[Path]:
    tracked = set(git(repo, "ls-files", "-z", "--", "source").decode("utf-8").split("\0")) - {""}
    added = set(git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", "source").decode("utf-8").split("\0")) - {""}
    selected = []
    for name in sorted(tracked | added):
        path = repo / name
        if not path.is_file():
            continue
        relative = Path(name)
        if any(p in FORBIDDEN_PARTS for p in relative.parts) or path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            continue
        if path.is_symlink():
            raise ValueError("Source symlink requires review: " + name)
        if name in added and path.suffix.lower() not in NEW_SOURCE_SUFFIXES:
            raise ValueError("Unreviewed new source type: " + name)
        selected.append(path)
    return selected


def source_manifest(repo: Path, files: list[Path]) -> dict:
    return {"versionCode": VERSION, "versionName": VERSION_NAME, "files": [
        {"path": path.relative_to(repo / "source").as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
        for path in files
    ]}


def source_changes(baseline: dict, current: dict) -> list[dict]:
    before = {item["path"]: item for item in baseline["files"]}
    after = {item["path"]: item for item in current["files"]}
    changes = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old and new and old["sha256"].upper() == new["sha256"].upper():
            continue
        changes.append({"path": name, "change": "added" if old is None else "deleted" if new is None else "modified",
                        "beforeSha256": old["sha256"] if old else None, "afterSha256": new["sha256"] if new else None,
                        "beforeBytes": old["bytes"] if old else None, "afterBytes": new["bytes"] if new else None})
    return changes


def zip_files(destination: Path, entries: list[tuple[Path, str]]) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, name in entries:
            if path.is_symlink() or ".." in Path(name).parts:
                raise ValueError("Unsafe archive entry")
            archive.write(path, name)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC verification failed")


def make_report(validation: dict) -> str:
    binding = validation["binding"]
    lines = [
        "湖南校园网 Android：后台运行专项", "",
        f"当前版本：{VERSION_NAME} / versionCode {VERSION}",
        f"生成时间：{validation['createdAt']}",
        "交付状态：仅本地开发与验证，尚未推送GitHub或创建Release。",
        f"源码清单 SHA256：{binding['sourceManifestSha256']}",
        "",
        "本次修改",
        "1. 每个任务同时安排进程内定时器和系统闹钟，共用一次性交付与取消保护；CPU运行时避免单纯依赖非精确闹钟批处理。",
        "2. 处于Doze且未获电池豁免时，定时器让已注册的闹钟交付，避免抢占后取消闹钟的临时执行机会；定时器不能唤醒深度休眠CPU或绕过Doze配额。",
        "3. 增加后台能力检查与用户主动设置入口，诊断记录权限和真实任务交付来源；权限不是登录硬门槛。",
        "4. 心跳延迟改用单调时钟；保持手动认证、代次取消和有界请求唤醒锁。",
        "",
        "当前 APK",
    ]
    for item in binding["apks"]:
        lines.extend([item["file"], "SHA256：" + item["sha256"]])
    if validation.get("findings"):
        lines.extend(["", "本轮现场发现"])
        lines.extend(validation["findings"])
    lines.extend(["", "本轮验证（仅按当前证据填写）"])
    for item in validation["tests"]:
        lines.append(f"[{item['status']}] {item['testId']}：{item['actual']}")
    lines.extend(["", "支持范围与限制", "设计基线：Android API26起，targetSdk35，arm64-v8a及armeabi-v7a；当前实测范围以validation.json的environment和tests为准。"])
    lines.extend(HISTORY_GAPS)
    lines.extend(validation.get("limitations", []))
    lines.extend(["", "使用说明", "覆盖安装候选主APK后，由用户打开应用并手动连接。在“更多”检查后台定时、电池优化和通知能力，根据手机实际页面允许后台运行。", "网络丢失或身份变化、进程终止、强制停止及重启后等待手动连接；本专项不增加自动账号提交。", "自然锁屏长测未通过前，不宣称长期保活或8小时稳定性已验证。", "", "复现资料", "source.zip 为当前源码输入副本；changes.json与changes.diff列出相对v34的源码修改。scripts.zip仅含审查后的工具白名单。", "repo-documentation.zip及对应diff是仓库顶层README与后台运行说明，不属于APK源码输入，不改动source.zip。", "源码中的历史文档按原字节保留，其旧版本与旧验收不能替代本报告和validation.json。", "私有tools.local.json、签名密钥、工具链缓存、设备标识和原始设备日志不包含在交付包中。"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot-input", action="store_true")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--extra-script", action="append", default=[])
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    if (repo / "SEALED").exists() or (repo / "SEALED.json").exists():
        raise ValueError("Stage is sealed")
    tools = json.loads((repo / "tools.local.json").read_text(encoding="utf-8-sig"))
    output = (args.output or Path(tools["OutputRoot"])).resolve()
    if output != Path(tools["OutputRoot"]).resolve():
        raise ValueError("Output must match current stage configuration")
    source = source_paths(repo)
    current = source_manifest(repo, source)
    build_input = repo / "evidence" / "final-build-source-manifest.json"
    if args.snapshot_input:
        if build_input.exists():
            raise ValueError("Preserve the existing final build snapshot before replacing it")
        write_json(build_input, current)
        print(json.dumps({"status": "PASS", "sourceFiles": len(source), "sourceManifestSha256": sha(build_input)}))
        return
    if args.results is None:
        parser.error("--results is required for final packaging")
    results = json.loads(args.results.resolve(strict=True).read_text(encoding="utf-8-sig"))
    if results.get("versionCode") != VERSION or results.get("versionName") != VERSION_NAME:
        raise ValueError("Results must explicitly belong to the current version; do not reuse prior-version results")
    if not build_input.exists() or json.loads(build_input.read_text(encoding="utf-8-sig")) != current:
        raise ValueError("Current source differs from the final build input snapshot")
    provenance_path = repo / "evidence" / "source-snapshot-verification.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig")) if provenance_path.exists() else {"method": "PRE_BUILD_SNAPSHOT"}
    if provenance.get("status", "PASS") != "PASS" or provenance.get("sourceManifestSha256", sha(build_input)) != sha(build_input):
        raise ValueError("Source snapshot verification is not a matching PASS")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "source-manifest.json", current)
    baseline = json.loads((repo / "evidence" / "baseline-manifest.json").read_text(encoding="utf-8-sig"))
    changes = source_changes(baseline, current)
    write_json(output / "changes.json", {"base": "v34 / f8a8de2", "versionCode": VERSION, "changes": changes})
    diff = git(repo, "diff", "--no-ext-diff", "--binary", "--", "source")
    tracked = set(git(repo, "ls-files", "-z", "--", "source").decode("utf-8").split("\0"))
    for path in source:
        relative = path.relative_to(repo).as_posix()
        if relative not in tracked:
            diff += git(repo, "diff", "--no-ext-diff", "--no-index", "--binary", "--", os.devnull, relative, accepted=(0, 1))
    (output / "changes.diff").write_bytes(diff)
    zip_files(output / "source.zip", [(path, path.relative_to(repo).as_posix()) for path in source])
    scripts = list(SCRIPTS)
    for name in args.extra_script:
        if Path(name).name != name or Path(name).suffix not in {".py", ".ps1"}:
            raise ValueError("Additional scripts must be reviewed files in the repository root")
        if name not in scripts:
            scripts.append(name)
    # Explicit whitelist: never recursively archive evidence or tool directories.
    zip_files(output / "scripts.zip", [(repo / name, name) for name in scripts])
    docs = [repo / name for name in ("README.md", "docs/BACKGROUND_KEEPALIVE.md")]
    zip_files(output / "repo-documentation.zip", [(path, path.relative_to(repo).as_posix()) for path in docs])
    docs_diff = git(repo, "diff", "--no-ext-diff", "--", "README.md", "docs/BACKGROUND_KEEPALIVE.md")
    tracked_docs = set(git(repo, "ls-files", "-z", "--", "README.md", "docs/BACKGROUND_KEEPALIVE.md").decode("utf-8").split("\0"))
    for path in docs:
        relative = path.relative_to(repo).as_posix()
        if relative not in tracked_docs:
            docs_diff += git(repo, "diff", "--no-ext-diff", "--no-index", "--", os.devnull, relative, accepted=(0, 1))
    (output / "repo-documentation.diff").write_bytes(docs_diff)
    write_json(output / "repo-documentation-manifest.json", {"scope": "Repository documentation only; not APK source inputs", "files": [{"path": path.relative_to(repo).as_posix(), "sha256": sha(path)} for path in docs]})
    apk_paths = sorted(output.glob(f"ESurfingHunan-{VERSION_NAME}-*.apk"))
    if not apk_paths or not any("candidate-phone" in path.name for path in apk_paths):
        raise ValueError("Current main APK missing")
    apks = [{"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size} for path in apk_paths]
    supplied = {item["testId"]: item for item in results.get("tests", [])}
    tests = []
    for test_id, expected in TESTS:
        item = supplied.pop(test_id, {})
        status = item.get("status", "NOT_RUN")
        if status not in STATUS:
            raise ValueError("Invalid test status: " + test_id)
        if any(name not in {path.name for path in apk_paths} for name in item.get("testedApks", [])):
            raise ValueError("A test references a non-current APK: " + test_id)
        tests.append({"testId": test_id, "status": status, "expected": item.get("expected", expected),
                      "actual": item.get("actual", "尚未取得当前构建证据"), "evidence": item.get("evidence", []),
                      "time": item.get("time"), "environment": item.get("environment", "see environment"),
                      "buildBinding": "binding", "testedApks": item.get("testedApks", [])})
    if supplied:
        raise ValueError("Review additional test IDs before packaging: " + ", ".join(supplied))
    validation = {"schema": 1, "createdAt": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(),
        "scope": "Android background execution revision; historical stage1 gates remain unchanged",
        "binding": {"versionCode": VERSION, "versionName": VERSION_NAME, "baseCommit": git(repo, "rev-parse", "HEAD").decode().strip(),
                    "sourceManifestSha256": sha(output / "source-manifest.json"), "buildInputManifestSha256": sha(build_input),
                    "sourceArchiveSha256": sha(output / "source.zip"), "expectedCertificateSha256": CERT, "apks": apks,
                    "sourceSnapshotMethod": provenance["method"], "sourceSnapshotLimitation": provenance.get("limitation")},
        "environment": results.get("environment", {}), "toolchain": results.get("toolchain", {}),
        "tests": tests, "historyGaps": HISTORY_GAPS, "limitations": results.get("limitations", []), "findings": results.get("findings", [])}
    write_json(output / "validation.json", validation)
    (output / "保活专项报告.txt").write_text(make_report(validation), encoding="utf-8")
    evidence = sorted(path for path in (output / "evidence").rglob("*") if path.is_file() and (path.suffix in {".json", ".txt", ".diff", ".xml", ".html"} or path.name in {"oem-background-before.png", "oem-background-after.png"})) if (output / "evidence").exists() else []
    write_json(output / "evidence-index.json", {"files": [{"file": path.relative_to(output).as_posix(), "sha256": sha(path)} for path in evidence]})
    signing_sidecars = [Path(str(path) + ".idsig") for path in apk_paths if Path(str(path) + ".idsig").is_file()]
    deliverables = [*apk_paths, *signing_sidecars, *evidence, *(output / name for name in ("source-manifest.json", "changes.json", "changes.diff", "source.zip", "scripts.zip", "repo-documentation.zip", "repo-documentation.diff", "repo-documentation-manifest.json", "validation.json", "evidence-index.json", "保活专项报告.txt"))]
    (output / "SHA256SUMS.txt").write_text("".join(f"{sha(path)}  {path.relative_to(output).as_posix()}\n" for path in sorted(deliverables, key=lambda p: p.relative_to(output).as_posix())), encoding="utf-8")
    print(json.dumps({"status": "PASS", "sourceFiles": len(source), "changedFiles": len(changes), "apks": apks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
