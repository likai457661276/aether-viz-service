# AGENTS.md

本文件定义 `ai-interactive-experiment` 仓库当前分支的项目级代理协作规范。

适用范围：仓库根目录及其所有子目录。

当用户指令与本文件冲突时，以用户指令为准。

## 1. 项目定位

这是一个基于 Python 3.12 的 FastAPI 服务，提供 AI互动实验互动教学可视化生成链路。

AI互动实验通过 `/generate-aetherviz-spec` 根据教学主题生成完整独立 HTML。服务优先命中静态 HTML 文件，并按主题中提取到的色值注入样式覆盖；未命中时先进行轻量规划，再生成自包含互动 HTML，生成结果校验失败时最多自动修复一次。

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
- `llm_service.py` 负责调用 OpenAI-compatible 大模型服务，供 AI互动实验 fallback 使用。
- `routers/` 负责 HTTP 路由层，不在此处堆积 AI互动实验生成、匹配、模板、校验等复杂业务逻辑。

### `aetherviz_service/routers/`

- `aetherviz.py` 负责 AI互动实验 HTTP 入参校验和响应封装，包括 `/generate-aetherviz-spec`、`/aetherviz-static-knowledge-points` 和 `/aetherviz-static-html`。
- 不新增非 AI互动实验路由，除非用户明确要求。

### `aetherviz_service/aetherviz/`

AI互动实验是独立子模块，负责互动教学可视化生成链路。新增 AI互动实验相关能力时，优先放入此目录，不在 `aetherviz_service/` 根目录新增平铺业务文件。

- `react.py` 负责 SSE 事件生成、静态命中分发、LLM 规划与互动 HTML fallback 编排、一次自动修复和错误收敛。
- `matcher.py` 负责服务端知识点关键词匹配；命中后应直接进入静态 HTML 返回路径。
- `knowledge_points.py` 负责静态知识点注册表，声明知识点 ID、标题、关键词、学科、知识域、年级和 `static_html_slug`。
- `static_html.py` 负责静态 HTML 文件路径映射、`utf-8-sig` 读取、DOCTYPE 基础检查、主题色提取与运行时主题色 CSS 覆盖注入。
- `html/` 存放可直接返回的完整独立 AI互动实验 HTML 文件，结构为 `html/{subject}/{point-slug}.html`。
- `fallback_planner.py` 负责未命中知识点时的学科识别、规划提示词构建、规划 JSON 解析和默认规划兜底。
- `fallback_validator.py` 负责未命中知识点时的互动 HTML 输出提取、代码围栏清理、截断内容闭合和基础长度检查。
- `validator.py` 负责 fallback HTML 的结构、安全、依赖、交互和可视化区域校验。
- `schemas/` 负责 AI互动实验专属请求响应模型定义。

新增可静态命中的 AI互动实验知识点时，应优先：

1. 在 `aetherviz_service/aetherviz/html/{subject}/` 下新增完整独立 HTML 文件。
2. 在 `knowledge_points.py` 注册知识点和 `static_html_slug`。
3. 在 `cover_images.py` 添加首屏封面截图 base64。
4. 在 `tests/test_aetherviz.py` 覆盖静态文件映射、主题色注入和命中后不调用 LLM 的行为。

静态 HTML 主题色约定：

- 当前接口请求体只包含 `topic`；主题色从 `topic` 中的 `#RRGGBB` 或中文颜色词提取，未提取到时使用默认色。
- 主题色适配通过后置 `:root` 覆盖层完成，不应批量替换整份 HTML。
- 学科语义色应保留独立 CSS 变量，不应被主题色覆盖。
- 静态 HTML 应保持完整独立，可直接保存和打开。

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
- 修改 AI互动实验静态 HTML 目录结构、知识点命中路径、主题色注入、fallback 路径或开发命令。
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
- 删除大量 AI互动实验静态 HTML 文件或目录。
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
