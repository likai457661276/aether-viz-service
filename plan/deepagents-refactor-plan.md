# Deep Agents 前后端重构计划

## 背景

项目将引入 [langchain-ai/deepagents](https://github.com/langchain-ai/deepagents) 作为后端 Agent 底座，按第一性原则重构 AI 互动实验的前后端链路。

本次不是对现有代码做兼容式补丁，而是以高内聚、低耦合为目标重新设计核心结构：

- 后端以 Deep Agents 为任务编排核心。
- 前端以“教案计划确认 -> HTML 产物生成 -> 产物预览与编辑”为主流程。
- LLM 只负责生成计划、HTML 和修复草稿。
- HTML 检查由后端确定性工具完成。
- 上下文压缩由 Deep Agents 管理，不再让前端承担硬性 Token 展示与判断。

首期不接入 Playwright 浏览器渲染检查。首期检查链路只包含 HTML parser、JS checker、安全检查和长度检查。

## 重构原则

1. 不为旧代码形态做过度兼容。
2. 接口语义优先于旧字段复用。
3. 前端状态机围绕用户真实流程设计，不围绕后端历史事件设计。
4. 后端模块按职责拆分，避免路由层、LLM 调用、校验、修复和事件流混在一起。
5. Deep Agents 负责组织任务，不替代确定性检查工具。
6. 计划、生成、检查、修复、编辑是独立阶段，每个阶段有清晰输入和输出。
7. 生成物始终是自包含 HTML，前端只用 iframe 隔离预览，不渲染课件内部逻辑。
8. 不恢复静态知识点命中、静态 HTML 文件目录或非 AI 互动实验功能。

## 目标

1. 重构后端为 Deep Agents 驱动的 Agent 生成链路。
2. 重构前端为计划卡片与 HTML 产物卡片分离的工作台。
3. 支持先生成教案计划，用户可通过 chat 多轮修改计划；每次计划修改必须通过 Deep Agents 的 `planning_agent` 重新生成教案计划。
4. 用户确认计划后，才进入 HTML 生成。
5. Deep Agents 组织 HTML 生成、沙箱写入、确定性检查、自动修复和最终输出。
6. 模型按任务分流：
   - 计划生成与计划修订：`deepseek-v4-flash`
   - HTML 生成：`qwen3.7-plus`
   - HTML 修复：`qwen3.7-plus`
7. 用 Deep Agents 上下文压缩机制替代前端硬性 Token 数字展示。
8. 形成稳定闭环：

```text
用户输入教学主题
  ↓
Deep Agents 生成教案计划
  ↓
用户通过 chat 提出修改意见
  ↓
Deep Agents 通过 planning_agent 重新修改教案计划
  ↓
用户确认计划
  ↓
Deep Agents 生成完整 HTML
  ↓
写入沙箱
  ↓
HTML parser / JS checker / 安全检查 / 长度检查
  ↓
生成结构化检查报告
  ↓
Deep Agents 通过 repair_agent 调用 qwen3.7-plus 自动修复
  ↓
再次检查
  ↓
输出可分发自包含 HTML
```

## 非目标

- 不迁移到 OpenMAIC 的 Next.js、多场景课堂或 LangGraph 多 Agent 应用架构。
- 不让前端渲染课件内部 SVG、Canvas 或 DOM 逻辑。
- 不把生成物依赖搬回 React 组件。
- 不让 LLM 自行判定安全边界。
- 首期不接入 Playwright 和截图检查。
- 不保留旧接口、旧事件、旧字段作为设计约束。

## 目标架构

### 后端分层

建议将后端核心重构为以下层次：

```text
aetherviz_service/
  main.py
  config.py
  aetherviz/
    api/
      routes.py
      schemas.py
      sse.py
    agents/
      runtime.py
      planner_agent.py
      html_agent.py
      repair_agent.py
      model_factory.py
      context_policy.py
    tools/
      html_parser.py
      js_checker.py
      security_checker.py
      length_checker.py
      validation_report.py
    sandbox/
      manager.py
      artifacts.py
    workflow/
      plan_workflow.py
      generate_workflow.py
      revise_plan_workflow.py
      edit_html_workflow.py
```

职责边界：

- `api/`：只处理 HTTP 入参、SSE 输出和错误响应。
- `agents/`：创建 Deep Agents、绑定模型、管理上下文压缩和阶段 Agent。
- `tools/`：提供确定性检查工具，返回结构化报告。
- `sandbox/`：管理任务沙箱、HTML 文件、检查报告和修复草稿。
- `workflow/`：编排业务阶段，不直接写底层检查逻辑。

### Deep Agents 能力映射

| Deep Agents 能力 | 本项目用途 |
| --- | --- |
| Planning | 生成和修订教案计划 |
| Tools | 调用 HTML parser、JS checker、安全检查和长度检查 |
| Virtual filesystem | 管理 HTML、检查报告和修复草稿 |
| Context management | 压缩长 chat、HTML、检查日志和修复历史 |
| Human-in-the-loop | 在计划确认点暂停 |
| Subagents | 拆分 planner、html_builder、repair_agent |
| Streaming | 输出新版 SSE 工作流事件 |

## 后端接口设计

本次重构不沿用旧接口语义，采用面向流程的 phase。

### `phase=plan`

用于生成初版教案计划。

输入：

```json
{
  "phase": "plan",
  "topic": "初中物理 电路串并联",
  "context": {}
}
```

输出事件：

- `plan.started`
- `plan.delta`
- `plan.ready`
- `context.compressed`
- `error`

计划状态：

- `draft`

### `phase=revise_plan`

用于修改已有教案计划。

输入：

```json
{
  "phase": "revise_plan",
  "topic": "初中物理 电路串并联",
  "current_plan": {},
  "message": "把互动改成闯关式，并增加学生预测环节"
}
```

选择 `phase=revise_plan` 的原因：

- 语义清晰，初次计划和计划修订在接口层分开。
- 后端可强制要求 `current_plan + message`。
- 日志、监控、测试和前端状态机更容易定位。
- 后续扩展计划版本、计划 diff、审批状态更自然。
- 这是长期核心流程，不应伪装成初次 `plan` 请求。

输出事件：

- `plan.revise_started`
- `plan.delta`
- `plan.revised`
- `context.compressed`
- `error`

计划状态：

- `revised`

硬性要求：

- `phase=revise_plan` 不允许绕过 Deep Agents 直接调用 LLM。
- 后端必须由 `planning_agent` 接收 `current_plan + message`，重新生成完整教案计划。
- 前端 chat 修改计划只产生计划修订，不触发 HTML 生成。

### `phase=approve_plan`

用于用户确认计划。

输入：

```json
{
  "phase": "approve_plan",
  "plan": {}
}
```

输出事件：

- `plan.approved`
- `error`

计划状态：

- `approved`

### `phase=generate`

用于根据已确认计划生成 HTML。

输入：

```json
{
  "phase": "generate",
  "approved_plan": {}
}
```

输出事件：

- `html.generation_started`
- `sandbox.written`
- `validation.started`
- `validation.report`
- `repair.started`
- `repair.done`
- `html.done`
- `context.compressed`
- `error`

硬性要求：

- HTML 自动修复必须由 Deep Agents 的 `repair_agent` 组织执行。
- 后端检查工具只产生结构化报告，不直接改写 HTML。
- `qwen3.7-plus` 只能作为 `repair_agent` 的修复模型使用，不由工作流绕过 Agent 直接调用。

### `phase=edit_html`

用于基于选中的 HTML 文件全文生成新分支。

输入：

```json
{
  "phase": "edit_html",
  "current_html": "<!doctype html>...",
  "message": "把按钮改成更适合课堂投屏的样式",
  "context": {}
}
```

输出事件：

- `html.edit_started`
- `sandbox.written`
- `validation.started`
- `validation.report`
- `repair.started`
- `repair.done`
- `html.done`
- `context.compressed`
- `error`

## 后端 Agent 设计

### `planning_agent`

模型：`deepseek-v4-flash`

职责：

- 生成教案计划。
- 修订教案计划。
- 接收前端 chat 修改意见，并重新输出完整教案计划。
- 整合教学目标、互动形式、控件、运行时、教学流程和设计约束。

硬性要求：

- 每次 chat 修改计划都必须经过 `planning_agent`。
- `planning_agent` 输出的是新的完整计划，不是局部 patch。
- 计划修订不得触发 HTML 生成。

输出结构：

- `plan_id`
- `status`
- `topic`
- `learning_goal`
- `scene_outline`
- `widget_outline`
- `design_brief`
- `interactive_spec`
- `widget_actions`
- `teaching_flow`
- `controls`
- `runtime`
- `revision_summary`
- `context_status`

### `html_agent`

模型：`qwen3.7-plus`

职责：

- 读取已确认计划。
- 生成完整自包含 HTML。
- 将 HTML 写入沙箱。
- 调用确定性检查工具。

约束：

- 不直接跳过检查。
- 不把推理文本混入 HTML。
- 不依赖外部未知资源。
- 首次输出目标控制在 36000 字符以内，硬上限 40000 字符。

### `repair_agent`

模型：`qwen3.7-plus`

职责：

- 读取结构化检查报告。
- 修复 HTML。
- 写入新的修复草稿。
- 触发再次检查。

硬性要求：

- HTML 自动修复必须通过 `repair_agent` 完成。
- `repair_agent` 使用 `qwen3.7-plus`，但修复流程由 Deep Agents 管理。
- 工作流不得绕过 `repair_agent` 直接调用 `qwen3.7-plus` 修改 HTML。

约束：

- 默认最多修复 2 次。
- 基础结构、安全边界或 JS 语法仍失败时返回 `error`。
- 轻量质量警告可随 `html.done` 返回 `validation_warnings`。

### `aetherviz_agent_runtime`

职责：

- 按 phase 调度对应 Agent。
- 管理沙箱 run_id。
- 管理上下文压缩策略。
- 将 Agent 事件转换为 SSE。
- 聚合 metadata、attempts、repaired、degraded、validation_warnings。

重要原则：

- 不让同一个 Agent 自由切换所有模型。
- 不让模型自行决定阶段跳转。
- phase 是后端工作流的确定性边界。

## 检查工具计划

### 必须工具

- HTML parser：检查文档结构、缺失标签、危险节点和基础长度。
- JS checker：检查内联脚本语法。
- Security checker：检查危险协议、未知远程资源、外部脚本和不安全能力。
- Length checker：检查目标长度和硬上限。

### 暂缓工具

- Playwright runner：首期不接入。
- Screenshot checker：首期不接入。

### 工具返回格式

工具返回结构化 JSON，不返回长文本日志：

```json
{
  "ok": false,
  "severity": "error",
  "summary": "脚本语法错误",
  "errors": [
    {
      "type": "js_syntax",
      "message": "Unexpected token",
      "line": 128
    }
  ],
  "warnings": [],
  "artifacts": {
    "html_path": "sandbox/run-xxx/index.html",
    "report_path": "sandbox/run-xxx/validation-report.json"
  }
}
```

Deep Agents 只把摘要放入上下文，大型 HTML、报告和修复草稿都写入沙箱文件。

## 沙箱目录策略

沙箱目录通过 `AETHERVIZ_AGENT_SANDBOX_ROOT` 配置。

| 环境 | 落点 | 示例 |
| --- | --- | --- |
| 开发环境 | 项目临时目录 | `.aetherviz_sandbox` |
| 生产环境 | 容器内挂载目录 | `/app/.aetherviz_sandbox` 或挂载卷路径 |

安全要求：

- 单次任务使用独立 `run_id` 子目录。
- Deep Agents 只能读写当前任务沙箱子目录。
- 沙箱目录不得指向仓库源码目录、用户主目录或系统配置目录。
- 生产环境需要限制目录容量、生命周期和清理策略。

## 百炼模型接入方案

项目使用阿里云百炼千问服务。Deep Agents 接入百炼时，只采用推荐的 OpenAI 兼容接口方案。

### 模型 ID

- 计划生成与计划修订：`deepseek-v4-flash`
- HTML 生成：`qwen3.7-plus`
- HTML 修复：`qwen3.7-plus`

### 接入方式

使用 `langchain-openai.ChatOpenAI` 显式传入百炼 OpenAI-compatible endpoint。

不要直接写：

```python
create_deep_agent(model="openai:qwen3.7-plus")
```

应显式创建模型实例：

```python
from langchain_openai import ChatOpenAI

html_model = ChatOpenAI(
    model="qwen3.7-plus",
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    temperature=0.2,
    max_tokens=16384,
    extra_body={
        "enable_thinking": False
    },
)
```

计划模型：

```python
planning_model = ChatOpenAI(
    model="deepseek-v4-flash",
    api_key=settings.planning_openai_api_key or settings.openai_api_key,
    base_url=settings.planning_openai_base_url or settings.openai_base_url,
    temperature=0.3,
    max_tokens=16384,
    reasoning_effort=settings.planning_reasoning_effort or "high",
)
```

HTML 与修复模型显式关闭思考模式：

```python
html_model = ChatOpenAI(
    model="qwen3.7-plus",
    api_key=settings.openai_api_key,
    base_url=settings.openai_base_url,
    temperature=0.2,
    max_tokens=16384,
    extra_body={
        "enable_thinking": False
    },
)
```

原因：

- Deep Agents 需要 LangChain ChatModel。
- 显式 `base_url` 可以避免默认走 OpenAI 官方端点。
- 百炼 OpenAI 兼容接口同时覆盖 Qwen 和 DeepSeek，便于统一模型路由。
- HTML 生成和修复需要确定性完整文件，不需要把推理过程暴露进生成流。
- 计划阶段使用 `deepseek-v4-flash` 的 `reasoning_effort=high` 更合适。

## 配置计划

新增或调整环境变量：

```bash
OPENAI_API_KEY="你的百炼 API Key"
OPENAI_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_MODEL="qwen3.7-plus"

PLANNING_OPENAI_API_KEY=""
PLANNING_OPENAI_BASE_URL=""
PLANNING_OPENAI_MODEL="deepseek-v4-flash"
PLANNING_REASONING_EFFORT="high"

AETHERVIZ_PLAN_MODEL="deepseek-v4-flash"
AETHERVIZ_HTML_MODEL="qwen3.7-plus"
AETHERVIZ_REPAIR_MODEL="qwen3.7-plus"
AETHERVIZ_AGENT_MAX_REPAIR_ATTEMPTS=2
AETHERVIZ_AGENT_SANDBOX_ROOT=".aetherviz_sandbox"
AETHERVIZ_AGENT_CONTEXT_POLICY="auto"
```

说明：

- `deepseek-v4-flash` 与 `qwen3.7-plus` 已按百炼模型 ID 确认。
- 模型、地域端点和 Workspace 专属端点仍通过环境变量配置。
- 不把真实 API Key 写入仓库。

## 前端重构计划

前端项目路径：`/Users/likai/Documents/workspace/bingo-aetherviz`

这是本次重构唯一明确关联的前端项目。涉及前端类型、API、SSE 消费、计划卡片、HTML 产物卡片和 iframe 预览的改动，都应落在该目录内。

### 信息架构

前端围绕三类对象设计：

- `Plan`：教案计划。
- `HtmlArtifact`：HTML 产物。
- `AgentRun`：一次后端 Agent 执行记录。

### 计划卡片

计划卡片只负责计划相关能力：

- 展示教案计划。
- 展示计划状态。
- 展示修改摘要。
- 支持 chat 修改计划，并通过 `phase=revise_plan` 交给后端 Deep Agents 重新生成完整教案计划。
- 支持用户确认计划。

计划状态：

- `draft`
- `revised`
- `approved`

### HTML 产物卡片

HTML 产物卡片只负责生成物相关能力：

- 展示生成状态。
- 展示验证状态。
- 展示修复次数。
- 展示 iframe 预览。
- 管理多个 HTML 分支。
- 发起 HTML 编辑。

产物状态：

- `queued`
- `generating`
- `checking`
- `repairing`
- `done`
- `failed`

### 用户流程

```text
输入主题
  ↓
生成计划卡片
  ↓
chat 修改计划
  ↓
Deep Agents 重新生成教案计划
  ↓
确认计划
  ↓
生成 HTML 产物卡片
  ↓
检查 / 修复 / 完成
  ↓
Deep Agents 通过 repair_agent 完成自动修复
  ↓
iframe 预览
  ↓
chat 编辑 HTML 生成新分支
```

### Token 展示降级

前端不展示硬性 Token 数字。

展示上下文状态：

- `normal`：上下文充足。
- `compressed`：已自动压缩历史，流程可继续。
- `degraded`：上下文不足以稳定继续，需要用户确认摘要或补充信息。

## SSE 事件计划

采用新版事件命名，不保留旧事件作为设计约束。

事件列表：

- `plan.started`
- `plan.delta`
- `plan.ready`
- `plan.revise_started`
- `plan.revised`
- `plan.approved`
- `html.generation_started`
- `html.edit_started`
- `sandbox.written`
- `validation.started`
- `validation.report`
- `repair.started`
- `repair.done`
- `html.done`
- `context.compressed`
- `error`

统一事件结构：

```json
{
  "event": "validation.report",
  "run_id": "run_xxx",
  "phase": "generate",
  "data": {},
  "metadata": {
    "attempts": 1,
    "repaired": false,
    "degraded": false,
    "validation_warnings": []
  }
}
```

## 上下文压缩计划

后端原则：

1. 完整 HTML 写入沙箱，不长期放入对话上下文。
2. 检查日志和修复 diff 只保留摘要。
3. 计划修改历史压缩为 `revision_summary`。
4. Deep Agents 压缩后发送 `context.compressed`。
5. 压缩后仍无法保证质量时返回 `degraded=true`。

前端原则：

1. 不展示具体 Token 数。
2. 展示上下文健康状态。
3. `degraded=true` 时要求用户确认摘要或补充约束。

## 依赖策略

Deep Agents 直接进入主依赖。

新增主依赖：

- `deepagents`
- `langchain-openai`

原因：

- Deep Agents 是新后端主链路底座。
- 生产、Docker、本地开发和测试环境必须一致。
- 不把核心能力做成可选实验依赖。

## 分阶段实施

### 阶段 1：后端骨架重建

- 新建 `api/`、`agents/`、`tools/`、`sandbox/`、`workflow/` 分层。
- 接入 `deepagents` 和 `langchain-openai`。
- 建立 `planning_agent`、`html_agent`、`repair_agent`。
- 建立沙箱管理器。
- 建立新版 SSE 事件模型。

验收标准：

- `phase=plan` 可返回结构化计划。
- `phase=revise_plan` 可基于 `current_plan + message` 返回修订计划。
- `phase=approve_plan` 可将计划状态置为 `approved`。

### 阶段 2：HTML 生成与检查闭环

- `phase=generate` 根据已确认计划生成 HTML。
- HTML 写入沙箱。
- 执行 HTML parser、JS checker、安全检查和长度检查。
- 检查失败时触发 Deep Agents 的 `repair_agent`。
- 修复后重新检查。

验收标准：

- 结构错误、JS 语法错误、危险资源、超长 HTML 可被拦截。
- 自动修复最多执行 2 次。
- 最终输出 `html.done` 或明确 `error`。

### 阶段 3：前端工作台重构

- 以前端对象 `Plan`、`HtmlArtifact`、`AgentRun` 重建状态管理。
- 拆分计划卡片与 HTML 产物卡片。
- 接入新版 phase 与 SSE 事件。
- iframe 只负责隔离预览自包含 HTML。

验收标准：

- 用户可完成 `plan -> revise_plan -> approve_plan -> generate -> preview`。
- 未确认计划时不会生成 HTML。
- HTML 编辑会生成新分支，不覆盖旧产物。

### 阶段 4：上下文压缩与降级体验

- 后端接入 Deep Agents 上下文压缩策略。
- 大 HTML、检查报告和修复草稿文件化。
- 前端展示 `normal/compressed/degraded`。
- `degraded=true` 时要求用户确认摘要或补充信息。

验收标准：

- 长对话不会因 Token 数字展示中断主流程。
- 压缩后能恢复当前计划、当前产物和下一步动作。

### 阶段 5：文档、测试与联调

- 更新 README。
- 更新 `.env.example`。
- 补充后端单元测试与接口测试。
- 补充前端状态机和 SSE 消费测试。
- 完成前后端联调。

验收标准：

- 后端核心测试通过。
- 前端可完整跑通新工作流。
- 文档描述与实际链路一致。

## 风险与控制

| 风险 | 控制方式 |
| --- | --- |
| 重构范围大 | 按阶段落地，每阶段保持可运行闭环 |
| Agent 权限过大 | 工具只暴露当前 run_id 沙箱目录 |
| LLM 生成危险 HTML | 安全检查器硬拦截 |
| 自动修复循环过长 | 限制最大修复次数 |
| 上下文压缩导致目标漂移 | 压缩摘要必须保留目标、计划、产物和下一步动作 |
| 模型端点变化 | 通过环境变量配置 |
| 前端状态复杂 | 用 `Plan`、`HtmlArtifact`、`AgentRun` 三类对象收敛状态 |

## 已确认决策

1. 本次是前后端整体重构，不以兼容现有代码为目标。
2. Deep Agents 依赖直接进入主依赖。
3. 百炼接入只采用 OpenAI 兼容接口方案。
4. 计划模型使用 `deepseek-v4-flash`。
5. HTML 生成和修复使用 `qwen3.7-plus`。
6. 开发环境沙箱目录落在项目临时目录。
7. 生产环境沙箱目录落在容器内挂载目录。
8. 首期去掉 Playwright 浏览器渲染检查能力。
9. 计划修改接口使用 `phase=revise_plan`，不做旧 `phase=plan + current_plan + message` 兼容。
