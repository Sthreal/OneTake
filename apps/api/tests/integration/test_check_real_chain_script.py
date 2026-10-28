"""脚本防腐烂（rot guard）：`scripts/check_real_chain.py` 必须真的跑得起来。

为什么需要这条：`scripts/` 下的脚本没有任何测试会执行，于是它"看起来在自检"、
实际一跑就崩 —— 实测：该脚本引用了 M4-03 提交 1 **已删除**的 `settings.product_scene_enabled`，
于是每次执行都在 `_check()` 抛 `AttributeError`，而 `docs/收尾总方案.md` §4 仍把它列为
"配置齐全"这一步的验证命令（照文档执行的人会直接撞到异常）。

这条用例只做一件事：**以子进程真的跑一次脚本**，不允许出现 Traceback。
（它不做付费调用、不连数据库 —— 脚本本身只读配置 + 算数。）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]   # apps/api/tests/integration → 仓库根
SCRIPT = REPO_ROOT / "scripts" / "check_real_chain.py"


def test_check_real_chain_script_runs_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
    )
    output = (result.stdout or "") + (result.stderr or "")

    assert "Traceback" not in output, f"脚本抛异常了：\n{output}"
    # 0 = 配置齐全；1 = 如实报告"缺哪些键"（也是脚本正常工作，不是失败）
    assert result.returncode in (0, 1), f"退出码 {result.returncode}：\n{output}"
    # 两条路径的预估都必须打印出来（它们直接来自生产估算函数）
    assert "分段路径" in output, output
    assert "整片一次生成" in output, output
