FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_LINK_MODE=copy

RUN pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY markdown_to_html_ppt ./markdown_to_html_ppt

RUN uv sync --frozen --no-dev

EXPOSE 10095

CMD ["uv", "run", "--frozen", "uvicorn", "markdown_to_html_ppt.main:app", "--host", "0.0.0.0", "--port", "10095"]
