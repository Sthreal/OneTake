"""整片一次生成（Phase 3，r2v 参考生视频）的编排逻辑。

与分段路径的区别：分段是"每个分镜一次 i2v + 拼接"，整片是把**多个分镜关键帧一起**交给
参考生视频模型，由模型原生切镜、一次把台词说完——调用次数少、跨镜一致性好、音频无拼接缝。

两条硬约束（来自百炼 r2v 文档）：
1. `reference_image` + `reference_video` 合计 ≤ 5，其中 `first_frame` 最多 1 张
2. 单次调用 duration ≤ 15s（无视频参考时）→ 超过必须切分多次调用再拼接

本模块是纯逻辑（不触网、不落库），便于单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from onetake_api.modules.content_plan.domain import ContentScene
from onetake_api.modules.content_plan.prompt_schema import person_aware_action

MAX_CALL_SECONDS = 15
MAX_MEDIA_ITEMS = 5
# first_frame 占 1 个名额，参考图最多再放 4 张
MAX_REFERENCE_IMAGES = MAX_MEDIA_ITEMS - 1


@dataclass(frozen=True)
class OneShotCall:
    order: int
    start_seconds: float
    end_seconds: float
    scene_ids: list[str] = field(default_factory=list)
    prompt: str = ""

    @property
    def duration_seconds(self) -> float:
        return round(max(0.0, self.end_seconds - self.start_seconds), 3)


def plan_one_shot_calls(
    scenes: list[ContentScene],
    *,
    max_seconds: int = MAX_CALL_SECONDS,
    realism: bool = True,
    has_character: bool = False,
) -> list[OneShotCall]:
    """把分镜按"单次调用不超过 max_seconds"分组；超出就切分成多次调用再拼接。"""
    if not scenes:
        raise ValueError("分镜为空，无法编排整片生成")
    limit = max(1, int(max_seconds))
    ordered = sorted(scenes, key=lambda item: item.start_seconds)
    groups = group_beat_durations([scene.end_seconds - scene.start_seconds for scene in ordered], max_seconds=limit)
    if len(ordered) >= 2 and any(len(group) == 1 for group in groups):
        raise ValueError(
            "脚本时长分布无法满足参考生视频的参考图下限（每次调用至少需要 2 个分镜）："
            "请缩短脚本或改用分段生成"
        )
    calls: list[OneShotCall] = []
    cursor = 0
    for order, _group in enumerate(groups, start=1):
        size = len(_group)
        calls.append(_build_call(order, ordered[cursor : cursor + size], realism=realism, has_character=has_character))
        cursor += size
    return calls


def group_beat_durations(durations: list[float], *, max_seconds: int = MAX_CALL_SECONDS) -> list[list[float]]:
    """按"单次调用不超过 max_seconds"把镜头时长分组。

    与 plan_one_shot_calls 共用同一套分组规则（估算口径与真实调用必须一致）。
    """
    limit = max(1, int(max_seconds))
    groups: list[list[float]] = []
    bucket: list[float] = []
    total = 0.0
    for length in durations:
        if bucket and total + length > limit:
            groups.append(bucket)
            bucket = []
            total = 0.0
        bucket.append(length)
        total += length
    if bucket:
        groups.append(bucket)

    # 供应商约束（2026-10-15 实测原文：「Only first frame provided is not allowed」）：
    # r2v 每次调用**至少要 2 张参考图**，也就是每次调用至少要有 2 个分镜。
    # 切分时很容易留下"最后一组只有 1 镜"（例：3/3/7/5 + 上限 15 → [3,3,7] + [5]），
    # 那样第二次调用只会带 first_frame → 跑 6 分钟后被供应商拒绝（钱花了、片子没有）。
    # 修法：**把上一组的最后一镜挪给下一组**（等价于把边界往后移），只要两侧都不超上限。
    for index in range(1, len(groups)):
        while len(groups[index - 1]) > 1 and len(groups[index]) < 2:
            moved = groups[index - 1][-1]
            if sum(groups[index]) + moved > limit:
                break
            groups[index - 1].pop()
            groups[index].insert(0, moved)
    return groups


def _build_call(order: int, scenes: list[ContentScene], *, realism: bool = True, has_character: bool = False) -> OneShotCall:
    start = min(scene.start_seconds for scene in scenes)
    end = max(scene.end_seconds for scene in scenes)
    return OneShotCall(
        order=order, start_seconds=start, end_seconds=end,
        scene_ids=[scene.scene_id for scene in scenes],
        prompt=build_one_shot_prompt(
            scenes, call_start=start, call_end=end, realism=realism,
            character_ref=(len(scenes) + 1) if has_character else None,
        ),
    )


# 镜头类型标签（借 ClipForge 的 SHOT_TYPE_LABELS 思路：让模型知道这一镜的职能）
# 取值必须覆盖 content_plan/generator.py 的 BEATS 全部 purpose（2026-10-15 实测漏了 usage_scenario，
# 那一镜的标签渲染成了内部英文枚举 —— 用户一眼就看出来了）。
# 台词里的"气口/停顿"标记必须剥掉，否则会被模型**念出来**（借 ClipForge 的做法）
_PAUSE_MARKS = ("[pause]", "[停顿]", "［pause］", "（停顿）", "(pause)", "(停顿)", "……。")


def strip_pause_marks(text: str) -> str:
    cleaned = text
    for mark in _PAUSE_MARKS:
        cleaned = cleaned.replace(mark, "")
    return cleaned.strip()


SHOT_TYPE_LABELS = {
    "hook": "开场钩子",
    "selling_point": "卖点",
    "usage_scenario": "使用场景",
    "cta": "行动号召",
    # 预留（当前 BEATS 未使用，但创作模型可能产出）
    "pain_point": "痛点",
    "product_reveal": "商品亮相",
}


def build_one_shot_prompt(
    scenes: list[ContentScene], *, call_start: float, call_end: float, realism: bool = True,
    character_ref: int | None = None,
) -> str:
    """整片提示词（**按阿里万相 r2v 官方 prompt 约定**写，2026-10-15 重写）。

    官方约定（摘自 help.aliyun.com/zh/model-studio/wan-video-to-video-api-reference）：
    - 中文提示词用「图 1、图 2」指代参考图片（**字母与数字之间要有空格**），顺序与 media 数组一致；
      图和视频分别计数；只有一张参考图时可简化写「参考图片」。
    - 首帧（first_frame）最多 1 张，且**参考图/参考视频至少要有 1 个** —— 这就是
      “Only first frame provided is not allowed” 的出处。
    - 无视频参考时 duration 取 2~15 秒。

    借自 ClipForge（storyboard-film.ts:267 buildStoryboardFilmPrompt）的四条**意图**（不是它的括号语法）：
    ① 逐镜时间码段落；② 每镜带**运镜**（注释原话：丢了运镜 = 每镜退化成静止帧）；
    ③ **镜头职能标签**（钩子/痛点/卖点/CTA）；④ 无台词镜**显式说明**只保留环境音与动作声。
    （它用大括号标记台词是 Seedance 方言，阿里不认，所以这里写成自然语言的“逐字说出”。）
    """
    ordered = sorted(scenes, key=lambda item: item.start_seconds)
    every = "参考图片" if len(ordered) == 1 else "对应的参考图片"
    lines: list[str] = [
        f"生成一段 {call_end - call_start:.0f} 秒的竖版带货短视频，包含 {len(ordered)} 个镜头，镜头之间原生切换。"
    ]
    for index, scene in enumerate(ordered, start=1):
        start = scene.start_seconds - call_start
        end = scene.end_seconds - call_start
        reference = "参考图片" if len(ordered) == 1 else f"图 {index}"
        action = scene.subject_action or scene.visual_goal or "展示商品"
        if character_ref is not None:
            # 绑了出镜人：场景文本里若写着"无人物"，必须改写 —— 否则提示词自相矛盾（一边说没人、一边要求人出镜）
            action = person_aware_action(action)
        purpose = SHOT_TYPE_LABELS.get(str(scene.purpose or ""), str(scene.purpose or "分镜"))
        camera = str(scene.camera_move or "").strip()
        dialogue = strip_pause_marks(str(scene.script_excerpt or ""))
        line = f"[{start:.0f}-{end:.0f} 秒] 镜头{index}（{purpose}，画面以{reference}为基准）：{action}。"
        if camera:
            line += f"运镜：{camera}。"
        if dialogue:
            line += f"台词（逐字说出，不要念出引号）：{dialogue}。"
        else:
            line += "（无台词，只保留环境音与动作声）"
        lines.append(line)
    lines.append(f"所有镜头保持人物、商品与{every}一致；商品外观、包装文字与 LOGO 不得变形；")
    if character_ref is not None:
        # 出镜人母版作为**身份锚点**（借 ClipForge 的 characterSheet 思路）。
        # 编号必须与 media 数组顺序一致（阿里官方：顺序与 media 一致、图与视频分别计数）——
        # 我们的 media 顺序是 [各镜关键帧..., 出镜人母版]，所以母版编号 = 本组镜数 + 1。
        #
        # 2026-10-16 更正：原来写的是条件句「画面中出现人物时，须与该图保持同一个人」→ 等于允许它**不出镜**，
        # 实测整片出来只有商品在展示台上。改成硬要求 + 明确"人与商品互动"。
        lines.append(
            f"图 {character_ref} 是本次的出镜人（脸型、发型、肤色、服装配色以此为准）。"
            "出镜人**必须出镜**，并与商品发生真实互动：至少一个镜头里手持或试用商品，"
            "手部与商品有真实接触、商品不被手遮挡；全片出现的人物都必须是这同一个人，不得换人。"
        )
    if realism:
        # 借 ClipForge 的"实拍质感"块：让**模型生成时就带**日常实拍观感（而不是只靠后处理补救）。
        # 走强风格化模板时可传 realism=False 关掉，避免两种观感打架。
        lines.append("画面为手机日常实拍的质感：轻微手持晃动、自然光、不过度修饰的影调；商品细节保持清晰。")
    lines.append("画面稳定，不新增文字、字幕、水印或多余主体；相邻镜头自然衔接，不出现跳变。")
    return "".join(lines)


def keyframe_refs_for_call(call: OneShotCall, keyframes_by_scene: dict[str, bytes]) -> list[bytes]:
    """取该次调用用到的关键帧（按分镜顺序），并截断到 r2v 允许的张数。"""
    refs = [keyframes_by_scene[scene_id] for scene_id in call.scene_ids if scene_id in keyframes_by_scene]
    return refs[: MAX_MEDIA_ITEMS]