"""关键帧应用服务（Phase 1）：生成候选、落库落存储、采纳候选。

分工：
- 生成与质检在 `integrations/product_scene/keyframe_integrated.py`（纯逻辑、可单测）
- 本模块负责取事实（已确认主图 / 已确认分镜）、落对象存储、写库、发事件

安全约束：MOCK_PROVIDERS=true 时不产生任何付费调用（生成器内部走 mock 渲染）。
"""
from __future__ import annotations

import json

import random

from sqlalchemy.orm import Session

from onetake_api.config import get_settings
from onetake_api.integrations.object_storage.dependencies import get_object_storage
from onetake_api.integrations.object_storage.public import ObjectStoragePublicService
from onetake_api.integrations.product_scene.keyframe_integrated import (
    MODE_GRID,
    MODE_INTEGRATED,
    KeyframeGenerator,
)
from onetake_api.modules.content_plan.domain import STATUS_CONFIRMED as CONTENT_PLAN_CONFIRMED
from onetake_api.modules.content_plan.public import ContentPlanPublicService
from onetake_api.modules.main_image.public import MainImagePublicService
from onetake_api.modules.outbox.public import OutboxPublicService
from onetake_api.modules.project.public import ProjectPublicService
from onetake_api.modules.video_plan.keyframe_domain import (
    KEYFRAME_ACCEPTED,
    KEYFRAME_FAILED,
    KEYFRAME_READY,
    VideoKeyframeCandidate,
)
from onetake_api.modules.video_plan.keyframe_repository import VideoKeyframeCandidateRepository
from onetake_api.platform.clock import SystemClock
from onetake_api.platform.errors import DomainError
from onetake_api.platform.ids import new_id


class KeyframeNotFoundError(DomainError):
    code = "KEYFRAME_NOT_FOUND"
    http_status = 404


class KeyframeConflictError(DomainError):
    code = "KEYFRAME_CONFLICT"
    http_status = 409
    retryable = True


class KeyframeValidationError(DomainError):
    code = "KEYFRAME_VALIDATION_ERROR"
    http_status = 422


def generate_seed() -> int:
    return random.randint(1, 2_000_000_000)


class VideoKeyframeApplicationService:
    def __init__(
        self,
        *,
        storage: ObjectStoragePublicService | None = None,
        generator: KeyframeGenerator | None = None,
    ) -> None:
        self._repository = VideoKeyframeCandidateRepository()
        self._projects = ProjectPublicService()
        self._plans = ContentPlanPublicService()
        self._main_images = MainImagePublicService()
        self._outbox = OutboxPublicService()
        self._clock = SystemClock()
        self._storage = storage
        self._generator = generator

    @property
    def storage(self) -> ObjectStoragePublicService:
        return self._storage or get_object_storage()

    @property
    def generator(self) -> KeyframeGenerator:
        if self._generator is None:
            self._generator = KeyframeGenerator()
        return self._generator

    def list_candidates(self, session: Session, *, project_id: str) -> list[VideoKeyframeCandidate]:
        self._projects.get_project(session, project_id=project_id)
        return self._repository.list_for_project(session, project_id)

    def _single_frame_generate(self, *, scene, product_png, seed: int, character_png: bytes | None):
        """单帧档调用（有出镜人才多传那个 kwarg，保持老调用方兼容）。"""
        kwargs = dict(scene=scene, product_png=product_png, mode=MODE_INTEGRATED, seed=seed, n=1)
        if character_png:
            kwargs["character_png"] = character_png
        return self.generator.generate(**kwargs)

    def _character_reference(self, session: Session, project_id: str) -> bytes | None:
        """项目绑定的出镜人母版（人物库引用）。没选人就返回 None —— 不猜、不造。

        读不到（图丢了 / 权限）也当"没有"：宁可不加人，也不能因为读母版失败让关键帧整体生成不了。
        """
        try:
            from onetake_api.modules.character.public import CharacterPublicService

            project = self._projects.get_project(session, project_id=project_id)
            character_id = getattr(project, "character_id", None)
            if not character_id:
                return None
            character = CharacterPublicService().get_character(session, character_id=character_id)
            return b"".join(self.storage.read_object(object_key=character.sheet_object_key)) or None
        except Exception:  # noqa: BLE001
            return None

    def _generate_grid_candidates(self, *, content_plan, variant, scene, product_png, project_id, seed, character_png=None):
        """批次 3：九宫格路径 —— **一张网格出 4 格，同一网格在计划内复用**。

        - 复用是**刻意**的：4 个格必须来自同一次生成，才有"同一空间/同一光线"的一致性；
        - 缓存键带内容方案 id：换方案/换分镜会重新生成，不会串到别的格子上；
        - 逐格质检与"不过线只重生成那一格"在 `candidates_from_grid` 里（批次 0 的实测结论）。
        """
        from onetake_api.integrations.product_scene.keyframe_integrated import GRID_COLS, GRID_ROWS

        grid_key = f"projects/{project_id}/keyframes/grid/{content_plan.id}/grid-{GRID_ROWS}x{GRID_COLS}.png"
        blocked_key = f"{grid_key}.unusable"
        # ① 这片网格已经被判过"整体不可用" → 直接走单帧档（不再逐格补救，也不再调模型）
        if self._object_exists(blocked_key):
            return self._single_frame_generate(scene=scene, product_png=product_png, seed=seed,
                                              character_png=character_png)
        grid_image: bytes | None = None
        try:
            stored = b"".join(self.storage.read_object(object_key=grid_key))
            grid_image = stored or None
        except Exception:  # noqa: BLE001 - 存储里没有这张网格（首次生成）是正常情况
            grid_image = None
        if grid_image is None:
            grid_image = self.generator.generate_grid_image(
                scenes=variant.scenes, product_png=product_png, seed=seed, character_png=character_png,
            )
            # ② **片级判断**（比逐格回退省一次调用）：整图先逐格套网格档门槛，**坏格过半** → 整片改用单帧档。
            #    为什么不是"逐格补救"：瓶子那档（2026-10-15 用户肉眼复核：四格 0.488~0.498、右上格文字变乱码、
            #    四格不是同一瓶）逐格回退会变成"1 次网格 + 4 次单帧"，比直接走单帧档还贵，而且救回来的格子
            #    本来就不该用。verdict.passed 与 candidates_from_grid 的门槛**同源**（_grid_cell_ok）。
            verdicts = self.generator.grid_cell_verdicts(grid_image=grid_image, product_png=product_png)
            failures = [item for item in verdicts if not item.passed]
            if len(failures) * 2 >= len(verdicts):
                self.storage.put_bytes(
                    object_key=blocked_key,
                    content=json.dumps({
                        "reason": "九宫格该片整体不可用（坏格过半）",
                        "matches": [item.product_match for item in verdicts],
                        "failed": [item.issues for item in failures],
                    }, ensure_ascii=False, indent=1).encode("utf-8"),
                    mime_type="application/json",
                )
                return self._single_frame_generate(scene=scene, product_png=product_png, seed=seed,
                                                  character_png=character_png)
            # 只有"可用"的网格才落盘：坏网格落盘会被后续分镜当成可复用网格读回来（那样就又要逐格回退）
            self.storage.put_bytes(object_key=grid_key, content=grid_image, mime_type="image/png")
        return self.generator.candidates_from_grid(
            grid_image=grid_image, scene=scene, scenes=variant.scenes, product_png=product_png, seed=seed,
        )

    def _object_exists(self, object_key: str) -> bool:
        """对象是否存在（存储层没有 exists API，用读一次来判；读失败一律当"不存在"）。"""
        try:
            return bool(b"".join(self.storage.read_object(object_key=object_key)))
        except Exception:  # noqa: BLE001
            return False

    def generate_candidate(
        self,
        session: Session,
        *,
        project_id: str,
        scene_id: str,
        mode: str | None = None,
        n: int | None = None,
        seed: int | None = None,
    ) -> list[VideoKeyframeCandidate]:
        settings = get_settings()
        self._projects.get_project(session, project_id=project_id)
        content_plan = self._plans.latest(session, project_id)
        if content_plan is None or content_plan.status != CONTENT_PLAN_CONFIRMED:
            raise KeyframeConflictError("请先确认视频分镜")
        variant = content_plan.variants[content_plan.selected_variant_index]
        scene = next((item for item in variant.scenes if item.scene_id == scene_id), None)
        if scene is None:
            raise KeyframeNotFoundError("分镜不存在")

        main_image = self._main_images.latest(session, project_id)
        if main_image is None or not main_image.version.transparent_object_key:
            raise KeyframeConflictError("已确认主图不可用，无法生成关键帧")
        product_png = b"".join(self.storage.read_object(object_key=main_image.version.transparent_object_key))
        # 出镜人母版（人物库引用）：**有就一定要给模型**，否则首帧没有人、整条片子只能是"商品在台上"。
        character_png = self._character_reference(session, project_id)

        previous = self._previous_accepted(session, project_id=project_id, order_index=scene.order - 1)
        scene_reference = None
        if previous is not None and previous.image_object_key:
            scene_reference = b"".join(self.storage.read_object(object_key=previous.image_object_key))

        resolved_seed = seed if seed is not None else generate_seed()
        if (mode or settings.keyframe_mode) == MODE_GRID:
            generated = self._generate_grid_candidates(
                content_plan=content_plan, variant=variant, scene=scene, product_png=product_png,
                project_id=project_id, seed=resolved_seed, character_png=character_png,
            )
        else:
            kwargs = dict(scene=scene, product_png=product_png, mode=mode, n=n, seed=resolved_seed,
                          scene_reference=scene_reference)
            if character_png:
                # 只在**有出镜人**时才多传：注入的假生成器/老调用方签名不受影响
                kwargs["character_png"] = character_png
            generated = self.generator.generate(**kwargs)
        self._repository.supersede_pending(session, project_id=project_id, scene_id=scene_id)
        now = self._clock.now()
        version = settings.keyframe_storage_version
        created: list[VideoKeyframeCandidate] = []
        for index, item in enumerate(generated):
            candidate_id = new_id("kfc")
            object_key = f"projects/{project_id}/keyframes/{version}/{scene_id}/{candidate_id}.png"
            self.storage.put_bytes(object_key=object_key, content=item.image_bytes, mime_type="image/png")
            candidate = VideoKeyframeCandidate(
                id=candidate_id, project_id=project_id, content_plan_id=content_plan.id, scene_id=scene_id,
                order_index=scene.order, mode=item.mode, status=KEYFRAME_READY if item.qa.passed else KEYFRAME_FAILED,
                provider=item.provider, created_at=now, seed=item.seed,
                image_object_key=object_key, width=item.width, height=item.height,
                product_match=item.qa.product_match, text_intact=item.qa.text_intact,
                issues=list(item.issues), fallback=item.fallback,
                error_code=None if item.qa.passed else "KEYFRAME_QA_FAILED",
            )
            self._repository.add(session, candidate)
            created.append(candidate)
        self._outbox.enqueue(
            session, event_name="KeyframeCandidatesGenerated", aggregate_type="video_plan",
            aggregate_id=content_plan.id, occurred_at=now,
            payload={"project_id": project_id, "scene_id": scene_id, "count": len(created), "seed": resolved_seed},
        )
        session.commit()
        return self._repository.list_for_project(session, project_id)

    def accept_candidate(self, session: Session, *, project_id: str, keyframe_id: str) -> list[VideoKeyframeCandidate]:
        self._projects.get_project(session, project_id=project_id)
        candidate = self._repository.get(session, keyframe_id)
        if candidate is None or candidate.project_id != project_id:
            raise KeyframeNotFoundError("关键帧候选不存在")
        if candidate.status == KEYFRAME_ACCEPTED:
            return self._repository.list_for_project(session, project_id)
        if candidate.status != KEYFRAME_READY:
            raise KeyframeValidationError("该候选未通过质检，不能采用")
        self._repository.reject_all_for_scene(
            session, project_id=project_id, scene_id=candidate.scene_id, except_id=candidate.id
        )
        self._repository.update_status(session, candidate.id, KEYFRAME_ACCEPTED)
        session.commit()
        return self._repository.list_for_project(session, project_id)

    def _previous_accepted(
        self, session: Session, *, project_id: str, order_index: int
    ) -> VideoKeyframeCandidate | None:
        if order_index < 1:
            return None
        for candidate in self._repository.list_for_project(session, project_id):
            if candidate.order_index == order_index and candidate.status == KEYFRAME_ACCEPTED:
                return candidate
        return None