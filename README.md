# AI互动实验

`AI互动实验` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

当前生成链路使用 LangChain `ChatOpenAI` 生成动态单页互动课件：先生成可确认的 `interactive` 教案计划，用户可多轮修订计划，确认后模型生成数学主视觉、业务控件、公式、旁白、教学流程和运行时。服务端随后按版本化 `math-shell-v1` 布局契约确定性重建页面骨架、响应式断点、区域顺序和滚动归属，模型不再创作最终页面布局。服务端根据主题生成通用 `knowledge_profile`（学科、概念族、表征类型、教学模式），再组合互动类型、学科组和表征提示词；计划通过 `discipline_spec` 描述对象、关系、不变量、边界情况和多重表征，不为单独知识点维护硬编码模板。HTML 只在请求内存中完成装配、检查和修复，通过 SSE 返回前端渲染与会话缓存；后端不落盘缓存 HTML、修复稿或检查报告。

Docker 镜像内置 Node.js，仅用于对生成物的内联 JavaScript 执行 `node --check` 语法校验，保证 macOS 本地与 Linux 生产容器使用同等级检查。

## 目录结构

```text
aether-viz-service/
├── aetherviz_service/
│   ├── main.py
│   ├── config.py
│   └── aetherviz/
│       ├── api/              # HTTP schema、route、SSE 事件
│       ├── agents/           # 模型调用、指令、topic profile、planner、html、repair、model factory
│       ├── tools/            # HTML 提取/清理、parser、JS checker、安全、长度、validation report
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
OPENAI_PLAN_MODEL="deepseek-v4-flash"
OPENAI_HTML_MODEL="qwen3.7-plus"
AETHERVIZ_PLAN_MAX_TOKENS=3072
AETHERVIZ_GSAP_CDN_URL="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"
AETHERVIZ_KATEX_ENABLED=true
AETHERVIZ_KATEX_CSS_URL="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css"
AETHERVIZ_KATEX_JS_URL="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"
AETHERVIZ_HTML_MAX_TOKENS=12288
```

规划阶段使用 `OPENAI_PLAN_MODEL`，HTML 生成、HTML 编辑和模型修复使用 `OPENAI_HTML_MODEL`。两类模型复用 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`；默认分别为 `deepseek-v4-flash` 和 `qwen3.7-plus`。`AETHERVIZ_PLAN_MAX_TOKENS` 控制计划 JSON 的最大输出 token，默认 3072；规划阶段固定关闭深度思考并启用 JSON Mode，以降低延迟和格式漂移。`AETHERVIZ_GSAP_CDN_URL` 统一配置 GSAP core UMD。KaTeX 仅在计划包含公式时按需加载固定 CSS/JS，且必须提供 `window.katex` 缺失时的纯文本降级。所有 CDN 地址只接受不含凭据、query 或 fragment 的 HTTPS URL；Tailwind、D3、KaTeX auto-render 和其他外部资源不在白名单中。`AETHERVIZ_HTML_MAX_TOKENS` 控制 HTML 生成、编辑和模型修复的最大输出 token，默认 12288。阶段级温度、超时及重试策略由服务内置默认值控制；HTML 直出默认关闭推理，避免增加耗时和截断概率。不要把真实 API Key 提交到仓库。

### LangSmith 可观测性

服务基于 LangChain，可通过 LangSmith 自动采集 planner、html、repair 等模型调用链路。在 `.env` 中启用：

```bash
LANGSMITH_TRACING="true"
LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
LANGSMITH_API_KEY="你的 LangSmith API Key"
LANGSMITH_PROJECT="aetherviz-direct-html"
```

`LANGSMITH_TRACING=false` 或未配置 `LANGSMITH_API_KEY` 时不会上报 trace。组织级 API Key 如需指定工作区，可额外设置 `LANGSMITH_WORKSPACE_ID`。每个 API phase 以 `aetherviz.request` 作为根 trace，HTML 生成、确定性校验、确定性修复、模型修复和最终校验作为子 run；metadata 记录业务 `run_id`、phase、互动类型、错误/警告类型、修复是否接受、耗时及最终大小。启用追踪时，每个 SSE 事件会额外返回真实的 `langsmith_trace_id`，供前端复制并定位完整调用树。工作流 trace 只保存摘要，不重复保存完整 SSE HTML；模型子 run 仍由 LangChain 自动采集。

## 启动服务

本地直接启动：

```bash
uv run uvicorn aetherviz_service.main:app --port 10095
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
- 前端不向生成物注入 GSAP、KaTeX 或其他运行时依赖；后端返回的 HTML 可自带白名单 GSAP core CDN，并在公式非空时自带固定版本 KaTeX CSS/JS。GSAP 必须有 native fallback，KaTeX 必须有纯文本 fallback。
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

根据教学主题生成 AI互动实验风格的完整独立互动教学 HTML。接口采用同端 SSE 和确定性工作流，计划类型固定为单页 `interactive`，并通过 `interactive_type` 分流为 `simulation`、`diagram` 或 `game`。

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
      {"id": "play-animation", "label": "播放", "type": "button", "action": "play"},
      {"id": "pause-animation", "label": "暂停", "type": "button", "action": "pause"},
      {"id": "reset-animation", "label": "重置", "type": "button", "action": "reset"}
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

`phase=edit_html` 必须携带选中的 HTML 文件全文。后端以该文件为修改基线，根据 `message` 生成新的完整 HTML，前端保存为新的时间线分支，不覆盖原文件。模型生成、编辑和修复的业务 HTML 目标为 32000 字符、硬上限为 40000 字符，用于控制模型耗时、上下文和代码复杂度；服务端布局骨架、控件契约和运行时 guard 的确定性装配开销不计入模型上限。最终装配 HTML 仅受 64000 字符异常膨胀安全上限约束。模型原始输出缺少 `</html>` 时会标记为截断并强制进入一次模型修复，不会把自动闭合结果静默当成正常页面。

响应类型为 `text/event-stream`。事件包括：

- `plan.started`
- `plan.delta`：规划进度更新；`data` 可含 `delta`（当前步骤文案或推理摘要）、`planning_steps`（步骤清单，含 `content`/`status`）、`active_step_index`
- `plan.ready`
- `plan.revise_started`
- `plan.revised`
- `plan.approved`
- `html.generation_started`
- `html.delta`：HTML 生成进度与实时大小更新；`data` 可含 `delta`、`html_steps`、`active_step_index`、累计 `bytes` 和 `chars`
- `html.edit_started`
- `validation.started`
- `validation.report`
- `repair.started`
- `repair.done`：修复结束状态，`data` 同时返回修复后最终 `bytes` 和 `chars`
- `html.done`：返回完整 HTML；metadata 额外包含最终 `bytes`、`chars`、`model_chars`、`assembled_chars`、`assembly_overhead_chars`、`assembly_count` 和 `truncated`
- `context.compressed`：仅在传入规划上下文确实超过上限并被裁剪时发送
- `error`：生成失败，包含用户可读 `message`、错误码 `code` 和调试用 `detail`。

错误约定：

- `400`：`phase=plan` 或 `phase=revise_plan` 时 `topic` 为空。
- `400`：`phase=generate` 时缺少 `approved_plan`，或计划缺少 `interactive_type`、`subject`、`title`、`goal`。
- `400`：`phase=revise_plan` 时缺少 `current_plan`、计划必要字段或 `message`。
- `400`：`phase=approve_plan` 时缺少 `plan` 或计划必要字段。
- `400`：`phase=edit_html` 时缺少 `message` 或 `current_html`。
- SSE `error` 且 `code=validation_failed`：HTML 未通过基础文档结构、安全边界、长度上限或内联脚本语法检查，自动修复后仍失败。
- SSE `error` 且 `code=invalid_phase`：请求了不支持的 `phase`。
- SSE `error` 且 `code=runtime_error`：生成过程中发生未预期异常。

`validation.report` 和修复事件返回结构化 `report`；`html.done` 返回最终完整 `html`，其 `metadata.bytes/chars` 为最终实际大小。前端应持有 HTML、渲染 iframe，并负责会话内缓存。

## 生成流程

`/bingo-ai/generate-aetherviz-spec` 使用阶段化生成策略：

1. `phase=plan` 由统一配置的模型执行单次规划，生成完整 `draft` 教案计划。
2. `phase=revise_plan` 由规划模型接收 `current_plan + message`，重新生成完整 `revised` 计划，不返回局部 patch。
3. `phase=approve_plan` 将计划状态置为 `approved`。
4. `phase=generate` 由 `html_agent` 根据已确认计划生成完整自包含 HTML，并在 `html.delta` 中持续返回累计实际大小。
5. 模型业务 HTML 先执行 32000/40000 字符约束，再经过 `math-shell-v1` 服务端装配器；模型外层布局不会进入最终 HTML。标准 range 由 `range-v1` 接管，`controller-v1` 提供 GSAP/RAF 共用动画控制接口。最终装配只执行 64000 字符异常膨胀检查。
6. `validation_report` 聚合布局、HTML、JavaScript、安全、分阶段长度、Widget、动画生命周期和学科一致性检查。动画检查会阻断 timeline/RAF 逐帧回调调用结构性 DOM/SVG 重建函数，并提示未清理的节点注册表；学科启发式检查仍只产生 warning。
7. 检查失败时先确定性修复业务 HTML；仍失败时由 `repair_agent` 使用未装配的业务 HTML 定向修复，最多 1 次。错误签名不变时恢复修复前版本并停止；硬错误修复成功后直接交付，不再追加完整质量模型重写。
8. 生成、编辑和模型修复的候选结果都会重新经过同一个服务端布局装配器，`phase=edit_html` 不能改变布局外壳，只能修改数学内容、业务交互与槽位优先级；结果仍生成新 HTML 分支，不覆盖旧 HTML。
9. 最终 HTML 仅通过 `html.done` 返回前端；服务端不保留 HTML 文件缓存或产物路径。

生产同步链路不启动服务端浏览器。真实运行时错误由前端 iframe bridge 捕获，用户可发起一次定向 `phase=edit_html` 修复并生成新分支。

### 离线视觉稳定性验证

生成链路会静态检查抽象 SVG viewBox、屏幕像素字号、缩放描边和动画渲染生命周期。结构创建应位于 `buildScene`，逐帧回调只通过 `deriveView/applyView` 更新既有节点；节点数量变化时需清空注册表并重建 timeline。

开发环境可在 960×540、1280×720 和 390×844 三种视口运行浏览器回归：

```bash
uv run playwright install chromium
uv run python scripts/visual_regression.py /path/to/generated.html --report /tmp/visual-report.json
```

脚本除视觉布局外，还检查播放后的可见变化、暂停稳定性、重置一致性、参数与视觉同步、重复播放节点数稳定性，并通过阻断 GSAP CDN 验证 native fallback。该脚本只用于离线验证，不进入生产同步链路。

可从 `langsmith trace get --full --format json --output ...` 的真实导出构建本地单步评估数据集：

```bash
uv run python scripts/build_visual_dataset.py /tmp/trace.json --output /tmp/aetherviz-visual-dataset.json
```

`scripts/langsmith_visual_evaluators.py` 提供视觉总通过、舞台可见性、SVG 尺度、动画变化、暂停、重置、参数同步、节点稳定和 GSAP fallback 等单指标确定性 evaluator，可用于 LangSmith 本地实验或按需上传；脚本默认不修改远端数据集和 evaluator。

主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色 `#22D3EE`。

## Widget 链路改造方向

本项目采用 Widget 链路级对齐：保留当前 FastAPI 单页 SSE 接口，不迁移外部系统的 Next.js、多场景课堂、LangGraph 或多 Agent 应用架构。

默认改造方向：

- 保留现有公共接口 `POST /bingo-ai/generate-aetherviz-spec`，不新增静态 HTML 接口。
- 计划对象继续以 `page_type: "interactive"` 为主，保留 `interactive_type` 兼容前端；可补充 `widget_type` / `widget_outline`，但不得破坏现有前端字段。
- 后端按 `simulation`、`diagram`、`game` 拆分独立 prompt、分型 widget-config 和开发期分型校验。
- 计划对象必须包含 `scene_outline`、`widget_outline`、`design_brief`、`widget_actions`、`knowledge_profile` 和 `discipline_spec`，作为后续 HTML 生成的唯一蓝图。知识画像只路由到通用概念族、表征和教学模式，不包含具体知识点专用模板。
- 旧版共享模块和兼容层已移除；学科与互动类型选择在 `workflow/plan_detection.py`，计划规范化在 `workflow/plan_contract.py`，直接模型 prompt 在 `agents/instructions.py`，确定性修复在 `tools/deterministic_repair.py`。
- `html.done.metadata.generation_backend` 当前固定为 `direct`，用于前端和观测系统识别直接模型链路。
- 前端可展示 `attempts`、`repaired`、`degraded`、`validation_warnings`、`context_status`、`bytes` 和 `chars`。
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

运行 Python 静态检查：

```bash
uv run ruff check .
```

安全自动修复可使用 `uv run ruff check . --fix`；暂不对全仓库执行批量格式化，避免改写提示词和内嵌 HTML/JS。

curl 示例：

```bash
curl -N -X POST http://localhost:10095/bingo-ai/generate-aetherviz-spec \
  -H "Content-Type: application/json" \
  -d '{"topic":"牛顿第二定律"}'
```
