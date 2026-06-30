# AI互动实验

`AI互动实验` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

服务包含 AI互动实验生成链路：静态知识点命中、主题色注入、未命中时的大模型互动 HTML fallback、fallback 输出校验与一次自动修复。

当前不包含前端、导出、数据库或任务队列能力。

## 目录结构

```text
ai-interactive-experiment/
├── aetherviz_service/
│   ├── main.py
│   ├── config.py
│   ├── llm_service.py
│   ├── routers/
│   │   └── aetherviz.py
│   └── aetherviz/
│       ├── react.py
│       ├── fallback_planner.py
│       ├── fallback_validator.py
│       ├── validator.py
│       ├── knowledge_points.py
│       ├── cover_images.py
│       ├── matcher.py
│       ├── static_html.py
│       ├── html/
│       │   ├── biology/
│       │   ├── chemistry/
│       │   ├── chinese/
│       │   ├── math/
│       │   └── physics/
│       └── schemas/
│           └── aetherviz.py
├── tests/
│   ├── test_aetherviz.py
│   └── test_llm_service.py
├── pyproject.toml
├── requirements.txt
├── Dockerfile
├── docker-compose.dev.yml
└── docker-compose.prod.yml
```

Python 包名为 `aetherviz_service`，服务标题为 `AI互动实验`。

## 安装依赖

推荐使用 `uv`：

```bash
uv python pin 3.12
uv sync --dev
```

也可以通过 `requirements.txt` 查看运行依赖。依赖声明以 `pyproject.toml` 为准。

## 配置

创建本地 `.env` 并填写 OpenAI-compatible 模型服务配置：

```bash
OPENAI_API_KEY="你的 OpenAI-compatible API Key"
OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_MODEL="qwen3.7-plus"
```

`OPENAI_MODEL` 支持逗号分隔的候选模型列表，服务调用时使用第一个模型。不要把真实 API Key 提交到仓库。

## 启动服务

本地直接启动：

```bash
uv run uvicorn aetherviz_service.main:app --reload --port 10095
```

Docker 开发环境：

```bash
docker compose -f docker-compose.dev.yml up app
```

生产编排：

```bash
docker compose -f docker-compose.prod.yml up -d app
```

开发环境已开启 CORS `allow_origins=["*"]`。生产环境应按实际前端域名收敛 CORS 配置。

## API

### GET /aetherviz-static-knowledge-points

返回当前已注册、可直接命中静态 HTML 的 AI互动实验知识点列表。该接口不调用大模型，适合前端展示可用主题、搜索提示或调试静态命中覆盖范围。

响应示例：

```json
{
  "success": true,
  "total": 1,
  "knowledge_points": [
    {
      "knowledge_point_id": "physics/newton_second_law",
      "title": "牛顿第二定律",
      "subject": "physics",
      "knowledge_domain": "mechanics",
      "grade": "高一",
      "keywords": ["牛顿第二定律", "F=ma", "加速度"],
      "render_mode": "static-html",
      "static_html_slug": "newton-second-law",
      "static_html_path": "physics/newton-second-law.html",
      "core_concepts": ["牛顿第二定律", "F=ma", "加速度"],
      "key_formulas": [],
      "cover_image_base64": "/9j/4AAQSkZJRgABAQA..."
    }
  ]
}
```

`cover_image_base64` 为静态 HTML 首屏封面截图的 JPEG base64 字符串，不包含 `data:image/jpeg;base64,` 前缀。

### GET /aetherviz-static-html

根据 `knowledge_point_id` 返回已注册静态知识点对应的完整独立 HTML。该接口不调用大模型。

请求参数：

- `knowledge_point_id`：必填，例如 `physics/newton_second_law`。

响应示例：

```json
{
  "success": true,
  "knowledge_point_id": "physics/newton_second_law",
  "title": "牛顿第二定律",
  "subject": "physics",
  "knowledge_domain": "mechanics",
  "grade": "高一",
  "render_mode": "static-html",
  "static_html_slug": "newton-second-law",
  "static_html_path": "physics/newton-second-law.html",
  "primary_color": "#22D3EE",
  "html": "<!DOCTYPE html><html lang=\"zh-CN\">...</html>"
}
```

错误约定：

- `404`：`knowledge_point_id` 未注册为静态知识点。
- `500`：知识点已注册，但对应静态 HTML 文件不存在或格式不正确。

### POST /generate-aetherviz-spec

根据教学主题生成 AI互动实验风格的完整独立互动教学 HTML。请求体只接收 `topic`。

请求示例：

```json
{
  "topic": "牛顿第二定律"
}
```

响应类型为 `text/event-stream`。事件包括：

- `start`：生成任务启动。
- `progress`：阶段进度，例如 `static_match`、`planning` 或 `generating`。
- `done`：生成完成，包含最终 `html` 和 `metadata`。
- `error`：生成失败，包含用户可读 `message`、阶段 `stage` 和调试用 `detail`。

典型静态命中流程：

```text
event: start
data: {"success": true, "stage": "start", "message": "开始生成《牛顿第二定律》的互动可视化页面", "progress": 3}

event: progress
data: {"success": true, "stage": "static_match", "message": "已命中静态知识点：牛顿第二定律", "progress": 35, "subject": "physics", "knowledge_domain": "mechanics", "knowledge_point_id": "physics/newton_second_law", "grade": "高一", "match_confidence": 0.98}

event: done
data: {"success": true, "stage": "done", "message": "已返回静态互动可视化页面", "progress": 100, "html": "<!DOCTYPE html><html lang=\"zh-CN\">...</html>", "metadata": {"topic": "牛顿第二定律", "attempts": 0, "source": "static_html", "degraded": false, "knowledge_point_id": "physics/newton_second_law"}}
```

错误约定：

- `400`：`topic` 为空。
- SSE `error` 且 `stage=static_html_missing`：主题已命中知识点，但静态 HTML 文件不可用。
- SSE `error` 且 `stage=llm_error`：调用模型服务失败。
- SSE `error` 且 `stage=fallback_failed`：互动 HTML 输出解析或基础质量门未通过。
- SSE `error` 且 `stage=validation_failed`：fallback HTML 未通过结构、安全、依赖、交互或可视化区域检查。
- SSE `error` 且 `stage=unknown_error`：生成过程中发生未预期异常。

## 生成流程

`/generate-aetherviz-spec` 使用“静态优先 + 动态兜底”策略：

1. 通过 `matcher.py` 对主题做服务端知识点关键词匹配。
2. 命中后读取 `aetherviz/html/{subject}/{slug}.html`，并通过 `static_html.py` 注入运行时主题色覆盖层。
3. 未命中时由 `fallback_planner.py` 构造轻量规划提示词并解析规划 JSON。
4. `react.py` 调用大模型生成完整自包含互动 HTML。
5. `fallback_validator.py` 提取 HTML、清理代码围栏，并对截断输出做轻量闭合。
6. `validator.py` 执行文档结构、安全、依赖、交互和可视化区域校验；首次失败时最多自动修复一次。

主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色 `#22D3EE`。主题色适配通过后置 `:root` 覆盖层完成，不批量替换整份 HTML，也不覆盖学科语义色。

## 静态 HTML 开发

新增可静态命中的知识点时，需要：

1. 在 `aetherviz_service/aetherviz/html/{subject}/` 下新增完整独立 HTML 文件。
2. 在 `aetherviz_service/aetherviz/knowledge_points.py` 注册知识点标题、关键词、年级 `grade`、知识域和 `static_html_slug`。
3. 在 `aetherviz_service/aetherviz/cover_images.py` 添加首屏 JPEG 封面 base64，键名使用 `{subject}/{static_html_slug}`。
4. 在 `tests/test_aetherviz.py` 覆盖静态文件映射、主题色注入、命中后不调用 LLM，以及必要的学科或年级断言。

静态 HTML 应保持完整独立，可直接保存和打开。

## 验证

运行 AI互动实验测试：

```bash
uv run pytest tests/test_aetherviz.py tests/test_llm_service.py
```

运行全量测试：

```bash
uv run pytest
```

curl 示例：

```bash
curl -N -X POST http://localhost:10095/generate-aetherviz-spec \
  -H "Content-Type: application/json" \
  -d '{"topic":"牛顿第二定律"}'
```

```bash
curl "http://localhost:10095/aetherviz-static-html?knowledge_point_id=physics/newton_second_law"
```
