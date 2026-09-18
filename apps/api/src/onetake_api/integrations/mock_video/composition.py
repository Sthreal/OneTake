from onetake_api.integrations.mock_video.renderer import compose_final_video
from onetake_api.modules.composition.port import CompositionRequest


class MockCompositionAdapter:
    provider_name = "mock-video"

    def compose(self, request: CompositionRequest) -> bytes:
        return compose_final_video(
            base_video_bytes=request.base_video_bytes,
            audio_bytes=request.audio_bytes,
            srt_bytes=request.srt_bytes,
            duration_seconds=request.duration_seconds,
            fps=request.fps,
        )
