FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY aetherviz_service ./aetherviz_service

RUN uv sync --frozen --no-dev

EXPOSE 10095

CMD ["/opt/venv/bin/uvicorn", "aetherviz_service.main:app", "--host", "0.0.0.0", "--port", "10095"]
