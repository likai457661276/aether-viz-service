# 离线评测模块

`evals/` 收拢 AetherViz 的本地和离线评测能力，不进入生产同步请求链路，也不创建或上传远程 LangSmith Dataset/Evaluator。

## 目录职责

```text
evals/
├── datasets/                 # 可提交的评测样本、失败 mutation 与阈值
├── evaluators/               # 单指标确定性和视觉 evaluator
├── targets/                  # 被测生成链路与浏览器执行封装
├── reporting/                # 基线比较和失败聚合
├── reports/                  # 可提交的基线、评测结果和阶段报告
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

从已脱敏的本地 Trace 导出构建视觉 Dataset：

```bash
uv run python evals/datasets/build_visual.py /tmp/trace.json \
  --output /tmp/aetherviz-visual-dataset.json
```

`datasets/recomposition/legacy-topics.jsonl` 保留早期开发/保留/挑战主题；当前跨维度回归入口默认使用 `datasets/recomposition/dataset.jsonl`。
