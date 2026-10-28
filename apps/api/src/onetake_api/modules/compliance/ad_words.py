"""广告违禁词 / 绝对化用语扫描（Phase 5）。

《广告法》第九条禁止"国家级、最高级、最佳"等绝对化用语；平台还会额外拦截
"全网最低、史上最低"这类无法验证的价格表述。这里给出一个保守的起步词表 +
位置返回，便于前端直接高亮。
"""
from __future__ import annotations

from onetake_api.modules.compliance.domain import BannedWordHit

# 保守起步词表：命中即提示，不自动改写（改写交给文案作者决定）
BANNED_WORDS: tuple[str, ...] = (
    "国家级", "最高级", "最佳", "最好", "第一品牌", "全国第一", "世界第一",
    "绝无仅有", "史无前例", "独一无二", "万能", "包治", "根治", "永久",
    "彻底解决", "无副作用", "纯天然", "100%", "百分百",
    "全网最低", "史上最低", "最便宜", "最低价", "顶级", "极致", "唯一",
)

ABSOLUTE_PHRASES = BANNED_WORDS


def scan(text: str, *, where: str) -> list[BannedWordHit]:
    """返回命中词与位置（index 为词在文本中的起始下标）。"""
    if not text:
        return []
    hits: list[BannedWordHit] = []
    for word in BANNED_WORDS:
        start = text.find(word)
        while start >= 0:
            hits.append(BannedWordHit(word=word, where=where, index=start))
            start = text.find(word, start + len(word))
    return sorted(hits, key=lambda hit: hit.index)