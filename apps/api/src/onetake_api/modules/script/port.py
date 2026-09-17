from typing import Protocol

from onetake_api.modules.script.domain import ScriptDraft, ScriptInput


class ScriptPort(Protocol):
    provider_name: str
    model: str

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
    ) -> ScriptDraft: ...
