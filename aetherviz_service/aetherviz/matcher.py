"""AetherViz 模板匹配结果结构与服务端校验。"""

from dataclasses import dataclass
import re

from aetherviz_service.aetherviz.knowledge_points import (
    KNOWLEDGE_POINTS,
    get_knowledge_point,
)


SUPPORTED_RENDER_MODES = {"static-html"}


class AetherVizTemplateMatchError(ValueError):
    pass


@dataclass(frozen=True)
class AetherVizTemplateMatch:
    supported: bool
    subject: str
    knowledge_domain: str
    knowledge_point_id: str
    knowledge_point_title: str
    grade: str | None
    render_mode: str
    confidence: float
    reason: str


def match_topic_to_knowledge_point(topic: str) -> AetherVizTemplateMatch | None:
    """用服务端关键词优先匹配已注册知识点。

    匹配成功后直接返回可校验的静态知识点匹配结果；无法可靠命中时返回 None，
    由接口入口继续走 LLM 规划和自包含互动 HTML 降级生成。
    """
    normalized_topic = _normalize(topic)
    if not normalized_topic:
        return None

    exact_candidates: list[tuple[int, object]] = []
    for point in KNOWLEDGE_POINTS.values():
        terms = (point.title, *point.keywords)
        for term in terms:
            normalized_term = _normalize(term)
            if normalized_term and normalized_term in normalized_topic:
                exact_candidates.append((len(normalized_term), point))
                break

    if exact_candidates:
        _, point = max(exact_candidates, key=lambda item: item[0])
        return _match_from_point(point, 0.98, "服务端关键词精确匹配")

    topic_tokens = _tokens(normalized_topic)
    best_point = None
    best_score = 0.0
    for point in KNOWLEDGE_POINTS.values():
        keyword_text = _normalize(" ".join((point.title, *point.keywords, *point.core_concepts)))
        keyword_tokens = _tokens(keyword_text)
        if not keyword_tokens:
            continue
        overlap = len(topic_tokens & keyword_tokens) / max(1, min(len(topic_tokens), len(keyword_tokens)))
        char_overlap = len(set(normalized_topic) & set(keyword_text)) / max(1, len(set(normalized_topic)))
        score = max(overlap, char_overlap * 0.72)
        if score > best_score:
            best_score = score
            best_point = point

    if best_point is not None and best_score >= 0.62:
        return _match_from_point(best_point, min(0.92, best_score), "服务端关键词模糊匹配")
    return None


def validate_aetherviz_template_match(match: AetherVizTemplateMatch) -> None:
    if not match.supported:
        return
    if match.render_mode not in SUPPORTED_RENDER_MODES:
        raise AetherVizTemplateMatchError(f"不支持的渲染模式：{match.render_mode or '空'}")
    point = get_knowledge_point(match.knowledge_point_id)
    if point is None:
        raise AetherVizTemplateMatchError(f"不支持的知识点：{match.knowledge_point_id or '空'}")
    if point.subject != match.subject or point.knowledge_domain != match.knowledge_domain:
        raise AetherVizTemplateMatchError(
            f"知识点与学科/知识域不匹配：{match.knowledge_point_id}"
        )
    if point.render_mode != match.render_mode:
        raise AetherVizTemplateMatchError(
            f"知识点渲染模式不匹配：{match.render_mode or '空'}"
        )


def _match_from_point(point, confidence: float, reason: str) -> AetherVizTemplateMatch:
    match = AetherVizTemplateMatch(
        supported=True,
        subject=point.subject,
        knowledge_domain=point.knowledge_domain,
        knowledge_point_id=point.knowledge_point_id,
        knowledge_point_title=point.title,
        grade=point.grade,
        render_mode=point.render_mode,
        confidence=confidence,
        reason=reason,
    )
    validate_aetherviz_template_match(match)
    return match


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _tokens(value: str) -> set[str]:
    ascii_tokens = set(re.findall(r"[a-z0-9]+", value))
    cjk_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}", value))
    chars = {char for char in value if "\u4e00" <= char <= "\u9fff"}
    return ascii_tokens | cjk_tokens | chars
