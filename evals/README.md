# 离线评测模块

`evals/` 收拢 AetherViz 的本地和离线评测能力，不进入生产同步请求链路，也不创建或上传远程 LangSmith Dataset/Evaluator。

## 目录职责

```text
evals/
├── datasets/                 # 可提交的评测样本、失败 mutation 与阈值
│   ├── generate_baseline/    # 生成流水线路由 / 硬校验 / 确定性 repair 基线
│   ├── edit_html/            # 编辑诊断与端到端确定性样本
│   ├── ir_candidates/        # 尚无专用后端的 IR 设计缺口样本
│   ├── ir_routing/           # IR 路由回归
│   ├── number_line_ir/       # 数轴 IR repair 与动态集合 Runtime 回归
│   ├── constraint_geometry_ir/  # 约束几何 IR 确定性 repair / 排名回归
│   └── recomposition/        # 几何重排回归
├── evaluators/               # 单指标确定性和视觉 evaluator
├── targets/                  # 被测生成链路与浏览器执行封装
├── reporting/                # 基线比较和失败聚合
├── reports/                  # 本地忽略的评测结果和阶段报告
├── run_generate_baseline_eval.py
├── run_edit_html_eval.py
├── run_ir_routing_eval.py
├── run_number_line_ir_eval.py
├── run_constraint_geometry_ir_eval.py
└── run_eval.py               # 统一的重组链路评测入口
```

`targets` 只负责返回真实运行输出；`evaluators` 只读取运行输出和 Dataset 期望值；`run_eval.py` 负责编排、并发、阈值判断及结果落盘。

`datasets/recomposition/completion_cases/` 包含受控的确定性修复样本：

- `target-assembly-out-of-bounds.json`：唯一硬失败为目标拼合越界，要求
  `deterministic_target_bounds_completion` 至少尝试一次且成功率 100%
- `composite-waypoint-with-assembly-failure.json`：waypoint 与装配失败正交，只移除
  `teaching:missing_intermediate_geometry_stage`
- `construction-attach-edge-rect-pair.json`：construction 求解后可通过排名与拼合

`datasets/recomposition/feasibility_cases/` 覆盖计划级可行性预检（例如展开图元预算超限时
`routing.assess` 排除）。

## 常用命令

运行确定性评测：

```bash
uv run python evals/run_eval.py
```

运行真实模型和浏览器回归：

```bash
uv run python evals/run_eval.py \
  --repetitions 3 --live-model --browser --workers 3 \
  --output-dir evals/reports/stage6/current
```

比较确定性基线与真实模型结果：

```bash
uv run python evals/reporting/regression.py \
  --baseline evals/reports/stage6/deterministic/latest-summary.json \
  --current evals/reports/stage6/current/latest-summary.json \
  --failures evals/reports/stage6/current/failures.jsonl \
  --output evals/reports/stage6/regression-report.json
```

对失败样本做阶段归因聚类（F1–F8）：

```bash
uv run python evals/reporting/failure_clusters.py \
  --failures evals/reports/latest/failures.jsonl \
  --runs evals/reports/latest/runs.jsonl \
  --output evals/reports/latest/failure-classification.json
```

`run_eval.py` 结束时也会写入 `runs.jsonl` 与 `failure-classification.json`。
summary 中的 `stage_observations` 记录 model_calls / duration / repair / fallback /
矩阵计划 feasibility 误杀；`generation_strategies` 额外汇总 construction 与
completion_history 收敛轮次。

对单个 HTML 执行离线浏览器评测：

```bash
uv run python evals/targets/visual.py /path/to/generated.html \
  --report /tmp/visual-report.json
```

对 CSS 编辑执行修改前后语义门禁：

```bash
uv run python evals/targets/css_edit.py /path/to/before.html /path/to/after.html \
  --selector '#target' \
  --expected-style 'display=grid' \
  --interaction-selector '#action' \
  --report /tmp/css-edit-report.json
```

门禁会检查目标数量和可见性、computed style、主视觉、新增浏览器异常与交互动作，并通过目标打码截图阻断目标区域之外的意外变化。修改本身预期影响整体布局时使用 `--allow-outside-target-changes` 显式放宽截图约束。

运行 Edit HTML 的诊断单步与端到端确定性回归：

```bash
uv run python evals/run_edit_html_eval.py
```

运行生成流水线本地基线（路由命中、硬校验、确定性 repair）：

```bash
uv run python evals/run_generate_baseline_eval.py
```

`datasets/generate_baseline/pipeline_core.jsonl` 覆盖 IR/direct 路由样本、硬校验通过/失败夹具，以及可确定性修复的 HTML；默认不调用模型或远程 LangSmith。

运行全部已注册 IR 的路由回归：

```bash
uv run python evals/run_ir_routing_eval.py
```

`datasets/ir_routing/` 下的 JSONL 同时支持主题输入和完整计划输入，并强制覆盖注册表中的每个 IR 后端；新增 IR 但未添加正向路由样本时回归会失败。`number_line.jsonl` 由候选设计缺口集晋级，覆盖区间端点、不等式射线、绝对距离、有向位移和集合区间五类正向路由。

运行数轴 IR 确定性 repair 与动态集合 Runtime 回归：

```bash
uv run python evals/run_number_line_ir_eval.py
```

`datasets/number_line_ir/regression.jsonl` 保存脱敏后的真实模型 repair 失败和设计缺口样本。
当前覆盖动态端点交叉、intersection 非空到空集、union 单段到双段，以及开闭端点相遇。
集合拓扑通过本地浏览器执行 `derived_sets` Runtime 验证；默认不调用模型或远程 LangSmith。

运行约束几何 IR 确定性 repair / 排名回归：

```bash
uv run python evals/run_constraint_geometry_ir_eval.py
```

`datasets/constraint_geometry_ir/regression.jsonl` 保存脱敏后的真实模型失败族与设计样本。
当前覆盖无效 drag / 错误 refs、`A.x`/`C.x` 点字段别名与非法 angle、非常数端点 midpoint
表达式重写，以及 repair 后的候选排名选中。默认不调用模型或远程 LangSmith。

`datasets/ir_candidates/` 保留尚未被现有 IR 覆盖的设计缺口样本。几何约束族与直方图分箱、
经验分布对比等样本已晋升到 `datasets/ir_routing/`（分别由 `constraint_geometry_scene`、
`data_distribution_scene`、`probability_experiment_scene` 承接）。当前剩余缺口面向
`distribution_chart_scene` 尚未实现的连续密度 / 参数分布 / 重复抽样能力，记录目标能力与
应降级为 direct 的可观察行为，不属于已注册 IR 的通过率门禁。首批样本来源标记为
`design_gap_seed`；只有经过脱敏并获准写入仓库的真实 Trace 才能标记为 `trace_failure`。
实现某个候选能力时，应把对应样本迁移为正向路由与运行时回归，而不是继续断言 direct 降级。

`datasets/edit_html/diagnosis.jsonl` 验证诊断策略、影响域、hard change claim 覆盖和
claim 可绑定性；`datasets/edit_html/end_to_end.jsonl` 验证用户意图、preserve 约束、
HTML validation 和最终 intent metadata。默认使用已审查 fixture，不调用模型或远程
LangSmith 服务。真实模型风险抽样需显式开启：

```bash
uv run python evals/run_edit_html_eval.py --live-model --max-runs 3
uv run python evals/run_edit_html_eval.py \
  --suite end-to-end --live-model --browser --judge --max-runs 1
```

浏览器和 LLM-as-Judge 只用于有界风险抽样；judge 一次生成教学语义、视觉质量、编辑
相关性三个结构化分数，再由三个单指标 evaluator 分别读取。所有报告仅写入本地忽略的
`evals/reports/`，不得使用 LangSmith CLI/SDK 上传 Dataset、Evaluator 或实验。

从已脱敏的本地 Trace 导出构建视觉 Dataset：

```bash
uv run python evals/datasets/build_visual.py /tmp/trace.json \
  --output /tmp/aetherviz-visual-dataset.json
```

### Router Feedback 回收（人工闸门）

生产链路默认开启 IR 路由 shadow mode：确定性 `assess` 仍决定线上选型，Flash/LLM 仲裁结果以
`generation_route_llm_selected_backend` / `generation_route_llm_confidence` /
`generation_route_llm_required_capabilities` 结构化留痕。
离线回收只处理本地脱敏 Trace，禁止创建或上传远程 LangSmith Dataset。

```text
脱敏本地 Trace
    → build_ir_routing_regression.py
    → pending_review 候选 JSONL（outputs.selected_backend = null）
    → 人工标注 expected backend / 删除噪声
    → 合并进 datasets/ir_routing/*.jsonl
    → run_ir_routing_eval.py
```

从脱敏 Trace 挖掘路由分歧候选（shadow 分歧、LLM 选型被拒等）：

```bash
uv run python evals/datasets/build_ir_routing_regression.py /tmp/trace.json \
  --output /tmp/ir-routing-pending.jsonl
```

候选行带 `pending_review` / `trace_candidate` 标签，并在 `metadata` 中保留
`deterministic_selected` 与 `llm_selected_backend` 对照；**不会**自动写入
`outputs.selected_backend`。人工确认期望后端后，再把样本并入 `datasets/ir_routing/`，
最后运行 `uv run python evals/run_ir_routing_eval.py` 做回归。

`datasets/recomposition/legacy-topics.jsonl` 保留早期开发/保留/挑战主题；当前跨维度回归入口默认使用 `datasets/recomposition/dataset.jsonl`。

`datasets/html_contract/` 存放 HTML 运行时契约的失败模式样本（按互动类型与通用模式组织，不绑定单个知识点）。例如 `mount_lookup_false_positive.json` 回归 `getElementById` + 字符串常量挂载写法，避免再次误报 `empty_main_visual_mount`。
