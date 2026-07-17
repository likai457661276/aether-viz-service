# 离线评测模块

`evals/` 收拢 AetherViz 的本地和离线评测能力，不进入生产同步请求链路，也不创建或上传远程 LangSmith Dataset/Evaluator。

## 目录职责

```text
evals/
├── datasets/                 # 可提交的评测样本、失败 mutation 与阈值
│   ├── generate_baseline/    # 生成流水线路由 / 硬校验 / 确定性 repair 基线
│   ├── edit_html/            # 编辑诊断与端到端确定性样本
│   ├── ir_routing/           # IR 路由回归
│   └── recomposition/        # 几何重排回归
├── evaluators/               # 单指标确定性和视觉 evaluator
├── targets/                  # 被测生成链路与浏览器执行封装
├── reporting/                # 基线比较和失败聚合
├── reports/                  # 本地忽略的评测结果和阶段报告
├── run_generate_baseline_eval.py
├── run_edit_html_eval.py
├── run_ir_routing_eval.py
└── run_eval.py               # 统一的重组链路评测入口
```

`targets` 只负责返回真实运行输出；`evaluators` 只读取运行输出和 Dataset 期望值；`run_eval.py` 负责编排、并发、阈值判断及结果落盘。

`datasets/recomposition/completion_cases/` 包含受控的确定性修复样本。当前
`target-assembly-out-of-bounds.json` 保证候选的唯一硬失败为目标拼合整体越界，并要求
`deterministic_target_bounds_completion` 至少尝试一次、成功率为 100%，避免依赖真实模型随机产生越界结果。

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

`datasets/recomposition/legacy-topics.jsonl` 保留早期开发/保留/挑战主题；当前跨维度回归入口默认使用 `datasets/recomposition/dataset.jsonl`。

`datasets/html_contract/` 存放 HTML 运行时契约的失败模式样本（按互动类型与通用模式组织，不绑定单个知识点）。例如 `mount_lookup_false_positive.json` 回归 `getElementById` + 字符串常量挂载写法，避免再次误报 `empty_main_visual_mount`。
