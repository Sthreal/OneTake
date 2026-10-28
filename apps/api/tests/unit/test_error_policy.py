"""错误码 → 分类 → 动作 的对照契约（S10 地基）。

权威实现只有 `platform.errors.ERROR_POLICY` 一张表；本测试保证：

1. **每个既有错误码都可分类**（取值域闭在 `ERROR_CLASSES` / `RECOVER_ACTIONS` 内）；
2. **未登记的码走最保守默认**（permanent / require_human）—— 没登记就是不许机器自己动；
3. **表里不许有指向已删除码的死行**（防止改名后留下幽灵策略）；
4. **分类不从 `retryable` 推导**：一整族「等人做动作」的码 retryable=True，却必须交人工。
"""
from __future__ import annotations

import importlib
import pathlib

import onetake_api
from onetake_api.platform.errors import (
    DEFAULT_ERROR_CLASS,
    DEFAULT_RECOVER_ACTION,
    ERROR_CLASSES,
    ERROR_POLICY,
    RECOVER_ACTIONS,
    DomainError,
    resolve_error_policy,
)


def _module_names() -> list[str]:
    """包内所有模块的完整名（按文件系统遍历）。

    **不用 `pkgutil.walk_packages`**：它列不进没有 `__init__.py` 的目录，而
    `modules/content_qa` 正是这样一个目录 —— 会安静漏掉它里面声明的两个错误码。
    """
    root = pathlib.Path(onetake_api.__path__[0])
    names: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(root.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        names.append(".".join(parts))
    return names


def _discovered_error_codes() -> dict[str, type[DomainError]]:
    """遍历包内所有模块，收集 DomainError 的具体子类（按 code 去重）。"""
    found: dict[str, type[DomainError]] = {}
    for name in _module_names():
        try:
            module = importlib.import_module(name)
        except Exception:  # pragma: no cover - 可选依赖缺失时跳过该模块
            continue
        for value in vars(module).values():
            if not isinstance(value, type) or value is DomainError:
                continue
            if not issubclass(value, DomainError):
                continue
            code = getattr(value, "code", None)
            if isinstance(code, str) and code:
                found[code] = value
    return found


def test_every_existing_error_code_is_classifiable() -> None:
    discovered = _discovered_error_codes()
    assert len(discovered) >= 71, f"错误码只有 {len(discovered)} 个，遍历可能没跑到全部模块"
    for code in discovered:
        error_class, action = resolve_error_policy(code)
        assert error_class in ERROR_CLASSES, (code, error_class)
        assert action in RECOVER_ACTIONS, (code, action)


def test_unregistered_codes_fall_back_to_conservative_default() -> None:
    assert (DEFAULT_ERROR_CLASS, DEFAULT_RECOVER_ACTION) == ("permanent", "require_human")
    assert resolve_error_policy("TOTALLY_UNKNOWN_CODE") == ("permanent", "require_human")


def test_policy_table_has_no_dead_rows() -> None:
    discovered = set(_discovered_error_codes())
    dead = sorted(set(ERROR_POLICY) - discovered)
    assert dead == [], f"ERROR_POLICY 里有已不存在的错误码：{dead}"


def test_transient_codes_are_machine_retryable() -> None:
    for code in (
        "RECOGNITION_PROVIDER_ERROR",
        "SCRIPT_PROVIDER_ERROR",
        "VOICE_PROVIDER_ERROR",
        "MATTING_PROVIDER_ERROR",
        "WAN_R2V_ERROR",
        "VIDEO_SEGMENT_GENERATION_FAILED",
    ):
        assert resolve_error_policy(code) == ("transient", "retry"), code


def test_policy_codes_require_human() -> None:
    assert resolve_error_policy("AIGC_LABEL_CHECK_FAILED") == ("policy", "require_human")


def test_classification_is_not_derived_from_retryable_flag() -> None:
    """必须交人工的码里，有相当一批 `retryable=True`（面向客户端的语义）—— 故意不同源。"""
    discovered = _discovered_error_codes()
    human_codes = {
        code for code in discovered if resolve_error_policy(code)[1] == "require_human"
    }
    retryable_but_human = sorted(
        code for code in human_codes if getattr(discovered[code], "retryable", False)
    )
    assert len(retryable_but_human) >= 5, retryable_but_human
    # 典型代表：冲突类错误是「等人做完动作再重试」，机器盲目重试只会再撞一次
    assert "VIDEO_CONFLICT" in retryable_but_human