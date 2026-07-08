# AGENTS.md

本文件定义 `aether-viz-service` 仓库当前分支的项目级代理协作规范。

适用范围：仓库根目录及其所有子目录。

当用户指令与本文件冲突时，以用户指令为准。

## 1. 项目定位

这是一个基于 Python 3.12 的 FastAPI 服务，提供 AI互动实验互动教学可视化生成链路。

AI互动实验通过 `/generate-aetherviz-spec` 根据教学主题生成完整独立 HTML。服务采用同端 SSE 和 Deep Agents 阶段化链路：`phase=plan` 生成单页 `interactive` 教案计划；`phase=revise_plan` 基于 `current_plan + message` 由 `planning_agent` 重新生成完整计划；`phase=approve_plan` 标记计划确认；`phase=generate` 携带 `approved_plan` 生成自包含互动 HTML；HTML 文件修改用 `phase=edit_html` 携带选中文件全文 `current_html` 和 `message`，并返回新的 HTML 分支。计划字段包括 `page_type`、`interactive_type`、`scene_outline`、`widget_outline`、`design_brief`、`interactive_spec`、`widget_actions`、`teaching_flow`、`controls`、`runtime` 等。生成和编辑阶段按“模型 HTML -> 沙箱写入 -> 确定性检查 -> 自动修复 -> 最终输出”执行，生产链路硬拦截文档结构、安全边界、内联脚本语法和 HTML 长度上限。动态生成逻辑以 OpenMAIC interactive 为核心，生成物运行时使用原生 HTML/CSS/JS、Canvas/SVG、`requestAnimationFrame`，并可使用白名单 GSAP core CDN 管理教学分镜。

项目已移除静态知识点命中、静态 HTML 文件目录和静态 HTML 返回接口。后续不要新增或恢复静态页面逻辑，除非用户明确要求。

后续不要新增或恢复非 AI互动实验功能，除非用户明确要求。

代码主目录：

- `aetherviz_service/`：应用主代码。
- `aetherviz_service/aetherviz/`：AI互动实验核心业务模块。
- `tests/`：测试。
- `README.md`：对外说明与本地运行文档。
- `pyproject.toml`：依赖、构建与测试配置。
- `Dockerfile`：容器镜像构建定义。
- `docker-compose.dev.yml`：开发环境容器编排。
- `docker-compose.prod.yml`：生产环境容器编排。

### 关联前端项目

- 前端项目路径：`/Users/likai/Documents/workspace/bingo-aetherviz`。
- 前端项目名称：`bingo-aetherviz` / `AI动态课件`。
- 前端技术栈：Vite + React + TypeScript；包管理器、Node 和 pnpm 版本以后端联调时该前端仓库 `package.json` 中的 `packageManager` 与 `volta` 字段为准。
- 前端职责：负责 chat 工作区、计划确认、SSE 事件消费、多个 HTML 产物管理、iframe `srcDoc` 预览和运行时错误桥接。
- 后端职责：负责 OpenMAIC widget 计划、HTML 生成、HTML 文件编辑、自动修复、基础结构安全校验、HTML 长度控制和最终自包含 HTML 输出。
- 职责边界：前端不渲染课件内部 SVG/Canvas/DOM 逻辑，不把后端生成物依赖搬回 React 组件；前端只消费后端返回的自包含 HTML，并在 iframe 中隔离预览。
- 联调约定：后端默认运行在 `http://localhost:10095`；前端可通过 `VITE_API_BASE_URL` 或 Vite proxy 指向该后端。
- 接口协作：前端按 `phase=plan -> phase=revise_plan -> phase=approve_plan -> phase=generate -> html.done` 流程工作；后续修改仅走 `phase=edit_html`，发送选中 HTML 文件全文 `current_html`、修改意见 `message` 和摘要型 `context`，用于生成新的 HTML 分支，不覆盖旧 HTML。
- OpenMAIC 改造边界：本项目采用 Widget 链路级对齐，保留当前 FastAPI 单页 SSE 接口，不迁移 OpenMAIC 的 Next.js、多场景课堂、LangGraph 或多 Agent 应用架构。
- 后端修改计划字段、SSE 事件、`metadata` 或 iframe action 契约时，必须同步检查前端 `src/types/aetherviz.ts`、`src/api/aetherviz.ts`、计划展示组件和 iframe 预览组件。

## 2. 运行环境

在本仓库内执行任务时，默认按以下环境理解：

- 操作系统：macOS
- Shell：`zsh`
- Python：`3.12`
- 依赖管理：`uv`
- 本地默认运行方式：Docker

若任务涉及跨平台兼容性、容器行为或 CI 环境，不得直接假设本地行为等同于 Linux 容器行为，需单独说明。

## 3. 工作方式

所有任务遵循以下状态流转：

`INIT -> ANALYSIS -> EXECUTION -> COMPLETED`

若遇到阻塞，可进入：

- `FAILED`：已尝试执行，但因错误未完成。
- `ABORTED`：缺少关键条件、继续执行风险过高，主动停止。

执行要求：

1. 先分析再执行，不要跳过上下文确认。
2. 优先做小步、可审查的修改。
3. 非必要不扩大改动面，不顺手重构无关代码。
4. 如果发现用户已有未提交改动，默认保留，不得覆盖或回滚。

## 4. 目录职责约定

### `aetherviz_service/`

- `main.py` 负责 FastAPI 应用装配，只挂载 AI互动实验路由。
- `config.py` 负责配置读取与集中管理。
- `llm_service.py` 负责调用 OpenAI-compatible 大模型服务，供 AI互动实验模型链路使用。

### `aetherviz_service/aetherviz/`

AI互动实验是独立子模块，负责互动教学可视化生成链路。新增 AI互动实验相关能力时，优先放入此目录，不在 `aetherviz_service/` 根目录新增平铺业务文件。

- `api/` 负责 HTTP 入参、phase schema、新版 SSE 事件结构、错误响应和路由定义。
- `agents/` 负责 Deep Agents runtime、`planning_agent`、`html_agent`、`repair_agent`、模型工厂和上下文策略。
- `workflow/` 负责 `plan`、`revise_plan`、`approve_plan`、`generate`、`edit_html` 阶段编排，不直接堆积底层校验逻辑。
- `tools/` 负责 HTML parser、JS checker、安全检查、长度检查和结构化 `validation_report`。
- `sandbox/` 负责 run_id 沙箱目录、HTML 文件、检查报告和修复草稿。
- `workflow/plan_contract.py` 负责计划契约规范化、内置学科识别、互动类型识别、渲染栈规划、计划 JSON 解析和无模型配置时的最小可运行计划。
- `agents/instructions.py` 负责 Deep Agents system prompt 和任务 prompt 构建。
- `agents/topic_profile.py` 负责从教学主题中提取生成主色。
- `tools/` 内部负责 HTML 提取、清理、parser、JS checker、安全检查、长度检查和结构化 `validation_report`；不得依赖旧版共享 validator。
- `schemas/` 负责 AI互动实验专属请求响应模型定义。

主题色约定：

- 当前接口请求体只包含 `topic`；主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色。
- 主题色只作为动态计划和生成提示的输入，不保留静态 HTML 主题色覆盖层。

OpenMAIC Widget 链路改造默认方向：

- 保留 `POST /generate-aetherviz-spec`，不新增静态 HTML 接口。
- 计划对象继续以 `page_type: "interactive"` 为主，保留 `interactive_type` 兼容前端；必须补充 OpenMAIC 风格 `scene_outline`、`widget_outline`、`design_brief` 和 `widget_actions`，但不得破坏现有前端字段。
- `simulation`、`diagram`、`game` 使用独立 prompt 和独立 widget-config 约束；分型完整性校验不作为生产硬拦截。
- 生产生成链路只做基础结构、语法、安全和长度校验，避免因质量门过严阻断可继续通过 chat 改进的 HTML。
- HTML 输出目标控制在 36000 字符以内，硬上限为 40000 字符；生成、编辑或修复结果超过硬上限时必须触发一次自动修复压缩，修复后仍超限则返回 SSE `error`。
- 前端展示 `metadata.source`、`attempts`、`repaired`、`degraded`、`validation_warnings`，并支持向 iframe 发送 `SET_WIDGET_STATE`、`HIGHLIGHT_ELEMENT`、`ANNOTATE_ELEMENT`、`REVEAL_ELEMENT`。

### `tests/`

- 测试文件命名以 `test_*.py` 为准。
- AI互动实验相关测试优先放在 `tests/test_aetherviz.py`。
- LLM 通用配置与工具函数测试可放在 `tests/test_llm_service.py`。
- 新增或修改业务逻辑时，优先补充对应测试。
- 若无法补测，需在结果说明中明确原因和风险。

## 5. 开发约束

### Python 与依赖

- 使用 `uv` 执行安装、运行和测试，不要改用 `pip install` 作为默认路径。
- 依赖声明以 `pyproject.toml` 为准。
- `uv` 默认使用 `pyproject.toml` 中配置的阿里云 PyPI 源。
- 非用户明确要求，不主动升级大版本依赖。
- Docker 相关改动优先保持 `Dockerfile`、`docker-compose.dev.yml`、`docker-compose.prod.yml` 一致。

### 代码改动

- 保持现有分层：路由层、AI互动实验业务层、schema 层、模型调用与配置职责分离。
- 优先复用现有 AI互动实验模块，不重复创建相近职责的新文件。
- 不为“看起来更完整”而引入额外抽象。
- 除非任务明确要求，不新增非 AI互动实验接口，不修改环境变量命名或错误语义。

### 配置与密钥

- 严禁把真实密钥写入仓库文件。
- `.env.example` 只放示例占位值，不放真实凭据。

## 6. 常用命令

优先使用以下命令：

```bash
docker compose -f docker-compose.dev.yml up app
docker compose -f docker-compose.dev.yml run --rm test
docker compose -f docker-compose.prod.yml up -d app
uv sync --dev
uv run pytest
uv run uvicorn aetherviz_service.main:app --reload --port 10095
```

AI互动实验常用验证命令：

```bash
uv run pytest tests/test_aetherviz.py
uv run pytest tests/test_aetherviz.py tests/test_llm_service.py
```

## 7. 文档与接口变更

出现以下情况时，应同步更新 `README.md` 或相关文档：

- 新增、删除或修改 HTTP 接口。
- 修改环境变量。
- 修改本地启动方式。
- 修改结构目录或关键约定。
- 修改 AI互动实验生成链路、主题色提取、确定性降级路径或开发命令。
- 修改 Docker 启动方式。

若改动只涉及内部实现且外部行为不变，可不更新 README，但应确保命名与代码可读性足够清晰。

## 8. 测试与验证

默认验证策略：

1. 能跑测试时，优先运行最小必要测试。
2. 若修改影响接口或配置流程，优先补充或运行对应测试。
3. 若环境限制导致无法执行验证，必须明确说明未验证项。

## 9. 禁止事项

除非用户明确要求，否则不要执行以下操作：

- 新增或恢复非 AI互动实验功能。
- 恢复静态知识点命中或静态 HTML 文件目录。
- 修改系统级环境配置。
- 安装或卸载全局工具。
- 重写无关模块。
- 提交真实密钥、证书或令牌。
- 使用破坏性 git 命令回滚用户现有改动。

## 10. 结果说明要求

完成任务后，应尽量说明：

- 改了什么。
- 为什么这么改。
- 如何验证。
- 是否存在未覆盖风险。
