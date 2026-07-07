import re
from collections.abc import Iterator
from dataclasses import dataclass

from openai import OpenAI, OpenAIError

from aetherviz_service.config import settings


class LLMServiceError(RuntimeError):
    pass


DEFAULT_SYSTEM_PROMPT = "你是一个严谨的 AI互动实验互动教学 HTML 生成助手，只输出用户要求的 HTML 内容。"
DEFAULT_OPENAI_COMPATIBLE_MODEL = "qwen3.7-plus"
DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_PLANNING_MODEL = "deepseek-v4-flash"
DEFAULT_PLANNING_REASONING_EFFORT = "high"


@dataclass(frozen=True)
class ActiveLLMConfig:
    api_key: str
    model: str
    base_url: str | None
    reasoning_effort: str | None = None


@dataclass(frozen=True)
class LLMStreamChunk:
    kind: str
    delta: str


def _primary_model_name(models: str | None) -> str | None:
    if not models:
        return None
    model = models.split(",", maxsplit=1)[0].strip()
    return model or None


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_llm_config(config=None, *, use_planning_model: bool = False) -> ActiveLLMConfig:
    if config is None:
        config = settings

    if use_planning_model:
        api_key = _blank_to_none(getattr(config, "planning_openai_api_key", None)) or _blank_to_none(
            config.openai_api_key
        )
        if api_key:
            planning_model = _primary_model_name(getattr(config, "planning_openai_model", None))
            return ActiveLLMConfig(
                api_key=api_key,
                model=planning_model or DEFAULT_PLANNING_MODEL,
                base_url=_blank_to_none(getattr(config, "planning_openai_base_url", None))
                or _blank_to_none(config.openai_base_url)
                or DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
                reasoning_effort=_blank_to_none(getattr(config, "planning_reasoning_effort", None))
                or DEFAULT_PLANNING_REASONING_EFFORT,
            )
        raise LLMServiceError("缺少 PLANNING_OPENAI_API_KEY 或 OPENAI_API_KEY 环境变量")

    api_key = _blank_to_none(config.openai_api_key)
    if api_key:
        return ActiveLLMConfig(
            api_key=api_key,
            model=_primary_model_name(config.openai_model) or DEFAULT_OPENAI_COMPATIBLE_MODEL,
            base_url=_blank_to_none(config.openai_base_url) or DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
        )

    raise LLMServiceError("缺少 OPENAI_API_KEY 环境变量")


def _openai_client(*, use_planning_model: bool = False) -> tuple[OpenAI, ActiveLLMConfig]:
    llm_config = _resolve_llm_config(use_planning_model=use_planning_model)

    client_kwargs: dict[str, str] = {"api_key": llm_config.api_key}
    if llm_config.base_url:
        client_kwargs["base_url"] = llm_config.base_url

    return OpenAI(**client_kwargs), llm_config


def _supports_dashscope_thinking(base_url: str | None) -> bool:
    if not base_url:
        return False
    normalized = base_url.lower()
    return "dashscope.aliyuncs.com" in normalized or "maas.aliyuncs.com" in normalized


def _uses_deepseek_v4(model: str) -> bool:
    return model.strip().lower().startswith("deepseek-v4")


def call_llm(
    prompt: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 16384,
    temperature: float = 0.3,
    *,
    use_planning_model: bool = False,
) -> str:
    client, llm_config = _openai_client(use_planning_model=use_planning_model)

    try:
        response = client.chat.completions.create(
            model=llm_config.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
        )
    except OpenAIError as exc:
        raise LLMServiceError(f"调用大模型失败：{exc}") from exc

    if not response.choices:
        raise LLMServiceError("模型响应 choices 为空，请检查模型服务状态")
    content = response.choices[0].message.content or ""
    return strip_code_fences(content).strip()


def call_llm_stream(
    prompt: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 16384,
    temperature: float = 0.3,
    enable_thinking: bool = False,
    use_planning_model: bool = False,
) -> Iterator[LLMStreamChunk]:
    client, llm_config = _openai_client(use_planning_model=use_planning_model)
    stream = None

    try:
        request_kwargs = {
            "model": llm_config.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
        }
        if enable_thinking and _supports_dashscope_thinking(llm_config.base_url):
            if llm_config.reasoning_effort and _uses_deepseek_v4(llm_config.model):
                request_kwargs["reasoning_effort"] = llm_config.reasoning_effort
            else:
                request_kwargs["extra_body"] = {"enable_thinking": True}

        stream = client.chat.completions.create(**request_kwargs)
        for chunk in stream:
            # qwen3 等模型流式输出时会发送 choices=[] 的特殊 chunk（如 usage 包或结束信号）
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning_delta = getattr(delta, "reasoning_content", None) or ""
            content_delta = delta.content or ""
            if enable_thinking and reasoning_delta:
                yield LLMStreamChunk(kind="reasoning", delta=reasoning_delta)
            if content_delta:
                yield LLMStreamChunk(kind="content", delta=content_delta)
    except OpenAIError as exc:
        raise LLMServiceError(f"调用大模型失败：{exc}") from exc
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()


def call_planning_llm_stream(
    prompt: str,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 16384,
    temperature: float = 0.3,
    enable_thinking: bool = True,
) -> Iterator[LLMStreamChunk]:
    yield from call_llm_stream(
        prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        enable_thinking=enable_thinking,
        use_planning_model=True,
    )


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fenced = re.fullmatch(r"```[a-zA-Z0-9_-]*\s*(.*?)\s*```", stripped, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # 只去掉开头和结尾的围栏标记，不破坏正文中可能存在的模板字面量反引号
    stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()
