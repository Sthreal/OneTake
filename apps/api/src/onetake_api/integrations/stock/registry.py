"""素材源聚合（批次 4a）：源顺序、跨镜去重、宽泛词回退、失败与"没结果"分开表达。

**源顺序的事实依据**（实测 2026-10-14）：
- **视频**：Wikimedia Commons（它是唯一有免 Key 实拍视频的源）；Openverse 没有视频接口。
- **音频**（BGM 音源）：Openverse 优先（许可元数据更规整）→ Wikimedia 兜底。

**错误语义**：所有源都**报错** → 抛 `StockError`（调用方据此回退原路径并留下原因）；
所有源都**正常但没结果** → 返回 `None`（这是"确实没素材"，不是故障）。两者不能混。
"""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Callable

import httpx

from onetake_api.integrations.stock import openverse, wikimedia
from onetake_api.integrations.stock.domain import StockAsset, StockError

SearchFn = Callable[..., list[StockAsset]]
_WORD_PATTERN = re.compile(r"[A-Za-z0-9]+")


def video_sources() -> tuple[SearchFn, ...]:
    """**调用时**解析源（不是 import 时冻结）：换源/打桩/灰度都不用改这里。"""
    return (wikimedia.search_videos,)


def audio_sources() -> tuple[SearchFn, ...]:
    return (openverse.search_audio, wikimedia.search_audio)


def find_video(
    query: str, *, limit: int = 5, exclude_ids: Collection[str] = (), client: httpx.Client | None = None
) -> StockAsset | None:
    return _find(video_sources(), query, limit=limit, exclude_ids=exclude_ids, client=client)


def find_audio(
    query: str, *, limit: int = 5, exclude_ids: Collection[str] = (), client: httpx.Client | None = None
) -> StockAsset | None:
    return _find(audio_sources(), query, limit=limit, exclude_ids=exclude_ids, client=client)


def _find(
    sources: Sequence[SearchFn], query: str, *, limit: int, exclude_ids: Collection[str], client: httpx.Client | None
) -> StockAsset | None:
    tried: list[str] = []
    errors: list[str] = []
    for candidate_query in (query, broaden_query(query)):
        if not candidate_query:
            continue
        for source in sources:
            name = f"{source.__module__.rsplit('.', 1)[-1]}.{source.__name__}"
            try:
                assets = source(candidate_query, limit=limit, client=client)
            except StockError as exc:
                errors.append(f"{name}({candidate_query})：{exc}")
                continue
            tried.append(name)
            for asset in assets:
                if asset.asset_id not in exclude_ids:
                    return asset
    if not tried and errors:
        raise StockError("所有素材源都检索失败：" + "；".join(errors))
    return None


def broaden_query(query: str) -> str | None:
    """宽泛词回退：丢掉**最后一个**词逐步放宽（"morning coffee routine" → "morning coffee"）。

    为什么是"丢尾部"而不是"只留首词"：检索词是"修饰 + 主体"的顺序（`morning coffee`），
    丢尾部保留的是主体所在的短语，比只留一个修饰词更可能命中。
    只做一个回退步（不做多级递归）——多级会把查询放宽到没有辨识度，反而撞上无关素材。
    单词查询没有回退余地 → 返回 None（调用方据此不再重试）。
    """
    words = _WORD_PATTERN.findall(query or "")
    if len(words) <= 1:
        return None
    return " ".join(words[:-1]).lower()