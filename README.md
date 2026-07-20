# AI教学动画

`AI教学动画` 是一个基于 Python 3.12 和 FastAPI 的后端服务，用于根据教学主题生成完整、可直接打开的互动教学 HTML。

当前生成链路只交付经过确定性契约验证的 IR 场景：先生成可确认的 `interactive` 教案计划，再根据 `representation_spec` 的视图、状态、对应关系、不变量和交互能力路由到一个已注册 IR 后端。模型只生成受限 JSON IR，SVG/DOM、坐标映射、交互和动画生命周期由服务端 Runtime 编译。没有 IR 满足计划能力时返回 `unsupported_ir_capability`；IR 候选及一次受限修复仍不合格时返回 `ir_generation_failed`。初始生成不再调用通用 direct HTML，也不会把结构合法但教学或视觉不可验证的页面作为成功结果。

最终页面统一按 `math-shell-v1` 布局契约装配。HTML 只在请求内存中完成装配、检查和必要修复，通过 SSE 返回前端渲染与会话缓存；后端不落盘缓存 HTML、修复稿或检查报告。

## IR 覆盖范围

IR 覆盖按“可验证表征能力”计算，不按教材目录中的知识点标题计数。同一个 IR 可覆盖不同年级、教材和命名下的大量知识点；只有示例标题相同但所需交互或不变量超出契约时，也不会被视为已覆盖。当前共有 **10 个生产 IR 家族**：

| IR 后端 | 已验证能力 | 代表性知识点/场景 | 明确边界 |
| --- | --- | --- | --- |
| `recomposition_scene` | 稳定拼片、面积/长度/角度守恒、多阶段重排、逐片拖拽、目标吸附、参数预设、渐进揭示 | 勾股定理割补证明、圆面积推导、三角形/平行四边形/梯形面积割补、等积变换 | 不做连续 path morph、自由绘图或未经目标拼合校验的近似动画 |
| `linked_coordinate_scene` | 多坐标视图共享参数、动态点、轨迹、投影和跨视图对应 | 单位圆与正弦曲线、旋转向量投影、参数曲线的多视图联动 | 不做无共享参数的独立图表或任意三维场景 |
| `coordinate_graph_scene` | 单坐标系完整曲线、动态点、辅助投影、稳定定义域揭示 | 一次/二次函数、三角函数、指数/对数函数、参数曲线、点在曲线上运动 | 不做多坐标系联动、隐式通用求解或自由绘图 |
| `parametric_geometry_scene` | 离散边数驱动的圆内接/外切正多边形、周长和误差收敛 | 正多边形逼近圆、圆周率近似、内外接周长收敛 | 仅离散正多边形，不做连续欧氏构造或割补重排 |
| `number_line_scene` | 点、开闭区间、射线、并交集、绝对距离、有向位移 | 不等式解集、区间运算、绝对值、数轴位移 | 仅一维有序尺度，不做二维函数或统计图 |
| `constraint_geometry_scene` | 点线圆角、受约束拖拽、轨迹及欧氏不变量验证 | 平行/垂直、等长、中点、共线、点在圆上、切线、等角、互补 | 不是通用非线性约束求解器，不做拼片重排 |
| `data_distribution_scene` | 固定样本身份、表格与六类图表、确定性统计量 | 柱状/折线/散点/直方/箱线图，均值、中位数、方差、标准差、四分位数、线性回归 | 不做连续密度面积、重复抽样或随机累计试验 |
| `symbolic_derivation_scene` | 受限多项式 AST、逐步等价性和方程常数倍校验 | 展开、因式分解、交换结合、分配律、线性方程等价变形 | 不支持不等式、超越方程、根式有理化和数值近似证明 |
| `probability_experiment_scene` | 有限样本空间、事件、固定种子、累计频率和概率树 | 骰子/硬币试验、事件概率、频率趋近、有限概率树 | 不支持连续分布、无限样本空间、马尔可夫链和贝叶斯网络 |
| `discrete_structure_scene` | 稳定节点/边/成员身份、图树集合序列和阶段揭示 | 图与树、集合关系、有限序列、排列过程 | 不执行最短路/最大流等算法，不提供自由图编辑 |

这张表是生产能力白名单，不是“模型可能生成”的范围。新增知识点前应先判断它是否能完整映射到表中的状态、实体、关系、不变量和交互；不能完整映射时应新增或扩展 IR，并补充契约与回归数据，而不是放宽为自由 HTML。

新增 `parametric_geometry_scene` 后端覆盖离散参数驱动的圆/正多边形构造、边界测量和误差收敛。它按最大边数一次预分配 SVG 节点，播放期只更新属性和可见性，固定 viewBox 按最坏外切包络预留，并统一复用服务端动画控制器；不用于割补重排或连续自由拖拽构造。

`number_line_scene` 后端覆盖一维有序尺度上的动态点、开闭端点、区间、集合并交、不等式射线、绝对距离和有向位移。`number-line-ir.v1.1` 使用受限状态表达式，并用 `derived_sets` 引用两个输入区间；Runtime 逐帧确定性求出空集、单点、单区间或双区间，模型不生成静态集合结果。服务端同时验证对象位于固定 domain、输入区间始终有序，多变量动画必须用关键帧覆盖全部状态；该后端不用于二维函数曲线、连续几何约束或统计分布图。

`constraint_geometry_scene` 后端覆盖连续参数驱动的欧氏几何构造。`constraint-geometry-ir.v1.1` 允许模型描述点、线段、圆、角、受限数学表达式和约束关系；服务端在参数上下界及内部采样状态验证共线、平行、垂直、等长、中点、重合、点在圆上、切线、等角和互补等不变量，再使用等比例数学坐标映射编译固定 SVG Runtime。点可将一个计划状态绑定为横向、纵向、圆周角或线段投影参数拖拽；轨迹使用单一 SVG path 和最多 800 个采样点的固定容量缓冲区，不在播放期创建图元。该能力不等同于通用非线性约束求解器。只有计划明确声明 `geometric_scene`、可调状态和可验证几何约束时才会路由到该后端；缺少结构化表征或必要约束时明确返回不支持。

`data_distribution_scene` 后端覆盖固定样本身份下的表格、柱状图、折线图、散点图、直方图和箱线图。`data-distribution-ir.v1` 只允许模型声明原始字段、数据行、图表映射和统计量类型；服务端在计划变量边界验证数值表达式，并统一计算分箱、均值、中位数、总体/样本方差、标准差、四分位数、IQR 和一元线性回归。所有表征共享同一数据源，直方图限制为最多 80 箱。首版不覆盖随机试验累计、重复抽样、参数化离散分布或连续密度面积；这些计划明确返回不支持。

`symbolic_derivation_scene` 使用 `symbolic-derivation-ir.v1` 的受限多项式 AST 表示表达式和方程。服务端将每一步规范化为精确有理系数多项式：表达式变换必须恒等，方程变换的左右差式允许相差非零常数倍；步骤必须连续，乘除规则必须声明非零常数。首版覆盖展开、因式分解、交换结合、分配律和常数倍方程变换，不覆盖不等式、超越方程、根式有理化和数值近似证明。

`probability_experiment_scene` 使用 `probability-experiment-ir.v1` 描述有限互斥样本点、正权重、事件集合、固定种子及样本空间、累计频率、概率树视图。服务端统一归一化理论概率，并由同一确定性随机序列驱动全部读数和图表。首版不覆盖连续分布、无限样本空间、马尔可夫链和贝叶斯网络。

`discrete_structure_scene` 使用 `discrete-structure-ir.v1` 描述稳定节点 id、边拓扑、集合成员、有限序列和阶段可见区间。服务端验证引用完整性、节点顺序唯一性和树视图的单根无环约束，并统一布局图、树、集合、序列和排列视图。首版不执行最短路、最大流等图算法，也不提供自由图编辑。

Docker 镜像内置 Node.js，用于内联 JavaScript `node --check` 和受限 Scene Module 隔离运行冒烟检查，保证 macOS 本地与 Linux 生产容器使用同等级检查；浏览器回归仍只在本地/离线流程运行。

## 目录结构

```text
aether-viz-service/
├── aetherviz_service/
│   ├── main.py
│   ├── config.py
│   └── aetherviz/
│       ├── api/              # HTTP schema、route、SSE 事件
│       ├── agents/           # planner、runtime 分发、model factory（兼容 shim 保留）
│       ├── generate/         # 初始生成线：plan→IR 路由→确定性 Runtime 装配
│       ├── edit/             # 后期编辑线：诊断、策略路由、确定性/局部补丁、intent 验收、workflow（不以 plan 为基线）
│       ├── contracts/        # 平台契约：layout 装配、validation、repair、delivery pipeline
│       ├── ir/               # IR 注册表；每个 IR 家族独立拥有契约、Agent、编译器和 Runtime
│       │   ├── recomposition/      # 几何切分重排 IR
│       │   ├── linked_coordinate/  # 联动坐标/动态数学场景 IR
│       │   ├── coordinate_graph/   # 单视图函数与坐标图 IR
│       │   ├── parametric_geometry/ # 离散参数几何与收敛 IR
│       │   ├── number_line/         # 数轴、区间与集合运算 IR
│       │   ├── constraint_geometry/    # 连续欧氏约束几何 IR
│       │   ├── data_distribution/      # 数据图表与确定性统计 IR
│       │   ├── symbolic_derivation/    # 可验证符号推导 IR
│       │   ├── probability_experiment/ # 有限随机试验 IR
│       │   └── discrete_structure/     # 图、树、集合与序列 IR
│       ├── tools/            # 共享底层工具（function_patch、security_policy、javascript_syntax 等）
│       ├── workflow/         # 仅 plan 相关：plan / revise_plan / approve_plan
│       └── schemas/
├── tests/
├── pyproject.toml
├── uv.lock
├── Dockerfile
├── docker-compose.dev.yml
└── docker-compose.prod.yml
```

Python 包名为 `aetherviz_service`，服务标题为 `AI教学动画`。

生成线与编辑线物理隔离：`generate` 与 `edit` 互不 import；双方只依赖 `contracts` 做装配、校验与修复。初始生成的结构化提示由各 IR 子包独立维护；编辑以当前业务 HTML 为唯一事实基线，不注入 IR 生成说明。

IR 扩展遵循固定边界：`ir/registry.py` 负责后端唯一注册和能力评估入口，`ir/router/` 负责确定性排序、低置信度模型仲裁和回退；每个 IR 子包自行拥有 `routing.py`、模型提示、JSON Schema、解析与确定性语义校验、编译器和服务端 Runtime。新增 IR 时注册一个带 `routing_profile` 和 `assess(plan)` 的 `IRBackend` 即可，不在生成工作流继续添加类型条件。几何重排实现和唯一导入边界完整归属 `ir/recomposition/`，不再通过 `agents/` 或 `tools/` 暴露旧入口。

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
OPENAI_ROUTER_MODEL="deepseek-v4-flash"
OPENAI_EDIT_ANALYSIS_MODEL="deepseek-v4-flash"
OPENAI_HTML_MODEL="qwen3.7-plus"
OPENAI_REPAIR_MODEL="deepseek-v4-flash"
AETHERVIZ_IR_ROUTER_ENABLED=true
AETHERVIZ_IR_ROUTER_SHADOW_MODE=true
AETHERVIZ_IR_ROUTER_MAX_TOKENS=768
AETHERVIZ_IR_ROUTER_TIMEOUT_SECONDS=20
AETHERVIZ_IR_ROUTER_MAX_RETRIES=1
AETHERVIZ_IR_ROUTER_CONFIDENCE_THRESHOLD=0.70
AETHERVIZ_IR_ROUTER_DETERMINISTIC_THRESHOLD=0.80
AETHERVIZ_IR_ROUTER_MIN_MARGIN=0.20
AETHERVIZ_PLAN_MAX_TOKENS=3072
AETHERVIZ_GSAP_CDN_URL="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"
AETHERVIZ_KATEX_ENABLED=true
AETHERVIZ_KATEX_CSS_URL="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css"
AETHERVIZ_KATEX_JS_URL="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"
AETHERVIZ_HTML_MAX_TOKENS=16384
AETHERVIZ_HTML_STREAM_MAX_RETRIES=1
AETHERVIZ_SCENE_MAX_TOKENS=12288
AETHERVIZ_EDIT_MAX_TOKENS=16384
AETHERVIZ_EDIT_ENABLE_THINKING=true
AETHERVIZ_EDIT_REASONING_EFFORT=
AETHERVIZ_EDIT_TEMPERATURE=0.15
AETHERVIZ_EDIT_ANALYSIS_MAX_TOKENS=2048
AETHERVIZ_EDIT_ANALYSIS_TIMEOUT_SECONDS=30
AETHERVIZ_EDIT_MAX_RETRIES=1
AETHERVIZ_REPAIR_MAX_TOKENS=16384
```

规划阶段使用 `OPENAI_PLAN_MODEL`，HTML、几何 IR 和整页 HTML 编辑使用 `OPENAI_HTML_MODEL`，编辑诊断使用 `OPENAI_EDIT_ANALYSIS_MODEL`，函数级修复与整页模型修复使用 `OPENAI_REPAIR_MODEL`。这些模型复用 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`；未配置 Key 时 HTML 生成与编辑会明确返回 `model_unavailable`，不会交付确定性占位页。编辑诊断默认使用 `deepseek-v4-flash`，温度为 0、关闭 thinking，优先使用严格 JSON Schema，兼容网关不支持时重试 JSON object 模式；`AETHERVIZ_EDIT_ANALYSIS_MAX_TOKENS` 与 `AETHERVIZ_EDIT_ANALYSIS_TIMEOUT_SECONDS` 分别控制短诊断 JSON 的输出预算和独立超时。`AETHERVIZ_PLAN_MAX_TOKENS` 控制计划 JSON 的最大输出 token，默认 3072；`AETHERVIZ_SCENE_MAX_TOKENS` 控制单次 3 候选重排 IR 响应，默认 12288。IR 优先使用严格 JSON Schema 响应约束；兼容网关不支持时自动降级到 JSON object 模式，再由同一服务端契约校验。IR 生成温度固定为 0；服务端执行传输结构归一化、确定性 AST 纠错、schema/白名单检查、default/min/max 语义展开和教学证明约束检查，再编译为固定 Scene Module，补齐 `structureKey`、多阶段 transform 插值和展示帧选择。HTML 编辑通过 `AETHERVIZ_EDIT_ENABLE_THINKING` 独立启用推理模式，默认开启且不影响新 HTML 生成、几何 IR 和修复；`AETHERVIZ_EDIT_REASONING_EFFORT` 可选配置推理强度，留空时使用模型默认值。`AETHERVIZ_GSAP_CDN_URL` 统一配置 GSAP core UMD。KaTeX 仅在计划包含公式时按需加载固定 CSS/JS，且必须提供 `window.katex` 缺失时的纯文本降级。所有 CDN 地址只接受不含凭据、query 或 fragment 的 HTTPS URL；协议相对 URL、`data:` URL、非 HTTPS 外链、Tailwind、D3、KaTeX auto-render 和其他外部资源不在白名单中。`AETHERVIZ_HTML_MAX_TOKENS`、`AETHERVIZ_EDIT_MAX_TOKENS`、`AETHERVIZ_REPAIR_MAX_TOKENS` 分别控制 HTML 新生成、基于当前 HTML 的整页重生成和模型修复的最大输出 token，默认均为 16384；启动时会校验三项预算能够覆盖业务 HTML 硬上限与收尾余量。`AETHERVIZ_MAX_REPAIR_ATTEMPTS` 控制整页模型修复次数，默认 1，可设为 0 关闭或设为更大的非负整数；`AETHERVIZ_HTML_STREAM_MAX_RETRIES` 控制 HTML 流式传输中断或完整结束标签缺失后的整次重新生成次数，默认 1。重试仍失败时返回明确错误，不输出残缺或降级 HTML。不要把真实 API Key 提交到仓库。

KaTeX 可见公式使用 `data-katex` 显式目标并直接调用 `katex.render`；裸露的 `$...$`/`$$...$$` 会被确定性转换，转换后仍残留时按硬错误阻断。动态创建的 SVG/Canvas/DOM 节点必须先完成场景构建，再绑定节点事件和首次渲染；初始化前访问动态节点同样按硬错误阻断。

`AETHERVIZ_EDIT_TEMPERATURE` 只控制完整 HTML 编辑模型，默认 `0.15`；需求编译、IR 路由、Scene IR 和修复模型仍保持 `0`，避免结构化判断与确定性修复产生随机漂移。`0.15` 用于适度提高动画重设计和跨链路改造能力；是否继续提高到 `0.2` 应以真实模型编辑成功率、无关区域变化率和校验失败率的离线 A/B 结果决定。

`OPENAI_ROUTER_MODEL` 只用于模糊 IR 路由的短 JSON 仲裁；`AETHERVIZ_IR_ROUTER_SHADOW_MODE=true` 时记录仲裁结论但仍执行确定性首选，完成离线回归后可关闭 Shadow。路由模型超时、格式错误、未知后端、低置信度或命中硬排除条件时均回退到最高分的合格确定性 IR；没有合格 IR 时返回 `unsupported_ir_capability`。

### LangSmith 可观测性

服务基于 LangChain，可通过 LangSmith 自动采集 planner、html、repair 等模型调用链路。在 `.env` 中启用：

```bash
LANGSMITH_TRACING="true"
LANGSMITH_ENDPOINT="https://api.smith.langchain.com"
LANGSMITH_API_KEY="你的 LangSmith API Key"
LANGSMITH_PROJECT="aetherviz-ir-html"
```

`LANGSMITH_TRACING=false` 或未配置 `LANGSMITH_API_KEY` 时不会上报 trace。组织级 API Key 如需指定工作区，可额外设置 `LANGSMITH_WORKSPACE_ID`。每个 API phase 以 `aetherviz.request` 作为根 trace；计划生成会记录 `aetherviz.plan_generation` 子 run 及规范化计划，HTML 生成、整页编辑重生成、确定性校验、确定性修复、模型修复和最终校验也分别作为子 run。metadata 记录业务 `run_id`、phase、编辑策略、互动类型、错误/警告类型、修复是否接受、耗时、最终大小以及独立的 `generation_attempts` / `repair_attempts` 计数，兼容字段 `attempts` 仍表示两者之和。启用追踪时，每个 SSE 事件会额外返回真实的 `langsmith_trace_id`，供前端复制并定位完整调用树。工作流 trace 只保存摘要，不重复保存完整 SSE HTML；模型子 run 仍由 LangChain 自动采集。

## 启动服务

本地直接启动：

```bash
uv run uvicorn aetherviz_service.main:app --port 10099
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
- **教学方案（plan）仅在点击生成 HTML 之前可修订**；一旦发起生成，前端不再把 plan 作为可引用上下文，后续消息走 `edit_html`。
- `phase=edit_html` 发送修改意见、选中 HTML 文件全文 `current_html` 和摘要型 `context`（**不含 `plan_summary`**），用于基于已有 HTML 生成新的 HTML 分支；后端返回 HTML 硬上限为 42000 字符，前端应保留完整返回内容作为后续 `current_html`。

前端联调命令以该前端仓库 `package.json` 为准，常用命令：

```bash
cd /Users/likai/Documents/workspace/bingo-aetherviz
pnpm dev:local
pnpm dev:local:proxy
pnpm build
```

其中 `pnpm dev:local` 通过 `VITE_API_BASE_URL=http://localhost:10099` 直连本后端，`pnpm dev:local:proxy` 通过 Vite proxy 指向本后端。

## API

### POST /bingo-ai/generate-aetherviz-spec

根据教学主题生成 AI教学动画风格的完整独立互动教学 HTML。接口采用同端 SSE 和确定性工作流，计划类型固定为单页 `interactive`，并通过 `interactive_type` 分流为 `simulation`、`diagram` 或 `game`。

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
    "recent_messages": [
      {"role": "user", "content": "再快一点"}
    ]
  }
}
```

`phase=edit_html` 必须携带选中的 HTML 文件全文。**编辑线以当前 HTML 为唯一事实基线**；请求中的 `plan_summary`（若旧客户端仍携带）会被后端忽略，不参与需求编译与重生成。后端先剥离 `math-shell-v1`，并把外壳标题、学习目标和目标列表转换为可往返编辑的语义元数据，再从当前业务 HTML 确定性提取有界 DOM、CSS、函数、事件、`role_hints` 与 widget 摘要；当前校验报告、可选 `edit_target`、可选 `runtime_error` 和精简会话上下文一并交给编辑需求编译模型。编辑 system prompt 不再注入视觉/数值/布局/舞台等生成向交付片段（这些规则已沉淀在当前 HTML 中）。该模型默认使用 `deepseek-v4-flash`，把“再快一点”“修改刚才那个”等输入消歧为自包含的 `resolved_instruction`，同时输出可观察的 `change_requirements`、`preserve_requirements`、完整 `impact_areas`、`acceptance_criteria`、可选确定性 `operations`，以及服务端可机器检查的 `change_checks` / `preserve_checks`（意图硬验收真源）。目标 selector、函数和语义角色仅作为证据；兼容字段 `strategy` 仍为 `full_html_regeneration` / `clarification_required`，真正执行路由由服务端 `execution_strategy` 决定。

执行阶段按复杂度分层，而不是默认完整重生成：

1. `deterministic_patch`：对可绑定的文本/属性/CSS/widget 默认值等操作由 Python 直接改写；
2. `scoped_model_patch`：模型只输出函数级与 CSS 规则级结构化补丁，由服务端哈希守卫应用；
3. `full_html_regeneration`：完整业务 HTML 重生成，作为跨层或高复杂度改动的兜底。

任一级 hard intent 验收失败时，携带失败证据升级到下一级，而不是盲目从零完整重试。通过后再经 `contracts` 统一装配、校验与必要修复，并用同一套 intent guard 防止修复冲掉意图。`html.done.metadata` 含实际 `edit_strategy`（上述三者之一）、诊断侧 `edit_execution_strategy`、`intent_passed` / `intent_check_count`，以及确定性 `edit_diff_report`（`visual`/`runtime` 仅离线占位，不进入生产同步链路）。生成提示词鼓励对次级业务实体补充 `data-edit-role` / `data-edit-entity`，并继续复用既有 `#play-animation`、`data-role="main-visual"`、`data-region` 稳定约定。前端继续把结果保存为新分支，不覆盖原文件，并把新分支完整 HTML 作为下一次编辑的事实基线。

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
- `html.edit_diagnosed`：结构化编辑目标、`change_checks` / `preserve_checks`、证据、策略、置信度和降级状态，不包含完整 HTML
- `validation.started`
- `validation.report`
- `validation.candidate`：仅表示尚未接受的修复候选，固定包含 `accepted=false`、`rolled_back=true`、`rejection_reason`，前端不得用其覆盖当前有效报告
- `repair.started`
- `repair.done`：修复结束状态，`data` 同时返回修复后最终 `bytes` 和 `chars`
- `html.repair_source`：仅在完整、未截断的候选稿仍未通过硬校验时发送，携带 `renderable=false` 的完整 HTML 与校验报告，只允许前端作为下一次 `phase=edit_html` 的修复基线，不得预览或保存为成功产物
- `html.done`：返回完整 HTML；metadata 额外包含最终 `bytes`、`chars`、`model_chars`、`assembled_chars`、`assembly_overhead_chars`、`assembly_count` 和 `truncated`
- `context.compressed`：仅在传入规划上下文确实超过上限并被裁剪时发送
- `error`：生成失败，包含用户可读 `message`、错误码 `code`、调试用 `detail` 和布尔值 `retryable`。仅 `edit_html` 的已知可恢复错误会标记为可重试，未知错误码默认不可重试。

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

### HTML 生成状态机

`phase=generate` 使用固定 staged pipeline，**不是** LangChain `create_agent` / LangGraph / 多轮 tool 编排。模型调用保持单次（或有界重试）`ChatOpenAI.stream`；IR 后端选择由注册表与确定性评分完成，服务端硬校验与有界修复在模型之外执行。

```text
normalize_plan
    → resolve_generation_route   # ir/router：assess → 阈值 / 可选 shadow 仲裁 → IR 或明确不支持
    → generate                   # 单一 IR 后端：受限 JSON → 确定性验证 → Runtime assemble
    → assemble                   # contracts/layout：math-shell-v1 外壳装配
    → validate                   # contracts/validation：硬错误阻断，质量启发式仅 warning
    → repair                     # contracts/repair：确定性 → 函数级 → 整页模型（次数有界）
    → html.done | validation_failed / error
```

| 阶段 | 权威入口 | 边界 |
|------|----------|------|
| route | `ir/router/service.py` + `ir/registry.py` | 只选满足完整能力的已注册 IR；无合格后端时明确失败 |
| generate | `generate/workflow.py` → IR `stream` | 一次 IR 后端；候选和一次受限修复均失败后终止，不生成替代 HTML |
| assemble / validate / repair | `contracts/pipeline.py` + `contracts/repair/` | 硬门禁在服务端；repair 为有界 `RepairSession`，非开放 Agent loop |

主链路不引入通用 Agent harness。若需「看反馈再改」，只允许在 repair 子阶段扩展有界策略，不把 IR 生成交给 LLM 自选工具。

`/bingo-ai/generate-aetherviz-spec` 使用阶段化生成策略：

1. `phase=plan` 由统一配置的模型执行单次规划，生成完整 `draft` 教案计划。
2. `phase=revise_plan` 由规划模型接收 `current_plan + message`，重新生成完整 `revised` 计划，不返回局部 patch。
3. `phase=approve_plan` 将计划状态置为 `approved`。
4. `phase=generate` 根据 IR 路由结果选择后端：`geometric_recomposition` 由 `ir/recomposition/agent.py` 一次生成 3 个结构化几何 IR 候选，不生成多个 HTML；服务端淘汰确定性硬校验失败候选，对其余候选按固定权重和稳定指纹排序，只编译最高分 IR 并装配生命周期脚手架。目标拼合已满足连通、重叠和形状约束但仅整体越界时，服务端先对所有目标端点执行保持几何关系的统一平移归位；全部候选仅因中间 transform 证据不足而失败时，再用通用 waypoint 补全器生成有界、偏离首尾直线插值的独立中间状态并重新执行全部硬校验。仍失败才对最接近合格的 IR 做一次受限模型修复；修复不合格时返回 `ir_generation_failed`。重排 Runtime 直接使用已验证 `targetTransform` 提供逐片拖拽、目标轮廓、距离吸附、完成状态、参数预设和渐进揭示，不允许模型另写吸附或拼合算法。
   IR 注册表根据完整计划解析已注册表征。规划模型通过 `representation_spec` 配置视图、共享状态、跨视图对应、必须证明的不变量和交互能力，不直接指定后端名称，服务端再确定性选择 IR。若计划已同时声明几何视图、拼片全等与度量守恒，即使规划模型遗漏 `recomposition_spec` 或留下过时知识画像，归一化层也会补齐通用切分重排契约并路由到 `recomposition_scene`。一个 `coordinate_plane` 且存在可调状态时路由到 `coordinate_graph_scene`；两个或更多视图、共享参数和跨视图关系完整时路由到 `linked_coordinate_scene`；存在 `number_line` 视图、可调状态且没有二维或几何视图时路由到 `number_line_scene`；视图仅由 `data_chart` 和可选 `symbolic_panel` 组成、具有可调状态且不要求随机累计或概率密度面积时路由到 `data_distribution_scene`。各后端的首稿候选失败后只把最接近合格候选自身的错误交给一次受限 JSON 修复；修复后仍不合格即终止。服务端统一编译 data-to-screen 映射、SVG 节点注册、参数控件、动画控制器和响应式 Runtime，模型不生成任意 JavaScript。
5. IR Runtime 编译出的业务 HTML 先执行 38000/42000 字符目标/硬限制，再经过 `math-shell-v1` 服务端装配器；IR 子 Runtime 的外层布局不会进入最终 HTML。装配器会过滤业务 CSS 中的页面级、布局槽位根节点和 range 外观规则，标准 range 由 `range-v1` 独占尺寸与渲染，播放、暂停、重置按钮及 select 由服务端提供统一的按压、状态、焦点反馈，`controller-v1` 在业务脚本执行前提供 GSAP/RAF 共用动画控制接口并广播播放状态。最终装配只执行 64000 字符异常膨胀检查。
6. `validation_report` 聚合布局、HTML、JavaScript、安全、分阶段长度、Widget、动画生命周期和学科一致性检查。Widget 检查会识别主视觉挂载节点的直接查询及一层精确字符串常量查询，避免把可证明的 SVG/Canvas 动态挂载误判为空节点；仅在业务脚本直接调用 GSAP 时要求 fallback guard。业务脚本声明、遮蔽或覆盖服务端 `window.AetherVizAnimationController`，以及 GSAP `onUpdate` 经 `bind(this)` 改绑后仍调用 Tween 专属 `this.targets()`，均作为硬错误阻断。动画控制器 options 使用注释、字符串、正则和嵌套层级感知的顶层字段扫描，只有带源码范围、证据和高置信度的 `onUpdate` 误传、毫秒 duration 等明确契约错误才阻断；检查器显式标记为低置信度或非阻断的问题统一降级为 `validator_uncertain` warning 并继续交付。动画检查还会阻断 timeline/RAF 逐帧回调调用结构性 DOM/SVG 重建函数、可为空的 first/lastChild 清空后直接重挂载，并提示未清理或未经存在性校验的动态节点注册表、量化状态反复吞掉逐帧增量、对象方法或箭头属性形式的空 `setSpeed`、绕过统一动画控制器、局部几何与世界 transform 重复编码，以及 GSAP 直接污染 getState 可序列化业务对象的风险；学科启发式检查仍只产生 warning。
   Widget 校验还会识别由场景 builder 创建、却在 builder/init 调用前绑定事件或调用 DOM 方法的动态节点，并阻止仅通过空值 early-return 掩盖初始化失败的候选；KaTeX 页面中残留的可见数学定界符也会进入修复流程。
7. 检查失败时先确定性修复业务 HTML。控制器顶层 `onUpdate` 误传会只改写为 `update`，不会重写完整文档；其他生命周期错误优先使用“报告点名函数/方法/箭头函数 + SHA-256 源哈希”的函数级替换，限制函数数量和总字符数，失败回滚后仍允许其他硬错误修复继续执行；其他硬错误才进入整页修复。截断源输出不进入修复循环；截断候选、无实际变化候选、引入 `js_syntax`/`missing_runtime_ready` 的候选、以及未严格减少硬错误的候选一律拒绝。候选检查只发送 `validation.candidate`，接受后才发送新的 `validation.report`。硬错误修复 prompt 不携带质量 warning；质量 warning 只允许确定性收尾，生产同步链路不再为其调用完整 HTML 模型修复。修复事件的 `attempt` / `repair_attempt` 从第一轮修复开始计为 1。
8. 生成、编辑和模型修复的候选结果都会重新经过同一个服务端布局装配器（`contracts`）。`phase=edit_html` 先执行 `extract_business_html` 和确定性摘要，再由需求编译模型将当前输入与最近对话整理为完整编辑任务、可选 `operations` 与结构化 intent checks；**忽略 `plan_summary` 与 plan 时代 memory**，装配/校验用的 plan 由当前 HTML 的 `widget-config` 与外壳元数据推导，不按 topic 重推互动类型。执行阶段按 `deterministic_patch → scoped_model_patch → full_html_regeneration` 升级，并以 hard `change_checks` / `preserve_checks` 做意图验收与修复后守门。短会话上下文只用于消除指代，不得覆盖当前 HTML。业务 HTML 不能修改服务端布局外壳。结果仍生成新 HTML 分支，不覆盖旧 HTML。
9. 通过校验的最终 HTML 仅通过 `html.done` 返回前端；校验失败但完整未截断的候选稿可通过 `html.repair_source` 返回并标记为不可渲染，仅供后续 `edit_html` 修复。服务端不保留 HTML 文件缓存或产物路径。

生产同步链路不启动浏览器。几何 IR 只允许白名单 state/definition/local 引用、算术与几何操作符、SVG 图元和属性；通用 DSL 包含 `atan/atan2/hypot` 等角度与距离计算，并允许每个稳定图元声明 2~5 个 transform keyframes。计划中的 `recomposition_spec` 会由前后端类型和 approve/generate 请求契约完整传递；其中 `proof_constraints` 描述度量不变量、目标关系、目标拼合约束和教学阶段。每个 `stage_requirement` 由服务端归一化为唯一 `id`、`source/intermediate/target` 角色、确定时间点、几何证据类型和最小图元比例。IR 的教学帧必须用 `stage_id`/`at` 一一覆盖计划阶段；每个中间阶段必须有足够比例图元在同一时间点形成区别于首尾且偏离直接线性插值的几何关键状态，纯文字中间步骤会被阻断。`target_relations` 使用通用结构化关系 `equal_area` / `equal_length` / `equal_angle` / `parallel` / `perpendicular` / `coincident` / `collinear` / `congruent`，通过图元、顶点和线段引用表达；`target_assembly` 使用 `connected` / `non_overlapping` / `approximate_rectangle` 描述世界坐标下的连通性、重叠率、矩形度及参数趋势，不包含知识点分支。服务端会在默认、最小和最大状态展开图元，阻断无效尺寸、非有限值、重复 id、静止端点、源状态明显重叠、源/目标整体越界、缺失中间几何证据、明确违反度量不变量、结构化几何关系或显式目标拼合约束的结果；仅目标拼合整体越界且所有采样状态的联合包围盒可容纳于画布时，允许统一平移目标端点后重新执行完整校验。归一化计划始终保留 `piece_congruence`，因此 repeat 图元的局部几何不得直接或间接依赖 repeat 索引，索引只能用于 id、样式和 transform，防止局部角度与旋转重复编码。修复反馈只携带状态级拼合指标和阶段失败摘要，避免逐拼片诊断挤占模型上下文。未声明 `target_assembly` 时该评分项为 0，不再按满分处理。扇形 `sector_path` 支持确定性轮廓采样和面积计算，其他当前图元或引用不足以计算时产生 warning，且不可计算的显式关系不会获得完整数学评分。编译后的 Scene Module 还会在无 DOM/网络/动态代码能力的 Node `vm` 中执行低成本冒烟检查，检查器会从 IR 自动发现任意计划 state 名称并补齐采样值；真实浏览器布局与行为验证仍由离线流程负责。

### 离线视觉稳定性验证

IR 路由与生成流水线基线使用仓库内本地数据集进行确定性回归，不创建远程 LangSmith Dataset/Evaluator：

```bash
uv run python evals/run_ir_routing_eval.py
uv run python evals/run_ir_routing_eval.py --enable-llm --output /tmp/aetherviz-ir-routing-report.json
uv run python evals/run_generate_baseline_eval.py
uv run python evals/run_generate_baseline_eval.py --output evals/reports/generate-baseline-latest.json
```

`run_generate_baseline_eval.py` 汇总三类本地基线：路由命中、硬校验通过/失败、确定性 repair 成功率；默认不调用模型。
`run_ir_routing_eval.py` 同时接受主题样本和完整计划样本，并要求数据集覆盖注册表中的全部 IR 后端；新增 IR 未补路由样本时会直接失败。
生成链路会静态检查抽象 SVG viewBox、屏幕像素字号、缩放描边和动画渲染生命周期。抽象 SVG 的确定性尺度修复先按初始 CTM 把用户单位换算为屏幕字号和线宽，再在 resize 时反算回用户单位，避免把 `0.2` 字号或 `0.05` 描边误当成亚像素屏幕值。纯 SVG simulation 若自行维护 RAF 且绕过服务端动画控制器会作为硬错误修复；Canvas 高频循环仍允许保留为非阻断 warning。结构创建应位于 `buildScene`，逐帧回调只通过 `deriveView/applyView` 更新既有节点；连续动画涉及有界离散拓扑数量时，应在 `buildScene` 按变量上界预分配节点池，逐帧仅切换可见性和属性。显式参数变更导致节点数量变化时需暂停动画、清空注册表并重建 timeline，渲染循环以实际注册表长度为边界或逐项校验节点存在。

`math-shell-v1` 会移除模型对舞台高度和外层布局的覆盖（包括选择器前带 CSS 注释的情况），并把仅包含按钮的模型控件行归一化为整行 action group。959px 以下舞台高度使用视口相关上限，599px 以下控件改为单列，避免滑块、播放按钮和预设按钮互相挤压。

开发环境会在 959×900、960×540、1280×720、912×1180 和 390×844 视口运行浏览器回归，覆盖响应式断点两侧及平板尺寸：

```bash
uv run playwright install chromium
uv run python evals/targets/visual.py /path/to/generated.html --report /tmp/visual-report.json
uv run python evals/targets/css_edit.py /path/to/before.html /path/to/after.html \
  --selector '#target' --expected-style 'display=grid' \
  --interaction-selector '#action' --report /tmp/css-edit-report.json
uv run python evals/run_eval.py --repetitions 4 --max-runs 35 --live-model --browser --output-dir /tmp/recomposition-35
```

完整页面脚本除视觉布局外，还检查槽位重叠、range 的 44~64px 命中高度和槽位内包含关系、播放后的可见变化、暂停稳定性、参数修改后的完整重置、完成状态与再次播放、重复播放节点数稳定性，并收集页面异常和每个运行时动作的调用异常；单个动作抛错会形成失败报告而不会中断整轮回归。CSS 编辑前后门禁额外检查目标 selector 数量与可见性、预期 computed style、主视觉可见性、新增浏览器异常和指定交互动作，并对目标区域打码后比较整页截图，默认阻断目标区域之外的意外变化；明确允许整体布局变化时可传入 `--allow-outside-target-changes`。这些脚本只用于离线验证，不进入生产同步链路。

`evals/datasets/html_contract/playback_progress.html` 是通用播放进度回归夹具；`tests/evals/test_playback_regression.py` 会真实点击播放按钮，并在 native fallback 与本地 GSAP stub 两种路径下验证 500ms 内 `getState()` 的连续进度及可见画面均发生变化。该检查只在本地测试执行，不进入生产请求。

可从 `langsmith trace get --full --format json --output ...` 的真实导出构建本地单步评估数据集：

```bash
uv run python evals/datasets/build_visual.py /tmp/trace.json --output /tmp/aetherviz-visual-dataset.json
```

`evals/evaluators/visual.py` 提供视觉总通过、舞台可见性、SVG 尺度、动画变化、暂停、重置、参数同步、节点稳定和 GSAP fallback 等单指标确定性 evaluator，仅用于本地或离线回归；Dataset 与 Evaluator 可按需提交，运行生成的评测报告保留在本地忽略目录 `evals/reports/`，禁止通过 LangSmith CLI/SDK/API/UI 创建或上传远端 Dataset/Evaluator。

`evals/datasets/recomposition/legacy-topics.jsonl` 保留早期的 4 个开发主题、3 个保留主题和 4 个挑战主题。当前统一入口 `evals/run_eval.py` 分别统计分类、首次候选集中是否存在合格 IR、首次 Scene 契约、一次受限 JSON 修复后的最终契约、教学语义约束、目标拼合约束、完整 HTML 硬校验和浏览器 Runtime，并保存每个候选的硬失败、分项得分、稳定指纹、目标拼合指标及排序。LangSmith 子 Run `aetherviz.geometry_ir_ranking` 仅记录脱敏后的候选数量、分数、硬失败、拼合指标、不可计算关系和选择原因，不记录候选 IR 正文。首稿 IR 门槛为 95%，最终 IR 合格门槛为 97%；可用 `--max-runs` 精确限制调用次数。

本地跨维度评估集位于 `evals/datasets/recomposition/`，包含 24 个主题、5 个通用无效 mutation、1 个受控 completion 样本、覆盖矩阵和阈值。受控样本构造仅有目标拼合整体越界的合法候选，硬性要求 `deterministic_target_bounds_completion` 至少尝试一次且成功率为 100%，不依赖真实模型随机触发。主题同时覆盖 piece 数量、平移/旋转/翻转/组合变换、面积/长度/角度/全等、多边形/线段/角/网格、3~5 个阶段、推导难度和参数边界。默认执行 3 次形成 72 次主题回归，并额外执行一次受控 completion：

```bash
uv run python evals/run_eval.py
uv run python evals/run_eval.py --live-model --browser
```

确定性 evaluator 检查 Dataset 矩阵、分类、Geometry IR/Scene/HTML 契约、数学不变量、教学阶段、无效案例检测和受控 completion；`piece_count` 与主要变换的主题意图对齐作为诊断项单独汇总，避免把启发式语义当作生产硬裁决。真实模型回归的 summary 额外统计 `raw_candidate`、`deterministic_target_bounds_completion`、`deterministic_waypoint_completion` 策略次数，以及确定性候选修复的尝试与成功数。结果默认写入本地忽略目录 `evals/reports/latest/`；如需形成可审查基线，应显式复制到非忽略目录并记录 Git revision 与工作区状态。脚本不实例化 LangSmith Client，也不调用 Dataset/Evaluator 远端 API；真实模型与浏览器仅在显式传入参数时运行。模块职责与更多命令见 `evals/README.md`。

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
- 学科与互动类型选择在 `workflow/plan_detection.py`，计划规范化在 `workflow/plan_contract.py`；各 IR 的结构化生成 prompt 位于对应 `ir/<family>/` 子包，编辑 prompt 位于 `edit/prompts.py`；HTML 装配/校验/修复在 `contracts/`。生成与编辑业务包互不 import。
- 成功事件 `html.done.metadata.generation_backend` 为 10 个已注册 IR 后端之一；无合格路由的错误事件使用 `generation_backend=unsupported` 和 `code=unsupported_ir_capability`，IR 校验失败使用 `code=ir_generation_failed`。API/SSE 主结构不变。
- 前端可展示 `generation_attempts`、`repair_attempts`、兼容字段 `attempts`、`repaired`、`degraded`、`validation_warnings`、`context_status`、`bytes` 和 `chars`。
- 计划中的 action 使用 `widget_setState`、`widget_highlight`、`widget_annotation`、`widget_reveal`；生成物 iframe 内部应兼容 `SET_WIDGET_STATE`、`HIGHLIGHT_ELEMENT`、`ANNOTATE_ELEMENT`、`REVEAL_ELEMENT` 消息。

## 验证

运行 AI教学动画测试：

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
curl -N -X POST http://localhost:10099/bingo-ai/generate-aetherviz-spec \
  -H "Content-Type: application/json" \
  -d '{"topic":"牛顿第二定律"}'
```
