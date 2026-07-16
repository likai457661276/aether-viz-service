# AetherViz 工作流与代码质量分析报告

- 生成时间：2026-07-16
- 分析范围：`aetherviz_service/`（约 13k 行 Python）、`tests/`、`evals/`、`scripts/`、根目录配置文件
- 分析方式：只读代码审查 + 全仓库 `grep` 交叉引用验证（区分"确认零引用"和"存在间接引用但可能冗余"两类结论），未修改任何文件
- 结论性质：本报告只做问题定位与风险说明，不包含代码改动；具体修复应按 `AGENTS.md` 的"小步、可审查"原则单独立项

## 修复落实状态（2026-07-16）

本轮已修复报告中的确定性安全、正确性、契约漂移和死代码问题：1.1～1.4、2.1、2.3～2.7、2.8 的 `source_topic` 冻结、3.1～3.4、3.6～3.7、3.9～3.10、4.1 的画布常量统一、4.2～4.3、4.6、4.9、6.1、7.3，以及第 8 节对应的协议相对 URL、多次修复、表征提示、非法模型类型和跨阶段语义稳定性测试缺口。生成和编辑现在共用公开的 `html_pipeline` 入口；无模型配置、编辑超时和输出预算不足会明确失败，计划 JSON 解析失败会显式进入带 `degraded` 标记的确定性规划降级，不再与正常模型计划混淆。

以下条目属于需要独立行为评估的大范围结构治理，本轮未做高风险重写：2.2 的完整修复编排迁移、4.1 的数值工具与 `stage_requirements` 全面统一、4.4 的 JS 词法器合并、4.5 的截断缝合专项复核、4.7～4.8/4.10/4.12 的检查器拆分与置信度审计，以及 7.1～7.2 的无状态 API 契约增强。其余低风险清理项不阻断本轮修复结果。

## 0. 结论摘要

项目整体架构清晰，`workflow -> agents -> tools` 的分层与 `AGENTS.md` 描述基本一致，`ruff check .` 全量通过，未发现明显的语法级死代码（未使用的 import/局部变量）。主要问题集中在四类：

1. **配置面"说谎"**：至少一处运行时参数（修复重试次数）无论用户如何配置都被硬编码上限吞掉，且无告警。
2. **安全校验存在可绕过的口子**：外部资源白名单只匹配 `https?://` 前缀，协议相对 URL（`//host/x.js`）可绕过整个白名单检查。
3. **职责与重复度问题**：`workflow` 层堆积了大量校验/修复策略实现；几何重排（`recomposition_*`）系列文件之间存在多处重复实现的几何/合法性判断逻辑；多处魔法数字（画布尺寸、字符预算、最短长度）散落在业务文件中而未进入 `constants.py`/`limits.py`。
4. **确认的死代码/半死路径**：`javascript_syntax.py` 中一条完整的"补丁引入未声明标识符"检测链路（约 100 行）从未被接入任何调用方；`instructions.py` 中的 `ADAPTIVE_LAYOUT_PROMPT` 常量被显式排除在提示词组装之外，仅靠一条测试断言"不得出现"续命；`knowledge_profile.py` 能推导出的部分 `representation_type`（`number_line`、`tree_diagram`、`dynamic_model`、`concept_map`）在 `instructions.py` 的提示词模块表中完全没有对应项；`plan_detection.py` 的 `select_animation_runtime()` 恒返回 `"gsap"`，`VALID_ANIMATION_RUNTIMES` 中的 `"native"` 是一条实质上不可达的路由。

以下按模块详细展开，每条均给出 `文件:行号`、问题描述、影响和改进方向。标注"✅ 已验证"表示本报告执行方已通过 `grep`/直接读码复核，而不仅是子分析建议。

---

## 1. 高优先级问题（建议优先处理）

### 1.1 ✅ 修复重试次数配置项被硬编码上限吞掉

- **位置**：`aetherviz_service/aetherviz/workflow/generate_workflow.py:559`
- **代码**：`max_attempts = min(max(settings.aetherviz_max_repair_attempts, 0), 1)`
- **配置**：`aetherviz_service/config.py:25` `aetherviz_max_repair_attempts: int = 1`（README 未声明其上限为 1）
- **问题**：无论运维把 `AETHERVIZ_MAX_REPAIR_ATTEMPTS` 配成 2、3 还是 10，模型修复循环最多只会跑 1 次；该值同时决定是否进入函数级修复（`generate_workflow.py:560`），因此配成 0 会同时关闭"函数级修复"和"整页模型修复"两条路径，配成 >1 则完全不产生任何效果。
- **影响**：配置项存在但行为被暗中限制，容易造成"调大了却没用"的排障困境；`Settings` 校验器（`config.py:55-72`）也没有对该字段做范围校验或告警。
- **改进方向**：去掉硬编码 `1`，改为直接使用配置值；如果产品策略上确实要求硬上限为 1，则应在 `Settings` 里加 `le=1` 校验或在启动日志中告警，而不是静默截断。

### 1.2 ✅ 外部资源白名单可被协议相对 URL 绕过

- **位置**：`aetherviz_service/aetherviz/tools/security_checker.py:38`
- **代码**：`if lower_name in {"src", "href", "srcset", "poster"} and re.search(r"https?://", lower_value):`
- **问题**：只有匹配到 `http://` 或 `https://` 字面前缀时才会进入白名单比对（`allowed_external_urls()`，来自 `security_policy.py`）。协议相对 URL（如 `<script src="//evil.example.com/x.js">`）、`data:` URL、相对路径完全不会命中这个正则，因此既不会被识别为"允许的 CDN"，也不会被识别为"非白名单外部资源"——直接被检查器无声放行。
- **对照**：`config.py:46-53` 对 CDN 配置项的校验反而更严格（禁止凭据、query、fragment），说明"配置侧安全" 与"生成物运行时校验安全" 强度不对等。
- **影响**：这是当前唯一的确定性安全边界，若模型输出包含协议相对 URL 引用任意脚本，服务端不会拦截,而是原样交付给前端 iframe。
- **改进方向**：使用 `urllib.parse.urlsplit` 规范化后再比较 scheme/netloc/path，显式拒绝协议相对（`//...`）、`data:`（脚本场景）、非 HTTPS 外链；`security_policy.py` 与 `security_checker.py` 应共用同一个 URL 规范化函数，而不是分别维护"配置侧严格、检查侧宽松"两套标准。

### 1.3 ✅ `javascript:` URL 检测使用子串匹配，`FORBIDDEN_PATTERNS` 扫描整页字符串

- **位置**：`security_checker.py:36-37`（`"javascript:" in lower_value`）、`security_checker.py:12-22`+`54-56`（`FORBIDDEN_PATTERNS` 对整段 HTML 做正则）
- **问题**：`javascript:` 判断是纯子串匹配，无法处理属性值中的空白/控制字符变体（部分浏览器在解析 legacy `javascript:` URL 时会跳过内部空白），也可能对包含该字符串的普通文案产生误报；`FORBIDDEN_PATTERNS` 对整页文本做正则匹配而不是限定在 `<script>` 内容里，`window['eva'+'l']`、间接引用等可以逃逸检测。
- **影响**：属于启发式安全检查的已知局限，不是回归问题，但与"安全检查"这个硬性阻断项的定位不完全匹配，建议在文档中明确其局限，避免被误认为是完整的脚本沙箱。
- **改进方向**：`javascript:` 改为对 URL 做 scheme 级解析；`FORBIDDEN_PATTERNS` 收窄到实际可执行的 `<script>` 文本范围。

### 1.4 ✅ `function_patch.py` 自实现了一套更弱的括号匹配，与 `javascript_object.py` 的实现重复且能力更弱

- **位置**：`aetherviz_service/aetherviz/tools/function_patch.py:260-309`（本地 `_matching_brace`）对照 `aetherviz_service/aetherviz/tools/javascript_object.py:23-93`（`matching_brace`）
- **问题**：两份独立实现"从某个 `{` 找到匹配 `}`"的状态机；`function_patch.py` 的本地版本不处理正则表达式字面量中的 `}`（如函数体内出现 `/\}/`），而 `javascript_object.py` 的版本已经处理。函数级修复（`function_patch.repair_function_targets`）在提取/替换函数体时使用的是较弱的版本。
- **影响**：当被修复函数体内包含正则表达式字面量且其中含有 `}` 时，函数级补丁的边界识别可能出错，导致替换范围错误或替换失败回滚（回滚本身是安全的，但会降低函数级修复的成功率）。
- **改进方向**：`function_patch.py` 改为直接调用 `javascript_object.matching_brace`，删除本地实现。

---

## 2. 工作流编排层（`workflow/`）问题

### 2.1 `plan_workflow.py` 与 `revise_plan_workflow.py` 编排逻辑几乎完全重复

- **位置**：`workflow/plan_workflow.py:12-55`、`workflow/revise_plan_workflow.py:12-62`
- **问题**：两者的 SSE 事件循环、`PlanningStreamResult` 指标抽取、`context.compressed` 分支结构基本相同，只是事件名称与文案不同。
- **影响**：任何一侧后续新增指标字段或调整压缩事件逻辑时，容易忘记同步另一侧。
- **改进方向**：抽出公共的 `_stream_plan_phase(event_names, stream_fn)`，`plan_workflow`/`revise_plan_workflow` 只保留薄包装和各自的事件命名。

### 2.2 `generate_workflow.py` 堆积了大量校验/修复策略实现，违反"工作流层只负责编排"的原则

- **位置**：`workflow/generate_workflow.py` 全文件约 1100 行；核心策略函数 `_attempt_repair_loop`（451-739 行）、`_attempt_function_repair`（742-846 行）、`_attempt_quality_repair`（335-419 行）、`_validate`/`_validate_impl`（955-1019 行）
- **问题**：候选接受策略（`_accept_hard_repair_candidate`）、报告裁剪（`_hard_error_only_report`/`_quality_only_report`）、修复轮次限制、SSE 事件裁剪全部写在 workflow 模块里，而不是委托给 `tools/` 层的服务对象。这与 `AGENTS.md` "工作流层负责编排，不堆积底层解析、检查或修复实现" 的原则存在明显偏离。
- **影响**：该文件已成为全仓库改动风险最高的单点；`edit_html_workflow.py` 还需要反向 `import` 其内部私有函数 `_run_html_workflow`（见 2.4），进一步加深耦合。
- **改进方向**：抽出独立的 `repair_orchestrator`（或 `validation_service`），把接受/拒绝策略和报告裁剪迁移过去；`generate_workflow.py` 只保留"调用编排 + yield SSE"。

### 2.3 修复循环里存在两套"候选是否无变化"的判定，语义不完全一致

- **位置**：`generate_workflow.py:859-867`（`_normalized_repair_candidate`，去 Markdown 代码块围栏后比较）、`edit_html_workflow.py:325-326`（`_normalized_html`，仅去除全部空白字符后比较）
- **问题**：两处都是在判断"模型输出是否等价于修复前/编辑前的 HTML"，但归一化规则不同：一个只处理围栏，一个只处理空白。理论上编辑场景如果模型输出被 Markdown 围栏包裹却内容不变，`_normalized_html` 不会识别为无变化。
- **改进方向**：抽出共享的 `normalize_html_for_compare()`，一次性说明是否需要去围栏、去空白，供两处复用。

### 2.4 `edit_html_workflow.py` 直接依赖 `generate_workflow.py` 的私有函数

- **位置**：`edit_html_workflow.py:36`（`from ...generate_workflow import _run_html_workflow`）、`edit_html_workflow.py:113`（调用处）
- **问题**：跨模块导入以下划线开头的"私有"符号，说明两个工作流事实上共享同一条 HTML 生成/校验/修复管线，但这层共享关系没有被显式建模成公共接口。
- **影响**：`generate_workflow.py` 任何一次内部重构（哪怶只是重命名）都可能直接破坏 `edit_html_workflow.py`；测试里也直接 mock 这个私有符号（`tests/test_aetherviz.py:1350`、`1436`），进一步把这个"坏边界"固化成了契约。
- **改进方向**：把 `_run_html_workflow` 提升为公共的 `html_pipeline.run_pipeline(...)`，放在独立模块中，供 `generate_workflow` 和 `edit_html_workflow` 平等调用。

### 2.5 `edit_html_workflow.py` 超时后仍可能把降级结果当作成功交付

- **位置**：`edit_html_workflow.py:212-218`（超时 `break`）、`edit_html_workflow.py:269-279`（仍然 `yield HtmlStreamResult(..., degraded=timed_out, ...)`）
- **问题**：模型流式输出超时后，只要已经拿到了完整的 `</html>`，代码就会把 `degraded=True` 的结果当作有效编辑结果返回，而不是像截断场景（`241-247` 行）那样直接失败。
- **影响**：与 README 中"整页重生成会在...`finish_reason=length/max_tokens`...时均明确失败并保留原页面"的表述存在细微差异——超时降级并不等同于 `finish_reason=length`，容易被理解成"更宽松"的一条隐藏路径。
- **改进方向**：明确产品策略——超时是否应该与截断同等对待直接失败，或者在 SSE `metadata.degraded` 之外，给前端一个更强的信号区分"完整但慢"和"截断"。

### 2.6 `plan_contract.py` 中 `_default_controls` 存在未使用参数

- **位置**：`workflow/plan_contract.py:457`（`def _default_controls(interactive_type: str, topic: str = "") -> list[dict]:`），函数体（458-471 行）从未引用 `topic`
- **问题**：函数签名暗示"控件会按主题定制"，但实现完全没有使用该参数；全仓库唯一调用处（`plan_contract.py:177`）传入了 `topic` 但被静默忽略。
- **改进方向**：删除该参数，或者实现"按主题挑选默认控件"的实际逻辑。

### 2.7 JSON 解析失败与"模型输出为空"两种情况被合并处理

- **位置**：`workflow/plan_contract.py:63-68`
  ```python
  try:
      parsed = json.loads(cleaned)
      if isinstance(parsed, dict):
          data = parsed
  except Exception:
      data = {}
  ```
- **问题**：`except Exception` 过宽，任何解析失败（包括编码问题、非预期异常）都会被静默吞掉并退回到空字典，进而触发 `_default_plan` 生成一份完全通用的确定性计划。
- **影响**：调用方（如 `planner_agent.py`）无法区分"模型本来就没输出" 和 "模型输出了坏 JSON"，两者都会表现为一份看起来完整、实际上与模型意图无关的默认计划，且不会被标记为需要重试或告警。
- **改进方向**：收窄为 `json.JSONDecodeError`；解析失败时向上传递明确的 `parse_failed` 标记，而不是静默退化。

### 2.8 计划字段在 `plan -> revise_plan -> approve_plan -> generate -> edit_html` 链路中多次被重新推导，存在漂移风险

- **位置**：`plan_contract.py:34-50`（`compact_plan_for_revision` 会丢弃 `scene_outline`/`widget_outline`/`knowledge_profile` 等字段再交给修订模型）；`agents/planner_agent.py` 的 `approve_plan` 处理会用 `plan["title"]` 回退当作 `topic`（当 `plan` 没有显式 `topic` 字段时）；`agents/runtime.py:114-115` 的 `generate` 分支同样用 `approved_plan.get("title")` 回退 `topic`；`edit_html_workflow.py:110-111` 又会用一份可能非常"瘦"的 `context.plan_summary` 重新跑一次 `normalize_plan`。
- **问题**：`AetherVizPlan` 契约中没有一个贯穿全生命周期、不被下游重新推导的 `source_topic` 字段；每个阶段都可能基于"当前可见的一小部分信息"重新计算 `subject`/`knowledge_profile`/`interactive_type`，五个阶段之间没有端到端的"同一计划对象字段保持不变"契约测试。
- **影响**：多数场景下用户确认的计划语义在各阶段被反复重新推导，结果通常一致，但在 `title` 被大幅改写、或 `edit_html` 阶段传入精简 `plan_summary` 的情况下，可能出现学科/知识画像/渲染栈与用户确认时不一致的静默漂移。
- **改进方向**：引入贯穿全生命周期的 `source_topic`（或计划 ID），在 approve 阶段"冻结"关键语义字段；补充一个端到端测试断言"同一计划对象核心字段在五阶段之间保持稳定"。

---

## 3. Agents / Prompt 层（`agents/`）问题

### 3.1 ✅ `knowledge_profile.py` 推导出的部分 `representation_type` 在提示词模块表中没有对应项

- **位置**：
  - 产出侧：`workflow/knowledge_profile.py:45`（`number_line`）、`:47`（`tree_diagram`）、`:153`（`dynamic_model`）、`:156`（`concept_map`）
  - 消费侧：`agents/instructions.py:185-195` 的 `REPRESENTATION_PROMPT_MODULES` 只覆盖 `coordinate_graph`、`geometric_construction`、`geometric_recomposition`、`symbolic_derivation`、`data_chart`、`process_model`、`object_motion`、`relation_network`、`discrete_manipulation` 九类。
- **验证**：已用 `grep` 确认 `dynamic_model`/`concept_map`/`number_line`/`tree_diagram` 在全仓库仅出现在 `knowledge_profile.py`（及 `plan_contract.py:893` 的一处默认字符串），未出现在任何 prompt 模块或校验逻辑中。
- **问题**：当画像命中这四类之一时，`system_prompt_for_interactive_type()`（`instructions.py:248-271`）里 `if representation in REPRESENTATION_PROMPT_MODULES` 的判断会直接跳过，不追加任何针对该表征类型的补充规则——画像"命中"了却没有产生任何生成侧的差异化提示。这类"表征分类存在但对生成无实际影响"与 `AGENTS.md` "知识画像是生成路由提示" 的定位不完全一致：既然要路由，就应该有对应的落地模块。
- **改进方向**：为四类补齐 `REPRESENTATION_PROMPT_MODULES` 条目；或者在未命中已实现模块时，显式降级到一个已覆盖的通用类型（如 `relation_network`），而不是静默跳过。

### 3.2 ✅ `ADAPTIVE_LAYOUT_PROMPT` 是已被移出组装路径但仍保留在源码中的常量

- **位置**：定义于 `agents/instructions.py:70-75`；`INTERACTIVE_HTML_SYSTEM_PROMPT` 的组装（`96-140` 行）没有引用它；`tests/test_aetherviz.py:1649-1671` 显式断言 `ADAPTIVE_LAYOUT_PROMPT` 的最后一行**不应该**出现在最终 prompt 里。
- **验证**：已用 `grep` 确认全仓库仅 `instructions.py`（定义）与 `test_aetherviz.py`（反向断言）两处引用，无任何正向使用。
- **问题**：这是一条被有意排除、只靠一条"负面测试"防止被误重新拼入的死常量，维护成本大于其价值（后来人很容易在重构时"顺手"把它拼回去，而不知道这是被刻意排除的）。
- **改进方向**：直接删除该常量与对应的排除断言，如果这部分规则仍有留存价值，应作为设计决策写进 `doc/`，而不是留一段死代码 + 一条反向测试。

### 3.3 ✅ `plan_detection.py` 中 `select_animation_runtime()` 恒定返回 `"gsap"`，`"native"` 是不可达路由

- **位置**：`workflow/plan_detection.py:114-115`；`VALID_ANIMATION_RUNTIMES = {"native", "gsap"}`（`:18`）
- **验证**：`grep "native"` 未发现除 schema 校验以外的任何选择逻辑会产生该值；只有当上游模型或前端在 `raw_plan.runtime.animation_runtime` 里显式写入 `"native"` 且通过 `normalize_plan` 的合法性检查（`plan_contract.py:90-92`）时，该值才会存活下来，但下游没有任何 `animation_runtime == "native"` 的分支处理——落地效果与 `"gsap"` 完全相同（因为 HTML 生成 prompt 里统一要求接入服务端 `AetherVizAnimationController`，GSAP 不可用时已经有 RAF fallback）。
- **问题**：这是一条"看起来可配置、实际恒定"的假配置面；`select_animation_runtime()` 函数签名（无参数）本身就暗示了它不依赖任何输入。
- **改进方向**：如果确实不需要按主题/渲染栈区分动画运行时，直接从 schema 中移除 `"native"` 选项，改为常量；如果未来要支持，应在 `select_animation_runtime` 里补齐判断逻辑。

### 3.4 ✅ `javascript_syntax.py` 的"补丁引入未声明标识符"检测链路是完整的死代码

- **位置**：`aetherviz_service/aetherviz/tools/javascript_syntax.py:41`（对外入口 `new_unresolved_identifiers`）及其专属依赖 `_inline_scripts`（53-61 行）、`_unresolved_identifiers`（64-91 行）、模块级常量 `_JS_KEYWORDS`/`_KNOWN_GLOBALS`（13-28 行）、`_strip_js_literals_and_comments`（94-145 行，唯一调用方就是 `_unresolved_identifiers`）
- **验证**：已用脚本在全仓库（含 `tests/`、`evals/`、`scripts/`）范围内对每个公开符号做零引用检查，`new_unresolved_identifiers` 是唯一一个确认全仓库零引用（连测试也没有）的公开函数；docstring 里描述的用途（"patch 后防止引入未声明的隐式全局状态，如 `lastFrameTime`"）与 `tools/function_patch.py` 的实际修复流程对照后，确认后者从未调用这条检查。
- **问题**：这是一套已经实现、写了详细文档字符串、但从未接入任何调用方的"未接线能力"，约 100 行代码、5 个符号完全不产生任何运行时效果。
- **改进方向**：二选一——(a) 在 `function_patch.repair_function_targets` 接受候选补丁前调用它做一次隐式标识符校验；(b) 确认不再需要后直接删除这条链路，只保留仍在被使用的 `check_javascript_syntax`/`_check_javascript_balance`/`_check_javascript_syntax_with_node`。

### 3.5 `model_factory.py` 中"规划模型独立配置"是假抽象

- **位置**：`agents/model_factory.py:17-22`（`has_planning_llm_config` 的实现与 `has_primary_llm_config` 完全等价）
- **问题**：函数名暗示"规划阶段可以有独立的模型凭据配置"，但实现上二者恒等，规划和 HTML/修复目前共用同一个 `OPENAI_API_KEY`/`OPENAI_BASE_URL`（这与 README 的描述一致），只是模型名不同。
- **影响**：调用方容易误以为存在独立的规划凭据开关。
- **改进方向**：合并为一个函数并去掉误导性命名；如果未来真的要支持独立凭据，再在 `Settings` 里加对应字段。

### 3.6 `model_factory.py` 对未知 `kind` 参数没有显式报错

- **位置**：`agents/model_factory.py:94-103`（按 `kind` 选择 token 预算/模型名的分支缺少 `else` 报错分支，未知取值会落到 `repair` 对应的配置）
- **问题**：如果调用方传入了拼写错误的 `kind`（例如 `"repiar"`），不会抛异常，而是静默使用 repair 的 token 预算与模型创建配置，这是一个隐蔽的错误来源。
- **改进方向**：为未知 `kind` 显式抛出 `ValueError`，并补充测试覆盖非法 `kind` 输入。

### 3.7 `function_repair_agent.py` 中函数补丁字符预算与 `tools` 层常量重复硬编码

- **位置**：`agents/function_repair_agent.py:35`（prompt 里硬编码字面量 `6000`）；对照 `tools/function_patch.py:13-14`（`MAX_FUNCTION_REPLACEMENT_CHARS = 6000`、`MAX_FUNCTION_REPLACEMENTS = 5`）
- **问题**：当前两处数值恰好一致，但 prompt 里的 `6000` 是裸字面量，不是从常量引用过去的；未来调整 `MAX_FUNCTION_REPLACEMENT_CHARS` 时很容易漏改 prompt 文案，造成"提示词说的预算" 和"实际强制的预算" 不一致。
- **改进方向**：prompt 用 f-string 注入常量，而不是手写数字。

### 3.8 `instructions.py` 中的 CDN 地址在模块导入时被"冻结"

- **位置**：`agents/instructions.py:15-16`（`GSAP_CORE_CDN = get_gsap_core_cdn_url()`、`KATEX_CSS_CDN, KATEX_JS_CDN = get_katex_cdn_urls()`）
- **问题**：这两个值在模块首次被 `import` 时就从 `settings` 读取并固化为模块级常量，之后即便运行时/测试通过 monkeypatch 修改了 `settings`，已经生成的 prompt 常量不会变化（除非重新 import 模块）。
- **影响**：主要在测试场景下可能造成"改了配置但断言仍然基于旧 CDN" 的隐性不一致；生产环境由于配置在启动时就固定，实际影响较小。
- **改进方向**：把 CDN 地址的读取延迟到 `build_*_prompt()` 函数体内部，而不是模块加载期。

### 3.9 `build_edit_html_prompt` 使用裸字面量 `40000` 截断当前 HTML

- **位置**：`agents/instructions.py:306`（`current_html[:40000]`）
- **问题**：`40000` 恰好等于 `limits.MODEL_HTML_HARD_LIMIT_CHARS`，但代码里没有引用该常量，只是字面量重复；且这是一次静默截断——如果 `current_html` 超过 4 万字符（例如历史累积的服务端装配开销导致业务 HTML 本身就接近硬上限），传给模型的当前页面会被无声截掉尾部，模型基于不完整的"事实基线"生成结果，可能破坏被截断部分的功能。
- **改进方向**：改为引用 `MODEL_HTML_HARD_LIMIT_CHARS`；超限时应直接拒绝编辑请求（复用已有的 `edit_budget_exceeded` 错误码语义），而不是静默截断输入。

### 3.10 `html_agent.py` 在无模型配置时返回的是"完整确定性占位 HTML"

- **位置**：`agents/html_agent.py:117-119`、`377-445`
- **问题**：当 `OPENAI_API_KEY` 未配置时，`html_agent` 不会直接失败，而是拼装一份结构合法、但与主题基本无关的确定性 HTML 并标记 `degraded=True`。这与 `AGENTS.md` "重试仍未获得完整、可校验 HTML 时必须明确失败，禁止把...低质量确定性页面作为降级结果交付" 的原则存在张力——虽然当前是面向"本地无 Key 也能跑通链路"的开发便利性设计，但它复用的是 `generate` 工作流的同一条正式路径，理论上可以直接进入生产响应。
- **影响**：如果生产环境因配置问题意外丢失了 `OPENAI_API_KEY`，最终用户会得到一份"看起来正常但内容空洞"的页面，而不是明确的错误提示。
- **改进方向**：在 `agents/runtime.py` 层对"未配置模型"这一情况做前置判断，直接返回 `model_unavailable` 错误（`edit_html_workflow.py:173-178` 已经是这么做的），而不是让 `html_agent` 内部静默降级；本地开发便利性可以通过单独的开发态开关实现。

---

## 4. 校验与修复工具层（`tools/`）问题

### 4.1 几何重排（`recomposition_*`）系列文件之间存在多处重复实现

- **位置概览**：`recomposition_ranking.py`、`recomposition_semantics.py`、`recomposition_assembly.py`、`recomposition_math.py`、`recomposition_runtime.py`、`recomposition_waypoints.py`、`recomposition_contract.py`、`recomposition_ir.py`（共约 3450 行，是 `tools/` 目录中体量最大的子系统）
- **具体重复点**：
  - `recomposition_ranking.py:112-114` 排名时会重新跑一遍几何/拼合计算，而 `recomposition_semantics.py:49-54` 内部又会再跑一遍 `recomposition_math`/`recomposition_assembly`，导致同一个候选在一次排名流程里被重复计算多次（CPU 开销，非正确性问题）。
  - 画布尺寸 `960x560` 在 `recomposition_assembly.py:21-22`、`recomposition_ranking.py:20-21`、`recomposition_runtime.py:101`、`recomposition_waypoints.py:103-104`（写成 `24/936/536`，是加了安全边距后的派生值）分别硬编码了四次，没有一个共同来源。
  - `_number`/`_finite`/`_issue` 一类的数值校验小工具在 `recomposition_ir.py`、`recomposition_assembly.py`、`recomposition_math.py`、`recomposition_semantics.py`、`recomposition_ranking.py`、`recomposition_runtime.py` 六个文件中分别有各自的实现，且行为不完全一致（有的遇到非法输入直接抛错，有的走 fallback 值）。
  - `_stage_requirements` 的归一化在 `recomposition_ir.py:571-593`（会重新推导 `role`/`at`/`id`）和 `recomposition_waypoints.py:134-137`（只是原样过滤）之间存在两套不同语义，与 `AGENTS.md` "计划归一化...应保持语义一致，避免同一规则在多处独立写死" 的原则有出入。
- **改进方向**：
  1. 把画布尺寸、字符预算等纯数值常量集中到 `tools/recomposition_constants.py`（或纳入现有 `limits.py`）。
  2. 抽出共享的 `recomposition_types.py` 承载数值校验小工具，统一"非法输入抛错 vs fallback" 的策略。
  3. `recomposition_semantics.py` 改为接受调用方已经算好的 math/assembly 结果作为可选参数，避免重复计算；`stage_requirements` 只保留 `recomposition_ir.py` 一份归一化实现，`waypoints` 复用它。

### 4.2 `recomposition_semantics.py` 与 `recomposition_math.py` 中存在未被消费的返回字段

- **位置**：`recomposition_semantics.py:268`（返回的 `score` 字段）；`recomposition_math.py:139-140`（`requested_relation_checks`/`available_relation_checks`）
- **验证**：已确认全仓库没有任何调用方读取这两个字段——排名使用的是 `recomposition_ranking.py` 里另一套独立计算的加权分数，跟 `semantics.py` 返回的 `score` 完全无关；`math.py` 的两个字段除定义处外无引用，实际只用到了同一份返回值里的 `relation_coverage`。
- **问题**：这类"计算了但没人用" 的返回字段容易误导后来的维护者以为它们承担了某种业务决策作用。
- **改进方向**：确认无用后直接删除；如果是为未来诊断预留的字段，应在文档中说明并至少接入日志/trace。

### 4.3 `deterministic_repair.py` 允许 `report=None`，隐含"盲目修复"行为

- **位置**：`aetherviz_service/aetherviz/tools/deterministic_repair.py:75-109`
- **问题**：函数签名允许 `report` 为空；当 `report` 为空但 `plan` 非空时，代码仍然会执行插入播放/暂停/重置控件等"结构性修复"步骤，而不是直接判定为无需修复的 no-op。
- **影响**：调用方如果误传了 `None`，得到的不是"什么都不做"，而是一次隐式的结构性改写，容易造成非预期的 HTML 变更。
- **改进方向**：把 `report` 改为必填参数；或在 `report is None` 时显式返回原始 HTML（no-op），把当前的"隐式行为"变成显式契约。

### 4.4 `html_output.py` 与 `javascript_syntax.py` 各自维护一套 JS 词法状态机

- **位置**：`html_output.py:24-150`（`_balance_js_brackets` 及其字符串/注释状态机）对照 `javascript_syntax.py:178-261`（`_check_javascript_balance`/`_strip_js_literals_and_comments` 附近逻辑）
- **问题**：两处都在实现"遍历字符流，正确跳过字符串/模板字符串/注释后再统计括号平衡"，但细节不完全一致（例如对模板字符串内 `${}` 表达式的处理程度不同）。
- **影响**：同一段 JS 在两个检查点上可能得到不同的"是否平衡"结论,增加维护和调试成本。
- **改进方向**：抽成公共的 `tools/javascript_lexer.py`，两处都复用同一个词法扫描器。

### 4.5 `html_output.py` 对截断输出的"自动缝合"与"应明确失败"的产品策略存在张力

- **位置**：`html_output.py:202-232`（检测到缺少 `</script>`/`</html>` 时自动补齐结束标签）对照 `html_parser.py:14-22`（解析器强制要求 `</html>` 结尾）
- **问题**：`html_output.py` 会在业务 HTML 缺少收尾标签时主动"缝合"补全，这段缝合后的 HTML 可以通过 `html_parser.py` 的结构检查（因为标签已经被补上了），但缝合本身并不能恢复被截断丢失的功能代码——即"结构合法" 不代表"语义完整"。
- **影响**：与 `AGENTS.md` "遇到可重试的传输中断或不完整输出时...重试仍未获得完整、可校验 HTML 时必须明确失败" 的要求存在潜在冲突，取决于这段缝合逻辑是否只在内部重试链路中使用、且最终仍会被 `truncated` 标记正确捕获并导向失败（需要结合 `generate_workflow.py` 里 `source_truncated`/`CANDIDATE_FATAL_ERROR_TYPES` 的实际生效路径确认，本报告未能在只读分析范围内完全排除这一风险，建议作为专项复核)。
- **改进方向**：明确"缝合"只应作为内部候选评估的中间态，最终交付前必须保留/检查 `truncated=true` 标记，不应该让"结构补全后的候选"绕过"截断即失败"的硬性策略。

### 4.6 多处魔法数字应迁入 `constants.py`/`limits.py` 但目前散落在业务文件中

- **位置**：
  - `html_output.py:235-238`：最短 HTML 长度硬编码为 `150` 字符。
  - `function_patch.py:13-14`：`MAX_FUNCTION_REPLACEMENTS = 5`、`MAX_FUNCTION_REPLACEMENT_CHARS = 6000`。
  - `recomposition_contract.py:14-15`：Scene/IR 长度上限 `12000`/`8000`。
  - `recomposition_ir.py:12`：`GEOMETRY_IR_MAX_CHARS = 10000`。
  - `recomposition_ranking.py:22-32`、`198-233`、`263-264`：缩放范围 `[0.05, 8]`、"舒适区" 24px 边距、piece 数量 `3~24`、若干动词打分表和权重系数。
- **问题**：这些数值大多与"输出预算""几何合法性阈值" 相关，理论上属于 `AGENTS.md` 中"外部资源、安全白名单、fallback 和输出限制必须从统一配置或常量读取" 覆盖的范畴，但当前分散在各自文件里，缺少统一的可发现入口。
- **改进方向**：不要求全部迁移（部分属于算法内部超参数，硬编码在实现文件里也合理），但至少应将"输出字符预算类" 数值（长度上限、替换字符上限）统一收纳进 `limits.py`；几何排名的启发式权重建议整理进一个独立的、带注释说明来源的配置块，方便审阅和调参。

### 4.7 `widget_contract_checker.py` 体量过大且与 `animation_lifecycle_checker.py` 存在重复的脚本抽取/契约判断逻辑

- **位置**：`widget_contract_checker.py`（约 1052 行，全仓库最大的单文件）；重复点见 `animation_lifecycle_checker.py:46-58` 与 `widget_contract_checker.py:78-90`、`117-146`（两者都各自实现了一遍"提取业务 `<script>` 内容" 的逻辑）
- **问题**：动画控制器契约相关的规则（`shadowed_animation_controller`、`bound_gsap_callback_context_mismatch` 等）分散在两个文件中，同一条业务违规可能被两个检查器分别命中（重复报告）或分别漏判（一边更新了规则，另一边没有同步）。
- **改进方向**：抽出共享的 `extract_inline_scripts(html, *, exclude_service_contracts=True)` 工具函数；评估是否可以把动画生命周期相关的契约规则统一收敛到一个模块，`widget_contract_checker.py` 按主题（widget-config 结构 / stage 挂载 / GSAP 契约 / SVG 契约）拆分为若干更小的文件，降低单文件复杂度。

### 4.8 `REQUIRED_WIDGET_ACTIONS` 检查使用子串匹配，容易误判

- **位置**：`widget_contract_checker.py:106-108`
- **问题**：判断"四类 iframe action 是否已处理" 时，直接检查动作名字符串（如 `"SET_WIDGET_STATE"`）是否出现在业务脚本文本中，不区分这段文本出现在注释、字符串常量还是真实的 `case`/`if` 分支里。
- **影响**：可能产生假阴性（模型在注释里写了这些字符串但没真正实现分支处理，检查器误判为"已处理"）或假阳性（真实实现使用了不同的字符串拼接方式）。
- **改进方向**：至少限定匹配范围到 `message` 事件处理函数体内部，理想情况下用简单的语句级解析代替全文子串匹配。

### 4.9 `js_checker.py` 允许 `type="module"` 脚本，但 `security_checker.py` 禁止 `import`，两者策略不一致

- **位置**：`js_checker.py:35-41`、`security_checker.py:16`（`FORBIDDEN_PATTERNS` 中的 ES Module import 规则）
- **问题**：一个模块脚本（`<script type="module">`）可能顺利通过语法检查，却因为内部使用了 `import` 语句被安全检查拒绝；反过来，如果模型使用动态 `import()` 表达式而不是静态 `import` 语句，可能绕过安全检查却依然是模块化脚本。
- **改进方向**：明确产品策略——如果不打算支持 ES Module，`js_checker.py` 应该直接拒绝 `type="module"`；如果要支持，应该配套评估 CSP/沙箱策略，而不是让两个检查器各说各话。

### 4.10 `discipline_consistency_checker.py` 与 `widget_contract_checker.py` 存在重复的"主视觉挂载点是否存在" 判断

- **位置**：`discipline_consistency_checker.py:35-40`、`53-65` 对照 `widget_contract_checker.py` 中的 stage 挂载检测逻辑
- **问题**：两个文件各自用正则/字符串匹配猜测 SVG/Canvas 是否被正确挂载到 `#aetherviz-stage`，属于同一类判断的重复实现，维护成本高且容易出现两者结论不一致的情况。
- **改进方向**：抽出共享的"主视觉挂载证据" 判定函数，供两个检查器复用。

### 4.11 `layout_contract.py` 中 `sanitize_business_css` 是仅供内部调用的函数却暴露为公开 API

- **位置**：`layout_contract.py:287`（定义）、`:101`（调用），全仓库无其他调用方
- **问题**：不是死代码，但函数命名未加下划线前缀，扩大了公共 API 表面，容易被误认为是可以从外部安全调用的通用工具。
- **改进方向**：如果确认无外部使用场景，改名为 `_sanitize_business_css`。

### 4.12 `validation_report.py` 的置信度/阻断降级机制被多数检查器忽略

- **位置**：`validation_report.py:60-78` 定义了 `confidence`/`blocking` 字段支持"不确定判断降级为 warning"；实际只有 `animation_lifecycle_checker.py:195-258` 在使用这两个字段。
- **问题**：`AGENTS.md` 明确要求"学科语义、视觉质量、表征匹配等启发式检查默认只产生 warning，不应因不确定判断阻断可继续编辑的产物"，但目前只有动画生命周期检查器实现了这套降级机制，其余启发式检查器（如 widget 契约里的部分规则）仍直接写入 `errors`，缺少统一的置信度标注。
- **改进方向**：评估 `widget_contract_checker.py`/`layout_contract_checker.py` 中哪些规则属于"确定性硬错误" 、哪些属于"启发式判断"，为后者统一补充 `confidence`/`blocking` 标注，而不是让"是否降级为 warning" 完全取决于该规则被写入 `errors` 还是 `warnings` 列表的硬编码位置。

---

## 5. 确认的死代码 / 无用代码清单

以下条目均已在全仓库范围内（包含 `tests/`、`evals/`、`scripts/`，排除 `.venv/`、`__pycache__/`）执行零引用验证：

| 符号 / 常量 | 位置 | 结论 | 建议 |
|---|---|---|---|
| `new_unresolved_identifiers` 及专属依赖链（`_inline_scripts`、`_unresolved_identifiers`、`_strip_js_literals_and_comments`、`_JS_KEYWORDS`、`_KNOWN_GLOBALS`） | `tools/javascript_syntax.py:13-28, 41-145` | 全仓库零引用（含测试） | 接入 `function_patch` 修复校验，或删除 |
| `ADAPTIVE_LAYOUT_PROMPT` | `agents/instructions.py:70-75` | 生产路径零引用，仅被一条"不应出现"的反向测试引用 | 删除常量与对应排除断言 |
| `_default_controls` 的 `topic` 参数 | `workflow/plan_contract.py:457` | 参数从未在函数体内被使用 | 删除参数或补齐实现 |
| `select_animation_runtime()` 的 `"native"` 分支 | `workflow/plan_detection.py:114-115` | 函数体无分支，恒返回 `"gsap"`；`"native"` 只能被动接受、无处理逻辑 | 从 schema 移除或补齐实现 |
| `recomposition_semantics.py` 返回的 `score` 字段 | `tools/recomposition_semantics.py:268` | 全仓库无读取方 | 删除或接入诊断日志 |
| `recomposition_math.py` 返回的 `requested_relation_checks`/`available_relation_checks` | `tools/recomposition_math.py:139-140` | 除定义外无引用 | 删除或接入诊断日志 |

未发现整模块级别的死文件——`workflow/`、`agents/` 下的每个文件都经由 `agents/runtime.py` 或对应工作流被实际引用；`ruff check .`（含 `F401` 未使用 import、`F841` 未使用局部变量规则）全量通过，说明不存在语法层面的明显死代码。

---

## 6. 配置与常量层（`config.py` / `constants.py` / `limits.py`）

### 6.1 `constants.py` 中存在两套名字指向同一语义的常量

- **位置**：`aetherviz_service/aetherviz/constants.py:6-12`
  ```python
  MODEL_HTML_TARGET_CHARS = _limits.MODEL_HTML_TARGET_CHARS
  MODEL_HTML_HARD_LIMIT_CHARS = _limits.MODEL_HTML_HARD_LIMIT_CHARS
  ...
  HTML_OUTPUT_TARGET_CHARS = MODEL_HTML_TARGET_CHARS
  HTML_OUTPUT_HARD_LIMIT_CHARS = MODEL_HTML_HARD_LIMIT_CHARS
  ```
- **说明**：代码注释已经说明这是"兼容既有导入"，属于有意保留的历史别名，不是意外重复。但目前 `instructions.py` 同时使用了 `HTML_OUTPUT_TARGET_CHARS`/`HTML_OUTPUT_HARD_LIMIT_CHARS` 两个名字，其他新代码（如 `edit_html_workflow.py`）却直接从 `limits.py` 导入 `MODEL_HTML_HARD_LIMIT_CHARS`/`FULL_HTML_OUTPUT_RESERVE_CHARS`，同一个仓库内两套命名并存。
- **改进方向**：既然是历史兼容别名，建议在 `constants.py` 顶部加一句更明确的"仅供旧代码兼容，新代码请直接使用 `limits.py`" 说明，并在下一次涉及这些常量的改动中顺手把 `instructions.py` 迁移到 `limits.py` 的命名，逐步收敛成一套名字。

### 6.2 字符/Token 估算系数是粗粒度的全局常量

- **位置**：`limits.py:12`（`ESTIMATED_OUTPUT_CHARS_PER_TOKEN = 3`），被 `estimated_output_capacity_chars()` 使用，进而驱动 `edit_html_workflow.py:293-295` 的编辑预算判断（`_has_full_edit_budget`）。
- **问题**：中文字符与英文/HTML 标签的 token 密度差异较大，固定系数 `3` 是一个粗略估算；如果实际业务 HTML 中英文标签/属性占比升高，用该系数计算出的"预算是否充足" 判断可能与真实模型行为出现偏差（偏保守则误杀本可完成的编辑请求，偏乐观则可能提交一个注定会超预算截断的请求）。
- **改进方向**：这属于产品可接受的工程简化，不是 bug，但建议补充针对当前生产模型的实测校准数据，并在 README/`limits.py` 注释中说明该系数的适用范围。

---

## 7. API / SSE 层（`api/`）问题

### 7.1 计划槽位冗余：`plan` / `approved_plan` / `current_plan` 三者按 `phase` 互斥使用但服务端不做交叉校验

- **位置**：`api/schemas.py:15-23`（三个字段）、`26-49`（按 `phase` 分别校验必填字段，但没有校验"当前传入的计划是否等于上一阶段确认过的计划"）
- **问题**：`approve_plan` 之后传给 `generate` 的 `approved_plan` 在服务端没有与 `approve_plan` 阶段确认过的计划做比对（因为服务端本身不持久化计划状态，这是有意为之的无状态设计），前端如果传错槽位（例如把未确认的草稿传成 `approved_plan`）不会被拦截。
- **影响**：这更多是一个"契约脆弱点" 而非当前的实际 bug——只要前端严格按 `README.md` 描述的阶段顺序调用即可规避，但服务端也没有任何兜底校验。
- **改进方向**：如果要加强健壮性，可以在 `approved_plan`/`plan` 中要求携带一个 `status` 字段并在 `generate`/`approve_plan` 阶段校验其取值，但需要评估这是否与当前"服务端无状态" 的设计目标冲突。

### 7.2 `REQUIRED_PLAN_FIELDS` 覆盖范围较窄

- **位置**：`api/schemas.py:12`（`REQUIRED_PLAN_FIELDS = ("interactive_type", "subject", "title", "goal")`）
- **问题**：只校验四个基础字段是否存在，`knowledge_profile`/`interactive_spec`/`recomposition_spec` 等更关键的语义字段缺失时，会在后续 `normalize_plan` 里被静默填充默认值，而不是在请求校验阶段就明确拒绝。
- **改进方向**：视产品策略决定是否需要加强——如果"允许精简计划、由服务端补全" 是有意设计（README 的示例请求确实展示了完整字段，暗示这是期望路径），则应在文档中更明确说明"必填四项之外的字段缺失会被静默填充默认值" 这一行为，避免调用方误以为传入的计划会被完整保留。

### 7.3 `schemas.py` 中存在两段几乎相同的 `approve_plan`/`generate` 校验分支

- **位置**：`api/schemas.py:36-39`（两个连续的 `if self.phase == "approve_plan":`）、`40-43`（两个连续的 `if self.phase == "generate":`）
- **问题**：属于小的风格冗余——完全可以合并成一个 `if` 块，当前拆成两段没有功能上的必要性，只是略微增加了阅读成本。
- **改进方向**：合并为单个条件块，非紧急。

---

## 8. 测试覆盖缺口

结合上述发现，以下缺口建议在后续补测试时优先考虑（均为"当前行为已确认存在但缺少直接测试断言" 的场景，不是要求新增功能）：

1. **跨阶段计划字段稳定性**：目前 `plan`/`revise_plan`/`approve_plan`/`generate`/`edit_html` 各阶段都有独立的 happy-path 测试，但没有一个端到端测试断言"同一份计划核心字段（`subject`/`knowledge_profile`/`interactive_type`）在五个阶段之间保持不变"。
2. **`AETHERVIZ_MAX_REPAIR_ATTEMPTS > 1` 时的实际行为**：当前没有测试覆盖"配置值大于 1 时是否真的产生了更多次重试"，如果补上这个测试会立即暴露 1.1 节的问题。
3. **协议相对 URL / `data:` URL 的安全检查**：`tests/test_hardening.py` 目前覆盖的是绝对 HTTPS 外链场景，没有覆盖 `//host/x.js` 或 `data:text/html` 场景（对应 1.2 节）。
4. **孤儿 `representation_type`（`number_line`/`tree_diagram`/`dynamic_model`/`concept_map`）命中后的 prompt 组装结果**：目前只有 `geometric_recomposition` 有专门测试。
5. **`edit_html` 阶段传入稀疏 `plan_summary` 时的漂移行为**：目前编辑契约测试主要针对 HTML 本身，没有测试 `plan_summary` 缺失关键字段时对布局装配/校验的影响。
6. **`model_factory.create_chat_model` 传入非法 `kind`**：目前没有测试覆盖 3.6 节描述的静默回落行为。

---

## 9. 优先级建议（供后续排期参考）

| 优先级 | 事项 | 对应章节 |
|---|---|---|
| P0（安全/正确性） | 修复外部资源白名单协议相对 URL 绕过 | 1.2 |
| P0（安全/正确性） | 修复 `AETHERVIZ_MAX_REPAIR_ATTEMPTS` 被硬编码为 1 的问题，或在文档/校验中明确该上限 | 1.1 |
| P1（正确性） | `function_patch.py` 改用 `javascript_object.matching_brace` | 1.4 |
| P1（架构） | 拆分 `generate_workflow.py` 的修复编排逻辑到独立服务对象 | 2.2 |
| P1（架构） | 消除 `recomposition_ranking`/`recomposition_semantics` 之间的重复求值，统一画布尺寸等常量 | 4.1 |
| P1（清理） | 删除 `ADAPTIVE_LAYOUT_PROMPT`、`javascript_syntax.py` 死代码链路，或将其真正接入调用方 | 3.2、3.4 |
| P2（一致性） | 补齐 `REPRESENTATION_PROMPT_MODULES` 缺失的四类映射，或在未命中时显式降级 | 3.1 |
| P2（一致性） | 统一 `check_javascript_syntax`/校验报告等跨文件的返回值形态 | 4.4、4.9 |
| P2（收尾） | 收敛画布尺寸/字符预算类魔法数进 `limits.py`；合并 `schemas.py` 中重复的 `if` 分支 | 4.6、7.3 |

---

## 10. 分析局限性说明

- 本报告基于只读静态分析和全仓库文本级引用检索，未运行完整的 `evals/run_eval.py` 真实模型回归或浏览器可视化回归，因此无法验证第 4.5 节"缝合截断输出" 相关的运行时实际影响范围，标注为待专项复核。
- `ruff check .` 已确认通过（无 `F401`/`F841` 等静态死代码），但 ruff 规则集不覆盖"公开函数在全仓库范围内零引用" 这类跨文件死代码，第 5 节的结论完全依赖人工 `grep` 交叉验证，如后续新增调用方，应重新核实。
- 未执行 `uv run pytest`；本报告中标注"✅ 已验证" 的条目均通过直接读码 + `grep` 复核，未标注的条目主要来自结构化子分析、建议在采纳前按需二次确认对应行号（本报告成稿时代码状态为准）。
