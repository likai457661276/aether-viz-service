# AI互动实验

`AI互动实验` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

当前生成链路只保留 OpenMAIC 风格的动态单页互动课件：先生成可确认的 `interactive` 计划，再按确认计划生成自包含 HTML。项目不再包含静态知识点命中、静态 HTML 文件读取或静态 HTML 返回接口。

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
│       ├── generation_stream.py
│       ├── html_output.py
│       ├── planning_stream.py
│       ├── prompts.py
│       ├── revision_plan_stream.py
│       ├── theme.py
│       ├── validator.py
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

依赖声明以 `pyproject.toml` 为准。

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

## 前端联调项目

关联前端项目为 `bingo-aetherviz` / `AI动态课件`：

```text
/Users/likai/Documents/workspace/bingo-aetherviz
```

前端是 Vite + React + TypeScript 应用，负责 chat 工作区、计划确认、SSE 事件消费、多个 HTML 产物管理、iframe `srcDoc` 预览和运行时错误桥接。后端负责 OpenMAIC widget 计划、HTML 生成、HTML 文件编辑、基础语法/安全校验、自动修复和最终自包含 HTML 输出。

职责边界：

- 前端不渲染课件内部 SVG、Canvas 或 DOM 互动逻辑。
- 前端不把后端生成物依赖重新搬回 React 组件。
- 前端只消费后端返回的自包含 HTML，并通过 iframe 隔离预览。
- `phase=revise` 只发送主题、修改意见和摘要型 `context`，用于修改教案计划，不发送完整 HTML。
- `phase=edit` 发送主题、修改意见、选中 HTML 文件全文 `current_html` 和摘要型 `context`，用于基于已有 HTML 生成新的 HTML 分支。

前端联调命令以该前端仓库 `package.json` 为准，常用命令：

```bash
cd /Users/likai/Documents/workspace/bingo-aetherviz
pnpm dev:local
pnpm dev:local:proxy
pnpm build
```

其中 `pnpm dev:local` 通过 `VITE_API_BASE_URL=http://localhost:10095` 直连本后端，`pnpm dev:local:proxy` 通过 Vite proxy 指向本后端。

## API

### POST /generate-aetherviz-spec

根据教学主题生成 AI互动实验风格的完整独立互动教学 HTML。接口采用同端 SSE，统一走动态 OpenMAIC 生成链路，计划类型固定为单页 `interactive`，并通过 `interactive_type` 分流为 `simulation`、`diagram` 或 `game`。

计划阶段请求示例：

```json
{
  "topic": "熵增演示",
  "phase": "plan"
}
```

生成阶段请求示例：

```json
{
  "topic": "熵增演示",
  "phase": "generate",
  "approved_plan": {
    "page_type": "interactive",
    "interactive_type": "simulation",
    "subject": "general",
    "title": "熵增演示互动动画",
    "goal": "用分层动画解释熵增的核心过程。",
    "learner_level": "初中/高中",
    "stage_layout": "顶部展示学习目标，中间大舞台展示粒子扩散轨迹，底部放置播放控制和结论区。",
    "interactive_spec": {
      "type": "simulation",
      "concept": "熵增",
      "description": "通过调节速度观察粒子从有序到无序的变化。",
      "variables": [
        {"name": "speed", "label": "速度", "min": 0.5, "max": 2, "default": 1, "step": 0.1, "unit": "x"}
      ],
      "presets": [{"id": "default", "label": "默认", "values": {"speed": 1}}],
      "observations": ["观察扩散速度改变后，粒子状态和结论如何同步变化。"]
    },
    "teaching_flow": [
      {"id": "observe", "label": "观察初始状态", "focus": "粒子从有序聚集开始", "caption": "先观察初始有序状态。"},
      {"id": "interact", "label": "调节速度", "focus": "粒子扩散并留下轨迹", "caption": "拖动速度观察扩散差异。"},
      {"id": "conclude", "label": "形成结论", "focus": "结论区高亮无序度增加", "caption": "把观察结果和熵增规律对应起来。"}
    ],
    "controls": [
      {"id": "speed-control", "label": "速度", "type": "slider", "bind": "speed"},
      {"id": "replay-btn", "label": "演示一次", "type": "button", "action": "play"},
      {"id": "reset-button", "label": "重置", "type": "button", "action": "reset"}
    ],
    "formulas": [],
    "runtime": {"render_stack": "svg_canvas", "animation_runtime": "native", "external_libraries": []},
    "primary_color": "#22D3EE"
  }
}
```

重新规划阶段请求示例：

```json
{
  "topic": "熵增演示",
  "phase": "revise",
  "instruction": "把动画速度调慢，说明文字放到左侧",
  "context": {
    "topic": "熵增演示",
    "selected_file": {
      "id": "html-...",
      "title": "熵增演示",
      "mode": "simulation",
      "topic": "熵增演示",
      "html_size": 12345,
      "created_at": 1760000000000
    },
    "available_files": [],
    "plan_summary": {
      "title": "熵增演示互动动画",
      "goal": "用分层动画解释熵增的核心过程。",
      "mode": "simulation",
      "interactive_type": "simulation"
    },
    "memory": {
      "topic": "熵增演示",
      "summary": "已生成互动实验 HTML。",
      "user_preferences": [],
      "completed_regenerations": [],
      "open_questions": [],
      "current_file_notes": {},
      "updated_at": 1760000000000
    },
    "recent_messages": [],
    "user_message": "把动画速度调慢，说明文字放到左侧"
  }
}
```

`context` 是前端 chat 会话的可选上下文字段，用于描述当前选择的文件摘要、可用文件摘要、计划摘要、短期记忆和最近有效消息。`phase=revise` 不接收也不读取完整 HTML，只基于用户要求和计划摘要生成新的 `plan_ready`，用户确认后再用 `phase=generate` 生成新的 HTML 分支。

HTML 文件编辑阶段请求示例：

```json
{
  "topic": "熵增演示",
  "phase": "edit",
  "instruction": "把标题改成慢速演示，并把说明文字放到左侧",
  "current_html": "<!DOCTYPE html>...",
  "context": {
    "selected_file": {
      "id": "html-...",
      "title": "熵增演示",
      "mode": "simulation",
      "topic": "熵增演示",
      "html_size": 12345,
      "created_at": 1760000000000
    },
    "plan_summary": {
      "title": "熵增演示互动动画",
      "goal": "用分层动画解释熵增的核心过程。",
      "mode": "simulation",
      "interactive_type": "simulation"
    }
  }
}
```

`phase=edit` 必须携带选中的 HTML 文件全文。后端以该文件为修改基线，根据 `instruction` 生成新的完整 HTML，前端保存为新的时间线分支，不覆盖原文件。

响应类型为 `text/event-stream`。事件包括：

- `start`：生成任务启动。
- `progress`：阶段进度，例如 `planning`、`generating`、`html_editing` 或 `repairing`。
- `thinking_delta`：HTML 生成、HTML 编辑、自动修复和修订阶段的用户可读中文思考摘要；计划阶段默认不启用思考流。
- `plan_delta`：计划阶段或重新规划阶段的结构化计划 JSON 输出片段。
- `plan_ready`：计划阶段完成，包含结构化 `plan`；用户确认后再请求 `phase=generate`。
- `generation_delta`：生成阶段的大模型输出片段，携带本次 `output_tokens` 和累计 `output_tokens_total`。
- `done`：生成完成，包含最终 `html` 和 `metadata`。
- `error`：生成失败，包含用户可读 `message`、阶段 `stage` 和调试用 `detail`。

错误约定：

- `400`：`topic` 为空。
- `400`：`phase=generate` 时缺少 `approved_plan`。
- `400`：`phase=revise` 时缺少 `instruction`。
- `400`：`phase=edit` 时缺少 `instruction` 或 `current_html`。
- SSE `error` 且 `stage=llm_error`：调用模型服务失败。
- SSE `error` 且 `stage=html_generation_failed`：互动 HTML 输出解析或自动修复未通过基础质量门。
- SSE `error` 且 `stage=validation_failed`：HTML 未通过基础文档结构、安全边界或内联脚本语法检查。
- SSE `error` 且 `stage=unknown_error`：生成过程中发生未预期异常。

## 生成流程

`/generate-aetherviz-spec` 使用动态双阶段生成策略：

1. `phase=plan` 时由 `fallback_planner.py` 生成单页 interactive 计划，字段包括 `page_type`、`interactive_type`、`widget_type`、`scene_outline`、`subject`、`title`、`goal`、`stage_layout`、`key_points`、`design_brief`、`interactive_spec`、`widget_outline`、`widget_actions`、`teaching_flow`、`controls`、`formulas`、`runtime` 和 `primary_color`。
2. 前端确认计划后，以 `phase=generate` 携带 `approved_plan` 再次请求。
3. `react.py` 按 `interactive_type` 选择 simulation、diagram 或 game 生成 prompt；生成逻辑以 OpenMAIC interactive 为核心，HTML 内需包含 `script#widget-config` 和 iframe message action listener；SVG 表达结构和标注，Canvas 承担连续运动、轨迹或粒子，DOM 承担步骤说明、公式和控制区；动画由原生 CSS transition/keyframes、`requestAnimationFrame` 和 DOM/SVG/Canvas 状态更新管理，不使用 GSAP。
4. `phase=revise` 时，后端忽略废弃的 HTML 入参，只基于 `instruction`、`context.plan_summary` 和会话摘要重新规划，返回新的 `plan_ready`，不生成补丁、不合并 HTML、不返回旧索引字段。
5. `phase=edit` 时，后端读取 `current_html` 作为唯一修改基线，根据 `instruction` 编辑 HTML，返回新的 `done.html` 分支，不覆盖旧 HTML。
6. `fallback_validator.py` 提取 HTML、清理代码围栏；`validator.py` 在生产生成链路只执行基础文档结构、安全边界和内联脚本语法检查。首次解析或基础校验失败时会发出 `progress stage=repairing` 并自动修复一次，成功时 `metadata.repaired=true`、`attempts=2`。
7. OpenMAIC 契约、运行时、交互完整性、主舞台质量等检查保留为开发测试能力，不作为生产返回前的硬拦截；用户可继续通过 chat 基于现有 HTML 逐步改进。

主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色 `#22D3EE`。

## OpenMAIC Widget 链路改造方向

本项目采用 Widget 链路级 OpenMAIC 对齐：保留当前 FastAPI 单页 SSE 接口，不迁移 OpenMAIC 的 Next.js、多场景课堂、LangGraph 或多 Agent 应用架构。

默认改造方向：

- 保留现有公共接口 `POST /generate-aetherviz-spec`，不新增静态 HTML 接口。
- 计划对象继续以 `page_type: "interactive"` 为主，保留 `interactive_type` 兼容前端；可补充 OpenMAIC 风格 `widget_type` / `widget_outline`，但不得破坏现有前端字段。
- 后端按 `simulation`、`diagram`、`game` 拆分独立 prompt、分型 widget-config 和开发期分型校验。
- 计划对象必须包含 OpenMAIC 风格 `scene_outline`、`widget_outline`、`design_brief` 和 `widget_actions`，作为后续 HTML 生成的唯一蓝图。
- `validator.py` 保留主题语义与 `interactive_spec` 对主舞台元素的一致性检查，但生产生成链路只使用基础语法/安全校验。
- 前端可展示 `source`、`attempts`、`repaired`、`degraded` 和 `validation_warnings`。
- 前端保留 iframe 隔离和运行时错误桥接，并支持向 iframe 发送 OpenMAIC widget action：`SET_WIDGET_STATE`、`HIGHLIGHT_ELEMENT`、`ANNOTATE_ELEMENT`、`REVEAL_ELEMENT`。

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
