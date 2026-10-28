"""零引用（死路径）检查：把「这个路径没人引用」从一次肉眼 grep 变成**可复现命令**。

用法（仓库根目录）：

    python scripts/check_dead_paths.py                 # 只跑「已删路径守护」+ 已登记候选
    python scripts/check_dead_paths.py <路径> [<路径>…]  # 指定候选，逐个报引用数

它回答一个问题：**这个路径现在能不能删？**
- 候选路径：统计**所有 git 跟踪文件**里的字符串引用（排除它自己子树、node_modules 与二进制）
  —— **0 引用**才允许进入"删除"类切片；有引用就打印引用点并退出非 0，意思是"先别删"。
- 已删路径守护：断言它们**没有再出现**（文件系统 + git 清单都查），防止误还原/误重建。

**为什么需要它**（S4 的由来）：`apps/worker` 与 `mvp/` 躺了很久没人敢删，每次都要重新肉眼判断；
而肉眼 grep 很容易被两类东西骗到 ——
① **二进制里的巧合字节**（例如 electron 的 `.png`/`.icns` 里恰好含 "mvp" 三字节）；
② **注释/文档里提到该路径**（不是真引用）。
所以本脚本只扫**文本类扩展名**、并把命中点连行号打印出来，让人一眼能分辨"真引用 vs 文字提及"。

设计约束（与 `scripts/check_real_chain.py` 同风格）：**只读** —— 只遍历 git 跟踪的文件，
不写入、不删除、不发网络请求。Windows 控制台默认 GBK，故先 reconfigure stdout。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 只扫这些扩展名（避免二进制误报 —— 这是本脚本存在的一半理由）
TEXT_SUFFIXES = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".jsonc",
    ".md", ".markdown", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".txt",
    ".html", ".htm", ".css", ".scss", ".sh", ".bash", ".ps1", ".sql", ".env",
    ".example", ".gitignore", ".dockerignore", ".editorconfig", ".prettierrc",
}
SKIP_PARTS = ("node_modules/", ".git/", "dist/", "build/", "__pycache__/")
MAX_BYTES = 1_500_000  # 超大文本文件跳过（本仓最大的源码约 780KB）

# ---- 已删路径守护：这些**必须保持不存在** ----
DELETED_GUARDS: dict[str, str] = {
    "apps/worker": "S4（2026-10-14）删除：零引用 stub；备份 2026-10-14_s4_apps_worker.zip",
    "mvp": "S4（2026-10-14）删除：本地静态原型（原本就被 gitignore）；备份 2026-10-14_s4_mvp_local.zip",
}

# ---- 已登记但**不删**的路径（实测有活引用，或用户口径为保留）----
# 记录在这里的价值：下一次有人想删它时，会先看到这条结论，而不是重新踩一遍。
RETAINED_WITH_REASON: dict[str, str] = {
    "apps/api/src/onetake_api/integrations/product_scene/avatar_assets.py":
        "有活引用：apps/api/tests/unit/test_avatar_video_service.py::test_mock_avatar_asset_is_available"
        "（该用例 docstring 记明按用户「暂时」口径保留文件，资产自检继续有效）",
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return [line for line in out.stdout.split("\n") if line.strip()]


def is_scannable(path: str) -> bool:
    if any(part in path for part in SKIP_PARTS):
        return False
    name = Path(path).name
    if name in TEXT_SUFFIXES:
        return True
    return Path(path).suffix.lower() in TEXT_SUFFIXES


# 导入族关键字：用于把「裸名/模块名」的命中判成**真引用**；否则只能算**文字提及**。
IMPORT_HINT = re.compile(
    r"\b(from|import|require|include|COPY|ADD|source|module|use)\b|\.include\b|--include"
)


def needles_for(candidate: str) -> list[tuple[str, bool]]:
    """候选路径 → [(needle, 是否"路径形式")]。

    **为什么不能只按文件路径搜**：本仓大量引用是**模块形式**（Python `from x.y import z`、
    TS `from "./x"`），文件路径那一串根本不会出现 —— 只按路径搜会得出"0 引用、可以删"的
    **假结论**（本脚本第一版就踩了这个坑：`avatar_assets.py` 被测试以
    `onetake_api.integrations.product_scene.avatar_assets` 导入，按路径搜却是 0）。
    因此每个候选同时产出：路径形式（`a/b/c.py`、反斜杠版）+ 点分模块形式 + 裸名（stem）。
    """
    clean = candidate.rstrip("/")
    out: list[tuple[str, bool]] = [(clean, True), (clean.replace("/", "\\"), True)]

    if clean.endswith((".py", ".pyi")):
        parts = clean.split("/")
        # 取 src/ 之后的部分作为模块路径（本仓 Python 源码都在 .../src/<pkg>/...）
        if "src" in parts:
            tail = parts[parts.index("src") + 1:]
            module = ".".join(tail)[: -3] if tail[-1].endswith((".py", ".pyi")) else ".".join(tail)
            out.append((module, False))
        out.append((parts[-1][: -3], False))
    elif clean.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        stem = ".".join(clean.split("/")[-1].split(".")[:-1])
        out.append((stem, False))
        out.append(("./" + stem, True))
    # 去重（保持顺序）
    seen, uniq = set(), []
    for needle, blocking in out:
        if needle and needle not in seen:
            seen.add(needle)
            uniq.append((needle, blocking))
    return uniq


def scan(needles: list[tuple[str, bool]], files: list[str], *, exclude_prefix: str | None):
    """返回 (真引用 hits, 文字提及 mentions)，均为 [(path, line, 片段)]。"""
    patterns = [(re.compile(re.escape(n)), blocking, n) for n, blocking in needles]
    hits, mentions = [], []
    for path in files:
        if exclude_prefix and (path == exclude_prefix or path.startswith(exclude_prefix.rstrip("/") + "/")):
            continue
        if not is_scannable(path):
            continue
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        lines = text.split("\n")
        for pattern, blocking, needle in patterns:
            for match in pattern.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                snippet = lines[line_no - 1].strip()[:110] if line_no - 1 < len(lines) else ""
                # 路径形式 → 一律算真引用；模块/裸名形式 → 只有出现在导入族语句里才算
                blocking_hit = blocking or bool(IMPORT_HINT.search(snippet))
                (hits if blocking_hit else mentions).append((path, line_no, snippet))
    # 同一行被多个 needle 命中时去重（点分模块名与裸名常常同时命中同一行）
    return _dedupe(hits), _dedupe(mentions)


def _dedupe(items: list[tuple[str, int, str]]) -> list[tuple[str, int, str]]:
    seen, out = set(), []
    for item in sorted(items, key=lambda x: (x[0], x[1])):
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def check_guards() -> int:
    print("== 已删路径守护（必须不存在）==")
    bad = 0
    for path, reason in DELETED_GUARDS.items():
        exists = Path(path).exists()
        tracked = bool(
            subprocess.run(
                ["git", "ls-files", "--error-unmatch", path],
                capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
        )
        status = "❌ 又出现了" if (exists or tracked) else "✅ 仍不存在"
        if exists or tracked:
            bad += 1
        print(f"  {status}  {path}\n            {reason}")
    return 1 if bad else 0


def check_candidates(candidates: list[str], files: list[str]) -> int:
    if not candidates:
        print("\n== 候选路径引用检查 ==（本次没有传入候选；用法见文件头）")
        if RETAINED_WITH_REASON:
            print("  已登记「保留」的路径（不要再当作删除候选）：")
            for path, reason in RETAINED_WITH_REASON.items():
                print(f"    - {path}\n        {reason}")
        return 0

    print("\n== 候选路径引用检查 ==")
    referenced = 0
    for candidate in candidates:
        hits, mentions = scan(needles_for(candidate), files, exclude_prefix=candidate.rstrip("/"))
        if hits:
            referenced += 1
            print(f"  ⚠️  {candidate}：{len(hits)} 处**真引用** → 还不能删")
            for path, line, snippet in hits[:10]:
                print(f"        {path}:{line}  {snippet}")
        else:
            print(f"  ✅ {candidate}：0 处真引用 → 可进入删除类切片（仍需单独授权 + 先备份）")
        if mentions:
            print(f"      （另有 {len(mentions)} 处**文字提及**，不阻断删除；前 3 条：）")
            for path, line, snippet in mentions[:3]:
                print(f"        {path}:{line}  {snippet}")
    return 1 if referenced else 0


def main(argv: list[str]) -> int:
    files = tracked_files()
    print(f"git 跟踪文件：{len(files)} 个（只扫文本类扩展名，已跳过 node_modules/dist/二进制）")
    rc = check_guards()
    rc |= check_candidates(argv[1:], files)
    print("\n结论：" + ("全部符合预期 ✅" if rc == 0 else "有需要人工处理的项目 ❌（见上）"))
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))