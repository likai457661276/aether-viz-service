# AI互动实验

`AI互动实验` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

当前生成链路使用 LangChain `ChatOpenAI` 生成动态单页互动课件：先生成可确认的 `interactive` 教案计划，用户可多轮修订计划，确认后再生成 HTML。服务端根据主题生成通用 `knowledge_profile`（学科、概念族、表征类型、教学模式）；普通主题沿用直接 HTML 链路，`geometric_recomposition` 几何切分重排主题只由模型生成纯 JSON 几何 IR（通用图元模板、有限循环、受限表达式、源/目标 transform 和教学帧），模型不再生成 JavaScript。DOM、SVG 注册表、IR 解释器、动画控制器、参数生命周期和 iframe Runtime 全部由服务端脚手架提供。最终页面统一按 `math-shell-v1` 布局契约装配，不为单独知识点维护硬编码模板。HTML 只在请求内存中完成装配、检查和修复，通过 SSE 返回前端渲染与会话缓存；后端不落盘缓存 HTML、修复稿或检查报告。

Docker 镜像内置 Node.js，用于内联 JavaScript `node --check` 和受限 Scene Module 隔离运行冒烟检查，保证 macOS 本地与 Linux 生产容器使用同等级检查；浏览器回归仍只在本地/离线流程运行。

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
AETHERVIZ_HTML_MAX_TOKENS=8192
AETHERVIZ_HTML_STREAM_MAX_RETRIES=1
AETHERVIZ_SCENE_MAX_TOKENS=12288
AETHERVIZ_EDIT_MAX_TOKENS=9216
AETHERVIZ_REPAIR_MAX_TOKENS=9216
```

规划阶段使用 `OPENAI_PLAN_MODEL`，HTML、几何 IR、HTML 编辑和模型修复使用 `OPENAI_HTML_MODEL`。两类模型复用 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`；默认分别为 `deepseek-v4-flash` 和 `qwen3.7-plus`。`AETHERVIZ_PLAN_MAX_TOKENS` 控制计划 JSON 的最大输出 token，默认 3072；`AETHERVIZ_SCENE_MAX_TOKENS` 控制单次 3 候选重排 IR 响应，默认 12288。IR 优先使用严格 JSON Schema 响应约束；兼容网关不支持时自动降级到 JSON object 模式，再由同一服务端契约校验。IR 生成温度固定为 0；服务端执行传输结构归一化、确定性 AST 纠错、schema/白名单检查、default/min/max 语义展开和教学证明约束检查，再编译为固定 Scene Module，补齐 `structureKey`、多阶段 transform 插值和展示帧选择。`AETHERVIZ_GSAP_CDN_URL` 统一配置 GSAP core UMD。KaTeX 仅在计划包含公式时按需加载固定 CSS/JS，且必须提供 `window.katex` 缺失时的纯文本降级。所有 CDN 地址只接受不含凭据、query 或 fragment 的 HTTPS URL；Tailwind、D3、KaTeX auto-render 和其他外部资源不在白名单中。`AETHERVIZ_HTML_MAX_TOKENS`、`AETHERVIZ_EDIT_MAX_TOKENS`、`AETHERVIZ_REPAIR_MAX_TOKENS` 分别控制 HTML 新生成、编辑和模型修复的最大输出 token，默认 8192、9216、9216。`AETHERVIZ_HTML_STREAM_MAX_RETRIES` 控制 HTML 流式传输中断或完整结束标签缺失后的整次重新生成次数，默认 1；重试仍失败时返回明确错误，不输出残缺或降级 HTML。不要把真实 API Key 提交到仓库。

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
4. `phase=generate` 根据 `knowledge_profile.representation_type` 路由：`geometric_recomposition` 由 `recomposition_scene_agent` 一次生成 3 个结构化几何 IR 候选，不生成多个 HTML；服务端淘汰确定性硬校验失败候选，对其余候选按固定权重和稳定指纹排序，只编译最高分 IR 并装配生命周期脚手架。目标拼合已满足连通、重叠和形状约束但仅整体越界时，服务端先对所有目标端点执行保持几何关系的统一平移归位；全部候选仅因中间 transform 证据不足而失败时，再用通用 waypoint 补全器生成有界、偏离首尾直线插值的独立中间状态并重新执行全部硬校验。仍失败才对最接近合格的 IR 做一次受限模型修复。计划声明显式 `target_assembly` 时，候选和修复均失败会明确终止生成，不再用无法证明原主题几何语义的通用 fallback 冒充正确结果。独立证据报告包含阶段、参数状态、piece id、失败原因、端点分离分数、直线路径偏离分数和各维度阈值；其他类型由 `html_agent` 直接生成业务 HTML。
5. 模型业务 HTML 先执行 32000/40000 字符约束，再经过 `math-shell-v1` 服务端装配器；模型外层布局不会进入最终 HTML。装配器会过滤业务 CSS 中的页面级、布局槽位根节点和 range 外观规则，标准 range 由 `range-v1` 独占尺寸与渲染，播放、暂停、重置按钮及 select 由服务端提供统一的按压、状态、焦点反馈，`controller-v1` 在业务脚本执行前提供 GSAP/RAF 共用动画控制接口并广播播放状态。最终装配只执行 64000 字符异常膨胀检查。
6. `validation_report` 聚合布局、HTML、JavaScript、安全、分阶段长度、Widget、动画生命周期和学科一致性检查。动画检查会阻断 timeline/RAF 逐帧回调调用结构性 DOM/SVG 重建函数、可为空的 first/lastChild 清空后直接重挂载，并提示未清理或未经存在性校验的动态节点注册表、局部几何与世界 transform 重复编码，以及 GSAP 直接污染 getState 可序列化业务对象的风险；学科启发式检查仍只产生 warning。
7. 检查失败时先确定性修复业务 HTML。生命周期错误优先使用“报告点名函数 + SHA-256 源哈希”的函数级替换，限制函数数量和总字符数，失败立即回滚；其他硬错误才进入整页修复。截断候选、引入 `js_syntax`/`missing_runtime_ready` 的候选、以及未严格减少硬错误的候选一律拒绝。硬错误修复 prompt 不携带质量 warning，attempt 事件统一单调编号。
8. 生成、编辑和模型修复的候选结果都会重新经过同一个服务端布局装配器，`phase=edit_html` 不能改变布局外壳，只能修改数学内容、业务交互与槽位优先级；编辑候选会继续执行确定性视觉/动画质量收尾，但不会为 warning 额外发起一次完整模型重写。结果仍生成新 HTML 分支，不覆盖旧 HTML。
9. 最终 HTML 仅通过 `html.done` 返回前端；服务端不保留 HTML 文件缓存或产物路径。

生产同步链路不启动浏览器。几何 IR 只允许白名单 state/definition/local 引用、算术与几何操作符、SVG 图元和属性；通用 DSL 包含 `atan/atan2/hypot` 等角度与距离计算，并允许每个稳定图元声明 2~5 个 transform keyframes。计划中的 `recomposition_spec` 会由前后端类型和 approve/generate 请求契约完整传递；其中 `proof_constraints` 描述度量不变量、目标关系、目标拼合约束和教学阶段。每个 `stage_requirement` 由服务端归一化为唯一 `id`、`source/intermediate/target` 角色、确定时间点、几何证据类型和最小图元比例。IR 的教学帧必须用 `stage_id`/`at` 一一覆盖计划阶段；每个中间阶段必须有足够比例图元在同一时间点形成区别于首尾且偏离直接线性插值的几何关键状态，纯文字中间步骤会被阻断。`target_relations` 使用通用结构化关系 `equal_area` / `equal_length` / `equal_angle` / `parallel` / `perpendicular` / `coincident` / `collinear` / `congruent`，通过图元、顶点和线段引用表达；`target_assembly` 使用 `connected` / `non_overlapping` / `approximate_rectangle` 描述世界坐标下的连通性、重叠率、矩形度及参数趋势，不包含知识点分支。服务端会在默认、最小和最大状态展开图元，阻断无效尺寸、非有限值、重复 id、静止端点、源状态明显重叠、源/目标整体越界、缺失中间几何证据、明确违反度量不变量、结构化几何关系或显式目标拼合约束的结果；仅目标拼合整体越界且所有采样状态的联合包围盒可容纳于画布时，允许统一平移目标端点后重新执行完整校验。归一化计划始终保留 `piece_congruence`，因此 repeat 图元的局部几何不得直接或间接依赖 repeat 索引，索引只能用于 id、样式和 transform，防止局部角度与旋转重复编码。修复反馈只携带状态级拼合指标和阶段失败摘要，避免逐拼片诊断挤占模型上下文。未声明 `target_assembly` 时该评分项为 0，不再按满分处理。扇形 `sector_path` 支持确定性轮廓采样和面积计算，其他当前图元或引用不足以计算时产生 warning，且不可计算的显式关系不会获得完整数学评分。编译后的 Scene Module 还会在无 DOM/网络/动态代码能力的 Node `vm` 中执行低成本冒烟检查，检查器会从 IR 自动发现任意计划 state 名称并补齐采样值；真实浏览器布局与行为验证仍由离线流程负责。

### 离线视觉稳定性验证

生成链路会静态检查抽象 SVG viewBox、屏幕像素字号、缩放描边和动画渲染生命周期。结构创建应位于 `buildScene`，逐帧回调只通过 `deriveView/applyView` 更新既有节点；连续动画涉及有界离散拓扑数量时，应在 `buildScene` 按变量上界预分配节点池，逐帧仅切换可见性和属性。显式参数变更导致节点数量变化时需暂停动画、清空注册表并重建 timeline，渲染循环以实际注册表长度为边界或逐项校验节点存在。

开发环境会在 959×900、960×540、1280×720、912×1180 和 390×844 视口运行浏览器回归，覆盖响应式断点两侧及平板尺寸：

```bash
uv run playwright install chromium
uv run python evals/targets/visual.py /path/to/generated.html --report /tmp/visual-report.json
uv run python evals/run_eval.py --repetitions 4 --max-runs 35 --live-model --browser --output-dir /tmp/recomposition-35
```

脚本除视觉布局外，还检查槽位重叠、range 的 44~64px 命中高度和槽位内包含关系、播放后的可见变化、暂停稳定性、参数修改后的完整重置、完成状态与再次播放、重复播放节点数稳定性，并收集页面异常和每个运行时动作的调用异常；单个动作抛错会形成失败报告而不会中断整轮回归。脚本还通过阻断 GSAP CDN 验证 native fallback，且只用于离线验证，不进入生产同步链路。

可从 `langsmith trace get --full --format json --output ...` 的真实导出构建本地单步评估数据集：

```bash
uv run python evals/datasets/build_visual.py /tmp/trace.json --output /tmp/aetherviz-visual-dataset.json
```

`evals/evaluators/visual.py` 提供视觉总通过、舞台可见性、SVG 尺度、动画变化、暂停、重置、参数同步、节点稳定和 GSAP fallback 等单指标确定性 evaluator，仅用于本地或离线回归；Dataset、Evaluator 和经确认的评测报告均可提交到 Git，禁止通过 LangSmith CLI/SDK/API/UI 创建或上传远端 Dataset/Evaluator。

`evals/datasets/recomposition/legacy-topics.jsonl` 保留早期的 4 个开发主题、3 个保留主题和 4 个挑战主题。当前统一入口 `evals/run_eval.py` 分别统计分类、首次候选集中是否存在合格 IR、首次 Scene 契约、一次受限 JSON 修复后的最终契约、教学语义约束、目标拼合约束、完整 HTML 硬校验、通用 fallback 和浏览器 Runtime，并保存每个候选的硬失败、分项得分、稳定指纹、目标拼合指标及排序。LangSmith 子 Run `aetherviz.geometry_ir_ranking` 仅记录脱敏后的候选数量、分数、硬失败、拼合指标、不可计算关系和选择原因，不记录候选 IR 正文。首稿 IR 门槛为 95%，无通用 fallback 门槛为 97%；可用 `--max-runs` 精确限制调用次数。

本地跨维度评估集位于 `evals/datasets/recomposition/`，包含 24 个主题、5 个通用无效 mutation、1 个受控 completion 样本、覆盖矩阵和阈值。受控样本构造仅有目标拼合整体越界的合法候选，硬性要求 `deterministic_target_bounds_completion` 至少尝试一次且成功率为 100%，不依赖真实模型随机触发。主题同时覆盖 piece 数量、平移/旋转/翻转/组合变换、面积/长度/角度/全等、多边形/线段/角/网格、3~5 个阶段、推导难度和参数边界。默认执行 3 次形成 72 次主题回归，并额外执行一次受控 completion：

```bash
uv run python evals/run_eval.py
uv run python evals/run_eval.py --live-model --browser
```

确定性 evaluator 检查 Dataset 矩阵、分类、Geometry IR/Scene/HTML 契约、数学不变量、教学阶段、无效案例检测和受控 completion；`piece_count` 与主要变换的主题意图对齐作为诊断项单独汇总，避免把启发式语义当作生产硬裁决。真实模型回归的 summary 额外统计 `raw_candidate`、`deterministic_target_bounds_completion`、`deterministic_waypoint_completion` 策略次数，以及确定性候选修复的尝试与成功数。结果默认写入并可提交到 `evals/reports/latest/`。脚本不实例化 LangSmith Client，也不调用 Dataset/Evaluator 远端 API；真实模型与浏览器仅在显式传入参数时运行。模块职责与更多命令见 `evals/README.md`。

完整 72～90 次真实模型回归可用 `--workers 2`～`--workers 4` 启用有界并发；默认值仍为 `1`。并发只缩短本地生成耗时，报告按 Dataset 与 repetition 的固定顺序汇总，不改变生产请求链路。

第六阶段完整本地回归使用 24 个主题、3 次 repetition，并将确定性基线与真实模型结果分目录保留。真实模型批量运行示例：

```bash
uv run python evals/run_eval.py \
  --repetitions 3 --live-model --browser --workers 3 \
  --output-dir evals/reports/stage6/current
uv run python evals/reporting/regression.py \
  --baseline evals/reports/stage6/deterministic/latest-summary.json \
  --current evals/reports/stage6/current/latest-summary.json \
  --failures evals/reports/stage6/current/failures.jsonl \
  --output evals/reports/stage6/regression-report.json
```

`regression-report.json` 汇总公共指标差异、真实模型专属指标、候选硬失败以及失败主题/维度。确定性脚手架与真实模型属于不同运行模式，公共指标可比较；没有历史真实模型报告时，首稿 IR、候选排序和 fallback 不能解释为代码版本升降。

主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色 `#22D3EE`。

## Widget 链路改造方向

本项目采用 Widget 链路级对齐：保留当前 FastAPI 单页 SSE 接口，不迁移外部系统的 Next.js、多场景课堂、LangGraph 或多 Agent 应用架构。

默认改造方向：

- 保留现有公共接口 `POST /bingo-ai/generate-aetherviz-spec`，不新增静态 HTML 接口。
- 计划对象继续以 `page_type: "interactive"` 为主，保留 `interactive_type` 兼容前端；可补充 `widget_type` / `widget_outline`，但不得破坏现有前端字段。
- 后端按 `simulation`、`diagram`、`game` 拆分独立 prompt、分型 widget-config 和开发期分型校验。
- 计划对象必须包含 `scene_outline`、`widget_outline`、`design_brief`、`widget_actions`、`knowledge_profile` 和 `discipline_spec`，作为后续 HTML 生成的唯一蓝图。知识画像只路由到通用概念族、表征和教学模式，不包含具体知识点专用模板。
- 旧版共享模块和兼容层已移除；学科与互动类型选择在 `workflow/plan_detection.py`，计划规范化在 `workflow/plan_contract.py`，直接模型 prompt 在 `agents/instructions.py`，确定性修复在 `tools/deterministic_repair.py`。
- `html.done.metadata.generation_backend` 为 `direct` 或 `recomposition_scene`；API/SSE 主结构不变，前端未声明 `representation_type` 固定枚举，无需同步类型迁移。
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
