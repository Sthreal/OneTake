from dataclasses import dataclass
from datetime import datetime

STATUS_ASSETS_READY = "assets_ready"
STATUS_RECOGNIZING = "recognizing"
STATUS_RECOGNITION_READY = "recognition_ready"
STATUS_RECOGNITION_CONFIRMED = "recognition_confirmed"
STATUS_MAIN_IMAGE_QUEUED = "main_image_queued"
STATUS_IMAGE_EDITING = "image_editing"
STATUS_MATTING = "matting"
STATUS_MAIN_IMAGE_READY = "main_image_ready"
STATUS_MAIN_IMAGE_CONFIRMED = "main_image_confirmed"
STATUS_SCRIPT_QUEUED = "script_queued"
STATUS_SCRIPT_GENERATING = "script_generating"
STATUS_SCRIPT_READY = "script_ready"
STATUS_SCRIPT_CONFIRMED = "script_confirmed"
STATUS_VOICE_QUEUED = "voice_queued"
STATUS_VOICE_GENERATING = "voice_generating"
STATUS_VOICE_READY = "voice_ready"
STATUS_SUBTITLE_QUEUED = "subtitle_queued"
STATUS_SUBTITLE_GENERATING = "subtitle_generating"
STATUS_SUBTITLE_READY = "subtitle_ready"
STATUS_AUDIO_SUBTITLE_CONFIRMED = "audio_subtitle_confirmed"
STATUS_CONTENT_PLAN_READY = "content_plan_ready"
STATUS_CONTENT_PLAN_CONFIRMED = "content_plan_confirmed"
STATUS_CONTENT_QA_PASSED = "content_qa_passed"
STATUS_CONTENT_QA_FAILED = "content_qa_failed"
STATUS_VIDEO_PLAN_READY = "video_plan_ready"
STATUS_VIDEO_GENERATING = "video_generating"
STATUS_VIDEO_READY = "video_ready"
STATUS_RENDERING = "rendering"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PipelineRun:
    id: str
    project_id: str
    status: str
    current_step: int
    state_version: int
    created_at: datetime
    updated_at: datetime
