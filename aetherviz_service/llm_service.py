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


@dataclass(frozen=True)
class ActiveLLMConfig:
    api_key: str
    model: str
    base_url: str | None


@dataclass(frozen=True)
class LLMStreamChunk:
    kind: str
    delta: str


def _primary_model_name(models: str | None) -> str | None:
    if not models:
        return None
    model = models.split(",", maxsplit=1)[0].strip()
    return model or None


def _resolve_llm_config(config=None) -> ActiveLLMConfig:
    if config is None:
        config = settings

    if config.openai_api_key:
        return ActiveLLMConfig(
            api_key=config.openai_api_key,
            model=_primary_model_name(config.openai_model) or DEFAULT_OPENAI_COMPATIBLE_MODEL,
            base_url=config.openai_base_url or DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
        )

    raise LLMServiceError("缺少 OPENAI_API_KEY 环境变量")


def _openai_client() -> tuple[OpenAI, ActiveLLMConfig]:
    llm_config = _resolve_llm_config()

    client_kwargs: dict[str, str] = {"api_key": llm_config.api_key}
    if llm_config.base_url:
        client_kwargs["base_url"] = llm_config.base_url

    return OpenAI(**client_kwargs), llm_config


def _supports_dashscope_thinking(base_url: str | None) -> bool:
    if not base_url:
        return False
    normalized = base_url.lower()
    return "dashscope.aliyuncs.com" in normalized or "maas.aliyuncs.com" in normalized


def call_llm(prompt: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT, max_tokens: int = 16384, temperature: float = 0.3) -> str:
    client, llm_config = _openai_client()

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
) -> Iterator[LLMStreamChunk]:
    client, llm_config = _openai_client()
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


def strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fenced = re.fullmatch(r"```[a-zA-Z0-9_-]*\s*(.*?)\s*```", stripped, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    # 只去掉开头和结尾的围栏标记，不破坏正文中可能存在的模板字面量反引号
    stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()
