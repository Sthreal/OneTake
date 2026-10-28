"""流水线阶段目录（S8+S9+S10 提交 3）。

**纯数据 + 纯函数、零 I/O**：推进器（`orchestrator.py`）只读这张表来决定
"下一步做什么 / 失败怎么办 / 要不要停下来等人"，本模块自己不知道也不关心怎么执行。

为什么要有这张表：S8（闸口自动放行）、S9（一键编排 + 断点续跑）、S10（失败分类与恢复）
**三者共用同一份阶段定义** —— 分开写就是三套并行实现（§1.4 明令禁止的形态）。

阶段划到 9 段，与既有 pipeline 状态机一一对应（状态常量直接引 `pipeline.domain`，不写字面量）：

```
识别 → 主图 → 文案 → 配音字幕 ──[人工闸口① 内容规划]── 语义质检 → 关键帧
   ──[人工闸口② 视频方案 + 费用审批]── 分段生成 → 合成出片 ──[人工闸口③ 交付门]
```

**失败语义**（`failure_semantics`）：
- `fatal`：失败就停，产不出东西没法继续（识别/主图/文案/配音字幕/内容规划/关键帧/分段/合成）
- `best_effort`：失败**跳过**不阻断（当前只有语义质检 —— 真正的阻断在交付门③，不在这一层）

**`is_paid` 的口径（容易误读，写清楚）**：它表示"该阶段**存在**付费路径"——一个**静态事实**，
不随配置变化。今天 **9 段全部为 True**，因为每一段都有真实提供方的付费实现
（识别/主图/文案/配音字幕/内容规划/质检/关键帧/分段/合成，合成在 `shotstack` 下也计费）。

> **所以它不能拿来当"能不能跑"的判据。**「自动链该不该继续」由**金额**决定：
> `estimate` 在当前配置下算出 0 元（`MOCK_PROVIDERS=true`，或该能力的 provider 是 mock）就照跑；
> 算出 > 0 且超过 `AUTO_RUN_BUDGET_CNY` 就停在闸口②等人审批。
> 这个静态标志只服务于两件事：① 文档与审阅时一眼看出"没有哪一段是天然免费的"；
> ② 阶段目录自检（付费阶段必须挂人工闸口②之后，不许出现在闸口之前）。
"""
from __future__ import annotations

from dataclasses import dataclass

from onetake_api.modules.pipeline.domain import (
    STATUS_AUDIO_SUBTITLE_CONFIRMED,
    STATUS_COMPLETED,
    STATUS_CONTENT_PLAN_CONFIRMED,
    STATUS_CONTENT_PLAN_READY,
    STATUS_CONTENT_QA_FAILED,
    STATUS_CONTENT_QA_PASSED,
    STATUS_IMAGE_EDITING,
    STATUS_MAIN_IMAGE_CONFIRMED,
    STATUS_MAIN_IMAGE_QUEUED,
    STATUS_MAIN_IMAGE_READY,
    STATUS_MATTING,
    STATUS_RECOGNITION_CONFIRMED,
    STATUS_RECOGNITION_READY,
    STATUS_RECOGNIZING,
    STATUS_RENDERING,
    STATUS_SCRIPT_CONFIRMED,
    STATUS_SCRIPT_GENERATING,
    STATUS_SCRIPT_QUEUED,
    STATUS_SCRIPT_READY,
    STATUS_SUBTITLE_GENERATING,
    STATUS_SUBTITLE_QUEUED,
    STATUS_SUBTITLE_READY,
    STATUS_VIDEO_GENERATING,
    STATUS_VIDEO_PLAN_READY,
    STATUS_VIDEO_READY,
    STATUS_VOICE_GENERATING,
    STATUS_VOICE_QUEUED,
    STATUS_VOICE_READY,
)

FAILURE_SEMANTICS = frozenset({"best_effort", "fatal"})
# 与 `platform.errors.ERROR_CLASSES` / `RECOVER_ACTIONS` 是同一份契约的延伸
STAGE_RECOVER_ACTIONS = frozenset({"retry", "retry_with_fallback", "skip_stage", "require_human", "abort"})
HUMAN_GATE_NAMES = ("content_plan", "plan_and_cost", "delivery")


class UnknownStageError(ValueError):
    """阶段名不在目录里 —— **明确报错，不静默回落**（静默回落会让断点续跑跑错阶段）。"""


@dataclass(frozen=True)
class StageSpec:
    """一个阶段。三个 `*_status` 都是**可空**的：有些阶段没有独立的状态标记
    （关键帧 / 分段靠各自仓储判定，不写 pipeline 状态）。"""

    name: str
    order: int
    enter_status: str | None      # 开始该阶段时写入的状态
    ready_status: str | None      # 该阶段产出就绪时写入的状态
    confirm_status: str | None    # 确认（人工或自动）时写入的状态
    failure_semantics: str        # best_effort | fatal
    is_paid: bool                 # 可能产生供应商费用（静态口径，宁严不宽）
    default_recover_action: str   # 失败时的默认动作（推进器可被 error_class 覆盖）
    human_gate: bool = False      # True = 必须人工确认，自动链**不得**代按
    extra_statuses: tuple[str, ...] = ()   # 同一阶段内的中间状态（只用于展示/校验）
    note: str = ""


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        name="recognition", order=1,
        enter_status=STATUS_RECOGNIZING, ready_status=STATUS_RECOGNITION_READY,
        confirm_status=STATUS_RECOGNITION_CONFIRMED,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        note="识别不出主体就无从继续；档 B 下确认可由系统代按",
    ),
    StageSpec(
        name="main_image", order=2,
        enter_status=STATUS_MAIN_IMAGE_QUEUED, ready_status=STATUS_MAIN_IMAGE_READY,
        confirm_status=STATUS_MAIN_IMAGE_CONFIRMED,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        extra_statuses=(STATUS_IMAGE_EDITING, STATUS_MATTING),
        note="修图 → 去背两步同属一个阶段",
    ),
    StageSpec(
        name="script", order=3,
        enter_status=STATUS_SCRIPT_QUEUED, ready_status=STATUS_SCRIPT_READY,
        confirm_status=STATUS_SCRIPT_CONFIRMED,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        extra_statuses=(STATUS_SCRIPT_GENERATING,),
    ),
    StageSpec(
        name="voice_subtitle", order=4,
        enter_status=STATUS_VOICE_QUEUED, ready_status=STATUS_VOICE_READY,
        confirm_status=STATUS_AUDIO_SUBTITLE_CONFIRMED,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        extra_statuses=(
            STATUS_VOICE_GENERATING, STATUS_SUBTITLE_QUEUED,
            STATUS_SUBTITLE_GENERATING, STATUS_SUBTITLE_READY,
        ),
        note="配音与字幕同属一段（字幕依赖配音时长）",
    ),
    StageSpec(
        name="content_plan", order=5,
        enter_status=STATUS_CONTENT_PLAN_READY, ready_status=None,
        confirm_status=STATUS_CONTENT_PLAN_CONFIRMED,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        human_gate=True,
        note="**人工闸口①**：出分镜方案是自动的，采用哪一套必须人拍板",
    ),
    StageSpec(
        name="content_qa", order=6,
        enter_status=None, ready_status=STATUS_CONTENT_QA_PASSED,
        confirm_status=None,
        failure_semantics="best_effort", is_paid=True, default_recover_action="skip_stage",
        extra_statuses=(STATUS_CONTENT_QA_FAILED,),
        note="质检不过**不阻断**自动链；真正的阻断在交付门③",
    ),
    StageSpec(
        name="keyframes", order=7,
        enter_status=None, ready_status=None, confirm_status=None,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        note="**无 pipeline 状态**：由关键帧仓储判定「是否已有已采用的关键帧」（M4-03 起这是硬前置）",
    ),
    StageSpec(
        name="segments", order=8,
        enter_status=None, ready_status=None, confirm_status=None,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        note="**无 pipeline 状态**：由分段仓储判定；失败停在待人工（不静默产出无商品成片）",
    ),
    StageSpec(
        name="render_compose", order=9,
        enter_status=STATUS_VIDEO_PLAN_READY, ready_status=STATUS_COMPLETED,
        confirm_status=None,
        failure_semantics="fatal", is_paid=True, default_recover_action="require_human",
        extra_statuses=(STATUS_VIDEO_GENERATING, STATUS_VIDEO_READY, STATUS_RENDERING),
        note="唯一的 fatal 收口：出不了片就没有交付物",
    ),
)

STAGE_BY_NAME: dict[str, StageSpec] = {spec.name: spec for spec in STAGES}
STAGE_NAMES: tuple[str, ...] = tuple(spec.name for spec in STAGES)


@dataclass(frozen=True)
class HumanGateSpec:
    """人工闸口。三个闸口**都不是**普通阶段：它们的"确认"有不同的落点。"""

    name: str
    after_stage: str
    label: str
    confirmed_by: str  # 用什么东西表示"这道闸口过了"


HUMAN_GATES: tuple[HumanGateSpec, ...] = (
    HumanGateSpec(
        name="content_plan", after_stage="voice_subtitle", label="内容规划",
        confirmed_by="pipeline.status == content_plan_confirmed",
    ),
    HumanGateSpec(
        name="plan_and_cost", after_stage="keyframes", label="视频方案 + 费用审批",
        confirmed_by="pipeline.cost_approvals 里有匹配 payload_hash 的记录（后端强制）",
    ),
    HumanGateSpec(
        name="delivery", after_stage="render_compose", label="交付门",
        confirmed_by="gate_acks（既有）",
    ),
)


def get_stage(name: str) -> StageSpec:
    spec = STAGE_BY_NAME.get(name)
    if spec is None:
        raise UnknownStageError(f"未知阶段：{name}（可用：{', '.join(STAGE_NAMES)}）")
    return spec


def stages_from(name: str) -> tuple[StageSpec, ...]:
    """断点续跑：从 `name` 起（含）的剩余阶段。**未知名字明确报错**，不静默从头跑。"""
    start = get_stage(name).order
    return tuple(spec for spec in STAGES if spec.order >= start)


def paid_stages() -> tuple[StageSpec, ...]:
    return tuple(spec for spec in STAGES if spec.is_paid)


def human_gate_after(stage_name: str) -> HumanGateSpec | None:
    """某个阶段之后是不是紧跟着人工闸口（推进器据此决定"能不能继续往下自动跑"）。"""
    get_stage(stage_name)
    return next((gate for gate in HUMAN_GATES if gate.after_stage == stage_name), None)


def validate_catalog() -> None:
    """自检目录取值域。**导入时不执行**（避免 import 副作用），由测试与推进器显式调用。"""
    if len(STAGE_NAMES) != len(set(STAGE_NAMES)):
        raise AssertionError("阶段名重复")
    if [spec.order for spec in STAGES] != list(range(1, len(STAGES) + 1)):
        raise AssertionError("阶段 order 必须是 1..N 连续")
    for spec in STAGES:
        if spec.failure_semantics not in FAILURE_SEMANTICS:
            raise AssertionError(f"{spec.name} 的 failure_semantics 非法：{spec.failure_semantics}")
        if spec.default_recover_action not in STAGE_RECOVER_ACTIONS:
            raise AssertionError(f"{spec.name} 的 default_recover_action 非法：{spec.default_recover_action}")
        if spec.failure_semantics == "best_effort" and spec.default_recover_action != "skip_stage":
            raise AssertionError(f"{spec.name} 是 best_effort，恢复动作应当是 skip_stage")
        if spec.human_gate and spec.default_recover_action != "require_human":
            raise AssertionError(f"{spec.name} 是人工闸口，恢复动作必须 require_human")
    gate_names = tuple(gate.name for gate in HUMAN_GATES)
    if gate_names != HUMAN_GATE_NAMES:
        raise AssertionError(f"人工闸口必须是 {HUMAN_GATE_NAMES}，实际 {gate_names}")
    for gate in HUMAN_GATES:
        if gate.after_stage not in STAGE_BY_NAME:
            raise AssertionError(f"闸口 {gate.name} 挂在不存在的阶段上：{gate.after_stage}")