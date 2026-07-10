# AI互动实验

`AI互动实验` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

当前生成链路只保留 Deep Agents 驱动的动态单页互动课件：先生成可确认的 `interactive` 教案计划，用户可多轮修订计划，确认后再生成自包含 HTML。HTML 会写入任务沙箱，并经过 HTML parser、JS checker、安全检查和长度检查；失败时由 `repair_agent` 自动修复。项目不再包含静态知识点命中、静态 HTML 文件读取或静态 HTML 返回接口。

## 目录结构

```text
aether-viz-service/
├── aetherviz_service/
│   ├── main.py
│   ├── config.py
│   └── aetherviz/
│       ├── api/              # HTTP schema、route、SSE 事件
│       ├── agents/           # Deep Agents runtime、指令、topic profile、planner、html、repair、model factory
│       ├── tools/            # HTML 提取/清理、parser、JS checker、安全、长度、validation report
│       ├── sandbox/          # run_id 沙箱与产物文件
│       ├── workflow/         # plan contract、plan、revise_plan、approve_plan、generate、edit_html 编排
│       └── schemas/
├── tests/
│   └── test_aetherviz.py
├── pyproject.toml
├── uv.lock
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
PLANNING_OPENAI_MODEL="deepseek-v4-flash"
PLANNING_REASONING_EFFORT="low"
AETHERVIZ_PLAN_MODEL="deepseek-v4-flash"
AETHERVIZ_HTML_MODEL="qwen3.7-plus"
AETHERVIZ_REPAIR_MODEL="qwen3.7-plus"
AETHERVIZ_AGENT_MAX_REPAIR_ATTEMPTS="2"
AETHERVIZ_AGENT_SANDBOX_ROOT=".aetherviz_sandbox"
AETHERVIZ_AGENT_CONTEXT_POLICY="auto"
```

`phase=plan` 和 `phase=revise_plan` 默认使用 `AETHERVIZ_PLAN_MODEL=deepseek-v4-flash`。HTML 生成和修复默认使用 `AETHERVIZ_HTML_MODEL=qwen3.7-plus`、`AETHERVIZ_REPAIR_MODEL=qwen3.7-plus`，并通过 `langchain-openai.ChatOpenAI` 显式接入百炼 OpenAI-compatible endpoint。`AETHERVIZ_AGENT_SANDBOX_ROOT` 控制任务沙箱目录，开发环境默认 `.aetherviz_sandbox`。

如教学方案生成需要单独的百炼业务空间或独立 Key，可额外设置：

```bash
PLANNING_OPENAI_API_KEY="你的教学方案模型 API Key"
PLANNING_OPENAI_BASE_URL="https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
```

`PLANNING_OPENAI_API_KEY` 和 `PLANNING_OPENAI_BASE_URL` 留空时会复用 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。不要把真实 API Key 提交到仓库。

### LangSmith 可观测性

服务基于 LangChain / Deep Agents，可通过 LangSmith 自动采集 planner、html、repair 等 agent 调用链路。在 `.env` 中启用：

```bash
LANGSMITH_TRACING="true"
LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
LANGSMITH_API_KEY="你的 LangSmith API Key"
LANGSMITH_PROJECT="deepagents-v4-html"
```

`LANGSMITH_TRACING=false` 或未配置 `LANGSMITH_API_KEY` 时不会上报 trace。组织级 API Key 如需指定工作区，可额外设置 `LANGSMITH_WORKSPACE_ID`。Trace 会在应用启动时写入进程环境变量，Deep Agents 的 `invoke` 调用会自动出现在 LangSmith 项目面板中。

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

前端是 Vite + React + TypeScript 应用，负责 chat 工作区、计划确认、SSE 事件消费、多个 HTML 产物管理、iframe `srcDoc` 预览和运行时错误桥接。后端负责互动 widget 计划、HTML 生成、HTML 文件编辑、基础语法/安全/长度校验、自动修复和最终自包含 HTML 输出。

职责边界：

- 前端不渲染课件内部 SVG、Canvas 或 DOM 互动逻辑。
- 前端不把后端生成物依赖重新搬回 React 组件。
- 前端只消费后端返回的自包含 HTML，并通过 iframe 隔离预览。
- 前端不向生成物注入 GSAP、D3、KaTeX 或其他运行时依赖；后端返回的 HTML 可自带白名单 GSAP core CDN，并必须包含缺失 GSAP 时的 native fallback。
- 前端按 `phase=plan -> phase=revise_plan -> phase=approve_plan -> phase=generate -> phase=edit_html` 工作；未确认计划时 chat 只修订计划，不触发 HTML 生成。
- `phase=edit_html` 发送修改意见、选中 HTML 文件全文 `current_html` 和摘要型 `context`，用于基于已有 HTML 生成新的 HTML 分支；后端返回 HTML 硬上限为 40000 字符，前端应保留完整返回内容作为后续 `current_html`。

前端联调命令以该前端仓库 `package.json` 为准，常用命令：

```bash
cd /Users/likai/Documents/workspace/bingo-aetherviz
pnpm dev:local
pnpm dev:local:proxy
pnpm build
```

其中 `pnpm dev:local` 通过 `VITE_API_BASE_URL=http://localhost:10095` 直连本后端，`pnpm dev:local:proxy` 通过 Vite proxy 指向本后端。

## API

### POST /bingo-ai/generate-aetherviz-spec

根据教学主题生成 AI互动实验风格的完整独立互动教学 HTML。接口采用同端 SSE，统一走 Deep Agents 工作流，计划类型固定为单页 `interactive`，并通过 `interactive_type` 分流为 `simulation`、`diagram` 或 `game`。

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
    "runtime": {
      "render_stack": "svg_canvas",
      "animation_runtime": "gsap",
      "external_libraries": ["https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"]
    },
    "primary_color": "#22D3EE"
  }
}
```

HTML 文件编辑阶段请求示例：

```json
{
  "phase": "edit_html",
  "message": "把标题改成慢速演示，并把说明文字放到左侧",
  "current_html": "<!DOCTYPE html>...",
  "context": {
    "topic": "熵增演示",
    "selected_file": {
      "id": "html-...",
      "title": "熵增演示",
      "topic": "熵增演示",
      "html_size": 12345,
      "created_at": 1760000000000
    },
    "plan_summary": {
      "title": "熵增演示互动动画",
      "goal": "用分层动画解释熵增的核心过程。",
      "interactive_type": "simulation",
      "widget_actions": [
        {"type": "widget_setState", "state": {"speed": 1.2}},
        {"type": "widget_highlight", "target": "[data-role='main-visual']"}
      ]
    }
  }
}
```

计划修订请求示例：

```json
{
  "topic": "熵增演示",
  "phase": "revise_plan",
  "current_plan": {},
  "message": "改成闯关式，并增加学生预测环节"
}
```

计划确认请求示例：

```json
{
  "phase": "approve_plan",
  "plan": {}
}
```

`phase=edit_html` 必须携带选中的 HTML 文件全文。后端以该文件为修改基线，根据 `message` 生成新的完整 HTML，前端保存为新的时间线分支，不覆盖原文件。后端生成、编辑和修复的 HTML 目标控制在 36000 字符以内，硬上限为 40000 字符；超过硬上限会触发自动修复压缩，修复后仍超限则返回 SSE `error`。

响应类型为 `text/event-stream`。事件包括：

- `plan.started`
- `plan.delta`：规划进度更新；`data` 可含 `delta`（当前步骤文案或推理摘要）、`planning_steps`（步骤清单，含 `content`/`status`）、`active_step_index`
- `plan.ready`
- `plan.revise_started`
- `plan.revised`
- `plan.approved`
- `html.generation_started`
- `html.delta`：HTML 生成进度更新；`data` 可含 `delta`（当前步骤文案）、`html_steps`（步骤清单，含 `content`/`status`）、`active_step_index`
- `html.edit_started`
- `sandbox.written`
- `validation.started`
- `validation.report`
- `repair.started`
- `repair.done`
- `html.done`
- `context.compressed`
- `error`：生成失败，包含用户可读 `message`、错误码 `code` 和调试用 `detail`。

错误约定：

- `400`：`phase=plan` 或 `phase=revise_plan` 时 `topic` 为空。
- `400`：`phase=generate` 时缺少 `approved_plan`。
- `400`：`phase=revise_plan` 时缺少 `current_plan` 或 `message`。
- `400`：`phase=approve_plan` 时缺少 `plan`。
- `400`：`phase=edit_html` 时缺少 `message` 或 `current_html`。
- SSE `error` 且 `code=validation_failed`：HTML 未通过基础文档结构、安全边界、长度上限或内联脚本语法检查，自动修复后仍失败。
- SSE `error` 且 `code=invalid_phase`：请求了不支持的 `phase`。
- SSE `error` 且 `code=runtime_error`：生成过程中发生未预期异常。

`sandbox.written` 事件在 `data` 中返回 `html_path`、`bytes` 和 `chars`；`validation.report` 和修复事件返回结构化 `report`；`html.done` 返回最终 `html`、`metadata` 和 `artifacts` 摘要。

## 生成流程

`/bingo-ai/generate-aetherviz-spec` 使用阶段化生成策略：

1. `phase=plan` 由单次 LLM 规划（默认 `deepseek-v4-flash`，可通过 `PLANNING_REASONING_EFFORT` 开启推理模式）生成完整 `draft` 教案计划。
2. `phase=revise_plan` 由规划模型接收 `current_plan + message`，重新生成完整 `revised` 计划，不返回局部 patch。
3. `phase=approve_plan` 将计划状态置为 `approved`。
4. `phase=generate` 由 `html_agent` 根据已确认计划生成完整自包含 HTML，并写入 run_id 沙箱。
5. `validation_report` 聚合 HTML parser、JS checker、安全检查和长度检查，输出结构化报告并写入沙箱。
6. 检查失败时由 `repair_agent` 使用 `qwen3.7-plus` 自动修复，最多 2 次；工具只产生报告，不直接改写 HTML。
7. `phase=edit_html` 基于选中 HTML 全文生成新的 HTML 分支，不覆盖旧 HTML。
8. 大型 HTML、检查报告和修复草稿写入沙箱；SSE 只返回摘要、最终 HTML 和 `metadata`。

主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色 `#22D3EE`。

## Widget 链路改造方向

本项目采用 Widget 链路级对齐：保留当前 FastAPI 单页 SSE 接口，不迁移外部系统的 Next.js、多场景课堂、LangGraph 或多 Agent 应用架构。

默认改造方向：

- 保留现有公共接口 `POST /bingo-ai/generate-aetherviz-spec`，不新增静态 HTML 接口。
- 计划对象继续以 `page_type: "interactive"` 为主，保留 `interactive_type` 兼容前端；可补充 `widget_type` / `widget_outline`，但不得破坏现有前端字段。
- 后端按 `simulation`、`diagram`、`game` 拆分独立 prompt、分型 widget-config 和开发期分型校验。
- 计划对象必须包含 `scene_outline`、`widget_outline`、`design_brief` 和 `widget_actions`，作为后续 HTML 生成的唯一蓝图。
- 旧版共享模块和兼容层已移除；计划契约在 `workflow/plan_contract.py`，Deep Agents prompt 在 `agents/instructions.py`，HTML 输出边界与确定性检查在 `tools/`。
- 前端可展示 `attempts`、`repaired`、`degraded`、`validation_warnings`、`context_status` 和 `artifacts`。
- 计划中的 action 使用 `widget_setState`、`widget_highlight`、`widget_annotation`、`widget_reveal`；生成物 iframe 内部应兼容 `SET_WIDGET_STATE`、`HIGHLIGHT_ELEMENT`、`ANNOTATE_ELEMENT`、`REVEAL_ELEMENT` 消息。

## 验证

运行 AI互动实验测试：

```bash
uv run pytest tests/test_aetherviz.py
```

运行全量测试：

```bash
uv run pytest
```

curl 示例：

```bash
curl -N -X POST http://localhost:10095/bingo-ai/generate-aetherviz-spec \
  -H "Content-Type: application/json" \
  -d '{"topic":"牛顿第二定律"}'
```
