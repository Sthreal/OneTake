from onetake_api.modules.script.domain import ScriptDraft, ScriptInput


class MockScriptAdapter:
    provider_name = "mock-qwen-vl-plus"
    model = "qwen-vl-plus"

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
    ) -> ScriptDraft:
        product = script_input.product_name
        hook = f"还在为{script_input.pain_point}烦恼？看看{product}。"
        pain = f"重点看它的实际表现。"
        points = [f"{point}。" for point in script_input.selling_points]
        scenario = f"日常用起来很自然。"
        if script_input.offer:
            cta = f"感兴趣就来看看。"
        else:
            cta = "想确认这些特点，现在就进一步看看。"
        return ScriptDraft(
            hook=hook,
            pain_point=pain,
            selling_points=tuple(points),
            usage_scenario=scenario,
            cta=cta,
        )

