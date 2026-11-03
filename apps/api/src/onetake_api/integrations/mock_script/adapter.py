import re

from onetake_api.modules.script.content import MAX_CHARACTERS, MIN_CHARACTERS, spoken_character_count
from onetake_api.modules.script.copy_rules import MIN_HOOK_SPOKEN_CHARS
from onetake_api.modules.script.domain import ScriptDraft, ScriptInput

_UNSET = object()

# 场景句收在「顺手看看」，和切片 A 的双 CTA 轻提同一句尾巴，rebase 后仍能过校验。
_LIGHT_TAIL = "顺手看看"
_PAD = "用着也省心"
# 卖点被整段裁掉时的中性替身，不含数字，避免造出输入里没有的事实。
_POINT_FALLBACK = "表现"
# 与 content._NUMBER_RE 同一写法：裁词只能落在数字边界上，不能把「12」裁成「1」。
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")
_CLIP_TAIL = " \t，,、；;：:。！？!?"


def _spoken(*parts: str) -> int:
    return spoken_character_count("".join(parts))


def _fit_scenario(hook: str, pain: str, points: list[str], body: str, cta: str) -> str:
    """短输入补到口播字数下限。尾巴始终是轻提，避免把补字贴进 hook。"""
    scenario = f"{body}，{_LIGHT_TAIL}。"
    for _ in range(8):
        if _spoken(hook, pain, "".join(points), scenario, cta) >= MIN_CHARACTERS:
            return scenario
        body = f"{body}{_PAD}"
        scenario = f"{body}，{_LIGHT_TAIL}。"
    return scenario


def _draft_spoken(draft: ScriptDraft) -> int:
    return _spoken(draft.hook, draft.pain_point, "".join(draft.selling_points), draft.usage_scenario, draft.cta)


def _clip_spoken(text: str, limit: int) -> str:
    """保留不超过 `limit` 个口播字的前缀，且不切开数字。"""
    if limit <= 0 or not text:
        return ""
    if spoken_character_count(text) <= limit:
        return text
    lo, hi = 0, len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if spoken_character_count(text[:mid]) <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    cut = best
    for match in _NUMBER_RE.finditer(text):
        unit_end = match.end()
        while unit_end < len(text) and text[unit_end].isascii() and text[unit_end].isalpha():
            unit_end += 1
        if match.start() < cut < match.end():
            cut = match.start()
            break
        # 「300ml」不能裁成「300m」：数字留整，半截单位丢掉。
        if match.end() < cut < unit_end:
            cut = match.end()
            break
    return text[:cut].rstrip(_CLIP_TAIL)


def _shorter(text: str) -> str | None:
    current = spoken_character_count(text)
    if current <= 0:
        return None
    clipped = _clip_spoken(text, current - 1)
    if spoken_character_count(clipped) < current:
        return clipped
    return None


def _scenario_line(body: str) -> str:
    body = body.strip()
    if not body:
        return f"{_LIGHT_TAIL}。"
    return f"{body}，{_LIGHT_TAIL}。"


def _cta_for(script_input: ScriptInput) -> str:
    if script_input.offer:
        return "感兴趣就来看看。"
    return "想确认这些特点，现在就进一步看看。"


class _LongDraft:
    """只在整稿超过上限时使用。短事实不进这里，原模板句子保持不变。"""

    def __init__(self, script_input: ScriptInput, angle: str) -> None:
        self.angle = angle
        self.cta = _cta_for(script_input)
        self.pain = script_input.pain_point
        self.product = script_input.product_name
        self.filler = "日常用起来很自然"
        self.scene_excerpt = script_input.usage_scenario
        self.comparison_body = "比一次就明白"
        self.pain_line = "重点看它的实际表现"
        self.extra_pad = ""
        self.points = [point for point in script_input.selling_points if spoken_character_count(point) > 0]

    def _hook(self) -> str:
        if self.angle == "scene":
            return f"出门时怎么还不用{self.product}？"
        if self.angle == "comparison":
            return f"别再继续为{self.pain}烦着？"
        return f"还在为{self.pain}烦恼？看看{self.product}。"

    def _body(self) -> str:
        if self.angle == "scene":
            base = f"在{self.scene_excerpt}里用" if self.scene_excerpt else ""
        elif self.angle == "comparison":
            base = self.comparison_body
        else:
            base = self.filler
        return f"{base}{self.extra_pad}"

    def _point_lines(self) -> list[str]:
        kept = [f"{point}。" for point in self.points if spoken_character_count(point) > 0]
        if not kept:
            return [f"{_POINT_FALLBACK}。"]
        return kept

    def spoken(self) -> int:
        return _spoken(
            self._hook(),
            f"{self.pain_line}。",
            "".join(self._point_lines()),
            _scenario_line(self._body()),
            self.cta,
        )

    def _hook_ok(self) -> bool:
        return spoken_character_count(self._hook()) >= MIN_HOOK_SPOKEN_CHARS

    def _snapshot(self) -> tuple:
        return (
            self.pain,
            self.product,
            self.filler,
            self.scene_excerpt,
            self.comparison_body,
            self.pain_line,
            self.extra_pad,
            list(self.points),
        )

    def _restore(self, snap: tuple) -> None:
        (
            self.pain,
            self.product,
            self.filler,
            self.scene_excerpt,
            self.comparison_body,
            self.pain_line,
            self.extra_pad,
            points,
        ) = snap
        self.points = points

    def _commit(self, mutate) -> bool:
        snap = self._snapshot()
        before = self.spoken()
        mutate()
        if self.spoken() < before and self._hook_ok():
            return True
        self._restore(snap)
        return False

    def _drop_extra_point(self) -> bool:
        if len(self.points) <= 1:
            return False
        return self._commit(lambda: self.points.pop())

    def _shrink_filler(self) -> bool:
        # 整句进退，避免「日常用起来很自」这种半截垫词。
        steps = ("日常用起来很自然", "日常用", "")
        try:
            index = steps.index(self.filler)
        except ValueError:
            if not self.filler:
                return False
            return self._commit(lambda: setattr(self, "filler", ""))
        if index >= len(steps) - 1:
            return False
        nxt = steps[index + 1]
        return self._commit(lambda: setattr(self, "filler", nxt))

    def _shrink_field(self, name: str, *, empty_replacement: str | None = None) -> bool:
        current = getattr(self, name)
        nxt = _shorter(current)
        if nxt is None:
            return False
        if nxt == "" and empty_replacement is not None:
            nxt = empty_replacement
            if nxt == current:
                return False
        if nxt == "" and name == "pain_line":
            return False
        return self._commit(lambda: setattr(self, name, nxt))

    def _shrink_down_to(self, name: str, floor: int, *, empty_replacement: str | None = None) -> bool:
        if spoken_character_count(getattr(self, name)) <= floor:
            return False
        return self._shrink_field(name, empty_replacement=empty_replacement)

    def _shrink_first_point(self) -> bool:
        if not self.points:
            return False
        nxt = _shorter(self.points[0])
        if nxt is None:
            return False

        def mutate() -> None:
            if nxt == "":
                self.points.clear()
            else:
                self.points[0] = nxt

        return self._commit(mutate)

    def _shrink_comparison_body(self) -> bool:
        return self._shrink_field("comparison_body")

    def _reducers(self) -> list:
        # 先把过长摘录收到还能读的前缀，再丢多余卖点；垫词整句进退，仍超长才收到钩子下限。
        reducers = []
        if self.angle in {"pain_point", "comparison"}:
            reducers.append(lambda: self._shrink_down_to("pain", 8, empty_replacement="它"))
        if self.angle == "scene":
            reducers.append(lambda: self._shrink_down_to("scene_excerpt", 8))
        if self.angle in {"pain_point", "scene"}:
            reducers.append(lambda: self._shrink_down_to("product", 8))
        reducers.append(self._drop_extra_point)
        if self.angle == "pain_point":
            reducers.append(self._shrink_filler)
        if self.angle in {"pain_point", "comparison"}:
            reducers.append(lambda: self._shrink_down_to("pain", 0, empty_replacement="它"))
        if self.angle == "scene":
            reducers.append(lambda: self._shrink_down_to("scene_excerpt", 0))
        if self.angle in {"pain_point", "scene"}:
            reducers.append(lambda: self._shrink_down_to("product", 0))
        reducers.append(self._shrink_first_point)
        reducers.append(lambda: self._shrink_down_to("pain_line", 1))
        if self.angle == "comparison":
            reducers.append(self._shrink_comparison_body)
        return reducers

    def fit(self) -> ScriptDraft:
        for _ in range(800):
            if self.spoken() <= MAX_CHARACTERS:
                break
            if not any(reduce() for reduce in self._reducers()):
                self._force_floor()
                break
        else:
            self._force_floor()
        for _ in range(8):
            if self.spoken() >= MIN_CHARACTERS:
                break
            self.extra_pad += _PAD
        return ScriptDraft(
            hook=self._hook(),
            pain_point=f"{self.pain_line}。",
            selling_points=tuple(self._point_lines()),
            usage_scenario=_scenario_line(self._body()),
            cta=self.cta,
        )

    def _force_floor(self) -> None:
        """缩不动时收成不含数字的最短骨架，再交给下面的垫字补到下限。"""
        self.product = ""
        self.filler = ""
        self.scene_excerpt = ""
        self.extra_pad = ""
        self.points = []
        if self.angle != "scene":
            self.pain = "它"
        if self.angle == "comparison":
            self.comparison_body = "比一次就明白"
        while self.spoken() > MAX_CHARACTERS and spoken_character_count(self.pain_line) > 1:
            clipped = _clip_spoken(self.pain_line, spoken_character_count(self.pain_line) - 1)
            if not clipped or spoken_character_count(clipped) >= spoken_character_count(self.pain_line):
                break
            self.pain_line = clipped


def _fit_long_draft(script_input: ScriptInput, angle: str) -> ScriptDraft:
    """富化事实整段嵌进模板会超过 72 字。数字只整段保留，裁完不够 45 再垫。"""
    return _LongDraft(script_input, angle).fit()


def _angled_draft(script_input: ScriptInput, angle: str) -> ScriptDraft:
    product = script_input.product_name
    points = [f"{point}。" for point in script_input.selling_points]
    pain = "重点看它的实际表现。"
    if script_input.offer:
        cta = "感兴趣就来看看。"
    else:
        cta = "想确认这些特点，现在就进一步看看。"
    if angle == "scene":
        hook = f"出门时怎么还不用{product}？"
        body = f"在{script_input.usage_scenario}里用"
    elif angle == "comparison":
        hook = f"别再继续为{script_input.pain_point}烦着？"
        body = "比一次就明白"
    else:
        raise ValueError(f"未知文案角度：{angle}")
    draft = ScriptDraft(
        hook=hook,
        pain_point=pain,
        selling_points=tuple(points),
        usage_scenario=_fit_scenario(hook, pain, points, body, cta),
        cta=cta,
    )
    if _draft_spoken(draft) <= MAX_CHARACTERS:
        return draft
    return _fit_long_draft(script_input, angle)


class MockScriptAdapter:
    """Mock 文案。`review_script` 供单测配置审稿结果，不打真实模型。

    - 不设置：四维全过，改写等于原稿（等长自然满足）；
    - `ScriptReview`：原样返回；
    - `BaseException`：审稿时抛出；
    - callable(script_input, draft)：返回上述二者之一。
    类属性和构造参数都能设；`_adapter()` 走的是无参构造，单测用类属性即可。
    """

    provider_name = "mock-qwen-vl-plus"
    model = "qwen-vl-plus"
    review_script: object = _UNSET
    review_calls = 0

    def __init__(self, *, review_script: object = _UNSET) -> None:
        self._review_script = review_script

    def generate(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        script_input: ScriptInput,
        angle: str | None = None,
    ) -> ScriptDraft:
        # pain_point / 缺省走原来的痛点模板，旧调用方字数口径不变。
        if angle in {"scene", "comparison"}:
            return _angled_draft(script_input, angle)
        product = script_input.product_name
        hook = f"还在为{script_input.pain_point}烦恼？看看{product}。"
        pain = f"重点看它的实际表现。"
        points = [f"{point}。" for point in script_input.selling_points]
        # 末尾轻提是双 CTA 的前半句（P4A），完整行动号召仍放在 cta，避免把场景句写成第二段广告。
        scenario = "日常用起来很自然，顺手看看。"
        if script_input.offer:
            cta = f"感兴趣就来看看。"
        else:
            cta = "想确认这些特点，现在就进一步看看。"
        draft = ScriptDraft(
            hook=hook,
            pain_point=pain,
            selling_points=tuple(points),
            usage_scenario=scenario,
            cta=cta,
        )
        if _draft_spoken(draft) <= MAX_CHARACTERS:
            return draft
        return _fit_long_draft(script_input, "pain_point")

    def review(self, *, script_input: ScriptInput, draft: ScriptDraft):
        from onetake_api.integrations.qwen_vl_script.adapter import REVIEW_DIMENSIONS, ScriptReview

        MockScriptAdapter.review_calls += 1
        spec = self._review_script if self._review_script is not _UNSET else MockScriptAdapter.review_script
        if spec is _UNSET:
            return ScriptReview(
                dimensions={
                    name: {"passed": True, "reason": "mock 通过"}
                    for name in REVIEW_DIMENSIONS
                },
                revised=draft,
                changed_fields=[],
                provider=self.provider_name,
                model=self.model,
            )
        if isinstance(spec, BaseException):
            raise spec
        if isinstance(spec, ScriptReview):
            return spec
        if callable(spec):
            return spec(script_input=script_input, draft=draft)
        raise TypeError("MockScriptAdapter.review_script 必须是 ScriptReview、异常或 callable")

