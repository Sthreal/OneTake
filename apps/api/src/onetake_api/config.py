from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://onetake:onetake_dev_password@localhost:5432/onetake"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9000"
    minio_public_endpoint: str = "localhost:9000"
    minio_root_user: str = "onetake"
    minio_root_password: str = "onetake_dev_password"
    minio_bucket: str = "onetake-media"
    minio_secure: bool = False
    minio_region: str = "us-east-1"
    mock_providers: bool = True
    mock_recognition_mode: str = "success"
    recognition_provider: Literal["mock", "real"] = "mock"
    image_edit_provider: Literal["mock", "real"] = "mock"
    qwen_image_edit_price_per_call: float | str | None = None
    matting_provider: Literal["mock", "real", "aliyun"] = "mock"
    script_provider: Literal["mock", "real"] = "mock"
    voice_provider: Literal["mock", "real"] = "mock"
    composition_provider: Literal["mock", "shotstack", "local"] = "mock"
    creative_planner_provider: Literal["rules", "qwen"] = "rules"
    wan_i2v_provider: Literal["mock", "real"] = "mock"
    # 数字人（avatar）档位已于 2026-10-14 下线（档案 M4-04）：本开关**已无消费者**
    # （provider 能力清单与估算分支都已摘除）。保留字段只为兼容既有 .env / compose
    # （删它要同步改 docker-compose 的 api+worker 两处）；移除条件：部署侧确认不再设置
    # AVATAR_VIDEO_PROVIDER 后，由清理类切片（S2/S4 一类）删除。
    avatar_video_provider: Literal["mock", "real"] = "mock"
    content_qa_provider: Literal["rules", "qwen"] = "rules"
    recognition_model: str = "qwen3-vl-plus"
    recognition_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    dashscope_api_key: str = ""
    image_edit_model: str = "qwen-image-edit-plus"
    image_edit_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    script_model: str = "qwen3-vl-plus"
    script_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    voice_model: str = "cosyvoice-v2"
    photoroom_api_key: str = ""
    photoroom_endpoint: str = "https://sdk.photoroom.com/v1/segment"
    shotstack_api_key: str = ""
    shotstack_env: Literal["stage", "v1"] = "stage"
    shotstack_api_base: str = "https://api.shotstack.io"
    shotstack_poll_interval_seconds: float = 2.0
    shotstack_poll_timeout_seconds: int = 600
    shotstack_max_retries: int = 3
    shotstack_retry_backoff_seconds: float = 2.0
    shotstack_render_price: float | str | None = None
    video_estimate_confirmation_threshold: float = 5.0
    video_estimate_minutes_per_clip: float = 1.0
    video_estimate_overhead_minutes: float = 0.5
    video_continuity_enabled: bool = True
    video_tail_offset_frames: int = 2
    video_max_candidates_per_segment: int = 8
    creative_planner_model: str = "qwen-plus"
    creative_planner_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    content_qa_model: str = "qwen3-vl-plus"
    content_qa_endpoint: str = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    content_qa_frame_count: int = 5
    wan_i2v_model: str = ""
    wan_i2v_resolution: Literal["720P", "1080P"] = "720P"
    wan_i2v_with_audio: bool = False
    wan_i2v_max_seconds: int = 5
    wan_i2v_price_per_second: float = 0.15
    wan_s2v_model: str = ""
    wan_s2v_resolution: Literal["480P", "720P"] = "720P"
    wan_s2v_max_seconds: int = 30
    wan_s2v_price_per_second: float | str | None = None
    wan_s2v_avatar_path: str = ""
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    alibaba_cloud_region_id: str = "cn-shanghai"
    aliyun_imageseg_endpoint: str = "imageseg.cn-shanghai.aliyuncs.com"
    # ---- 商品入画链路（docs/商品入画链路总体方案.md）----
    # 默认值一律保持"旧行为"，对应 Phase 验收通过后再翻转默认值；
    # 每个开关都能单独回滚，不需要回滚代码。
    generation_path_default: Literal["segmented", "one_shot"] = "segmented"
    # 批次 3：`grid` = 一张九宫格出 4 格（默认仍是 integrated，零默认变更、可随时回退）
    keyframe_mode: Literal["integrated", "erase_background", "grid"] = "integrated"
    # 九宫格整图尺寸：批次 0 实测 2x2 @1440*2560 → 单格 692x1228 → 放大 1.56x 到 1080x1920；
    # 更大的 2160*3840 被服务端面积上限（4,194,304 px）拒绝，不要改成那档
    keyframe_grid_image_size: str = "1440*2560"
    # 九宫格的"相似度**警示线**"（⚠️ 不是硬门槛！只对网格档生效；单帧档仍用 keyframe_qa 的 0.55）。
    # 标定依据（2026-10-15，5 张不同商品图 × 各跑"九宫格 + 单帧"共 10 次调用，记录见
    # docs/九宫格格子阈值标定记录.md）：
    #   - 单帧 match：0.741~0.911（0.55 阈值对**单帧**完全够用）
    #   - 格子 match：0.466~0.794 —— 透明/白底/标签多的商品（瓶子）天然偏低
    #   - 格/单帧 比值：0.606~0.896 —— **既不稳定，绝对值也没法定**
    # 结论（2026-10-15 由用户肉眼复核定案）：瓶子那档格子 0.488~0.498 时人眼看到的是
    # 「右上格标签文字变成诡异符号 + 四格不是同一瓶」，而同商品单帧（0.784）清晰完整 → **低分确实对应坏格**。
    # 所以 `product_match` 对网格档**保持硬门槛**，本值就是网格档的下限（单帧档仍用 keyframe_qa 的 0.55）。
    keyframe_grid_match_floor: float = 0.52
    keyframe_candidates: int = 2
    keyframe_pixel_lock_fallback: bool = True
    keyframe_storage_version: str = "v3"
    keyframe_qa_provider: Literal["rules", "qwen"] = "rules"
    keyframe_qa_model: str = "qwen3-vl-plus"
    keyframe_image_size: str = "1080*1920"
    video_motion_prompt_enabled: bool = True
    video_kf2v_enabled: bool = True
    # 整片路径是否保留模型原声（口型台词；开启时不再叠 TTS，避免双声）。默认关：语音只来自 TTS
    video_keep_model_audio: bool = False
    wan_kf2v_model: str = "wan2.2-kf2v-flash"
    wan_kf2v_price_per_second: float | str | None = None
    wan_r2v_model: str = ""
    wan_r2v_resolution: Literal["720P", "1080P"] = "720P"
    wan_r2v_max_seconds: int = 15
    wan_r2v_price_per_second: float | str | None = None
    # ---- 超时预算（2026-10-15 修：原 video 作业硬编码 600 秒 → one_shot 必超）----
    # video 作业（rq）超时：one_shot 会把**全部** r2v 调用塞进同一个作业，而实测**单次** 10s 片段
    # 就要 438 秒（2026-10-14 steps-d.json）→ 18s 脚本切 2 次调用，600 秒必然被 rq 掐掉
    # （用户点了"出片"却在 10 分钟处失败，且钱已花）。默认 2400 = 2×单次轮询上限(900) + 拼接/合成余量。
    # 权衡：作业超时越长，卡住的作业占用 worker 越久（本仓只起 1 个 worker，见 docker-compose）。
    video_job_timeout_seconds: int = 2400
    # r2v **单次调用**的轮询上限（适配器内部）：必须 ≤ 作业超时 / 调用次数，否则单次就超时（钱白花）。
    wan_r2v_poll_timeout_seconds: int = 900
    qwen_image_price_per_call: float | str | None = None
    native_feel_enabled: bool = True
    native_feel_strength: Literal["subtle", "medium", "strong"] = "subtle"
    gate_mode: Literal["enforce", "warn_only"] = "enforce"
    aigc_label_enabled: bool = True
    aigc_label_text: str = "AI生成"
    aigc_label_position: Literal["top_right", "top_left", "bottom_right", "bottom_left"] = "top_right"
    aigc_label_size_ratio: float = 0.028
    aigc_label_opacity: float = 0.75
    aigc_label_safe_margin_ratio: float = 0.04
    aigc_label_avoid_subtitle: bool = True
    aigc_label_source: Literal["local", "model"] = "local"

    # ---- 字幕样式（批次 1a）----
    # 四档：standard（默认）/ bold / minimal / karaoke。字号口径（帧宽比例 + 标定）见
    # integrations/media/caption_styles.py；取值必须与 caption_styles.CAPTION_STYLE_KEYS 一致
    # （有单测钉住这条一致性，改一处漏一处会红）。
    caption_style: Literal["standard", "bold", "minimal", "karaoke"] = "standard"

    # ---- BGM（批次 4b：0 成本路径）----
    # 默认**关闭** → 不叠 BGM 时成片逐字节不变。开启后旁白会把音乐压下去（sidechain 闪避），
    # 且**只有存在旁白轨时才叠**（沿用"用户关闭语音 → 成片无音轨"的既有契约）。
    # 来源免 Key 优先：BGM_TRACK_PATH 指定的本地文件 → assets/bgm/ 内置库 → 都没有则如实跳过。
    bgm_enabled: bool = False
    bgm_gain_db: float = -20.0
    bgm_track_path: str = ""
    # 闪避参数：阈值越低越早开始压、比率越高压得越狠（默认值按"人声清晰优先"取）
    bgm_duck_threshold: float = 0.03
    bgm_duck_ratio: float = 12.0

    # ---- 免 Key 素材（批次 4a：0 成本路径）----
    # 默认**关闭** → 不启用时逐段生成路径与改造前完全一致（一个调用都不少、一个字节都不变）。
    # 开启后：`product_mode=absent` 的空镜（当前只有 hook 段）优先用免 Key 实拍素材填充，
    # 检索/下载/归一化任一环节失败都**回退到原 i2v 路径**（0 成本增强绝不能让成片失败）。
    stock_enabled: bool = False
    stock_search_limit: int = 5
    stock_max_asset_mb: int = 40

    # ---- 多平台导出（批次 6）----
    # 小红书 3:4 的处理策略：默认 `blur_pad`（模糊背景留白，**不丢画面**）；可切 `center_crop`（居中裁切）
    export_xiaohongshu_strategy: Literal["blur_pad", "center_crop"] = "blur_pad"

    # ---- 逐镜 VLM 评分（批次 5）----
    # 默认**关闭**：这是付费调用（Qwen-VL 按次）。打开后逐镜打分、写侧车报告、交付门给 warn（不阻断）。
    # 费用必须能被预估到（`QWEN_VL_PRICE_PER_CALL`，缺单价一律进 missing_price_config，不按 0 算）。
    segment_quality_enabled: bool = False
    qwen_vl_price_per_call: float | str | None = None

    # ---- 文案审稿闸（切片 C，花钱前）----
    # 默认开启，并且 GATE=enforce：付费视频前必须有人对当前稿 apply 改写或 ack 保留原稿。
    # enforce / warn 不在生成任务里自动改写，避免审稿失败被静默当成已经过闸。
    # off：不拦截（ENABLED=true 时仍可走旧的「生成时增强审稿、失败降级」）。
    # warn：不拦截，未过闸只记日志。这道闸不替代 cost_approvals。
    script_review_enabled: bool = True
    script_review_gate: Literal["off", "warn", "enforce"] = "enforce"
    # ---- 自动链成本护栏（S8+S9+S10）----
    # 自动链**默认关闭**（要一键跑中间段必须显式打开）；预算默认 0 = 只跑免费 / mock 阶段，
    # 一旦这一步在当前配置下要花钱，推进器就停下来等人审批（绝不自动「加预算」）。
    auto_run_enabled: bool = False
    auto_run_budget_cny: float = 0.0
    # 自动链用的配音音色。默认与**活前端配音面板的默认音色一致**（`longxiaochun_v2`）：
    # 那份清单（VoicePanel.tsx 的 VOICES）本来就是"当前账号/模型下能用的音色"，两边对齐才不会
    # 出现"UI 能用、自动链 418"的错位（实测踩过：默认写 v1 的 `longxiaochun` + `cosyvoice-v2` → 418 InvalidParameter）。
    # 换音色只要改这里或设 `AUTO_RUN_VOICE_ID`；mock 适配器忽略该值，所以不影响免费链路。
    auto_run_voice_id: str = "longxiaochun_v2"
    # ---- 廉价预览片（S12）----
    # 紧急回滚开关：默认 True（预览全程零付费，故不需要默认关闭）。
    # 移除条件：确认预览永不引起付费调用后，由清理切片删除本开关。
    preview_enabled: bool = True
    project_ttl_hours: int = 24
    media_cleanup_interval_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
