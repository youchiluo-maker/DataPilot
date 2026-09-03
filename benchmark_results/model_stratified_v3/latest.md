# DataPilot 评测报告（deepseek:deepseek-ai/DeepSeek-V4-FLASH）

- 生成时间：2026-09-03T15:45:20+08:00
- 案例数量：7
- 评测集 SHA-256：`011bb2edfb81acb2604e646dea3e71bf69d8671d23e5c60d5756ff299d39de48`

## 指标

| 指标 | 结果 |
|---|---:|
| 查询执行率 | 100% |
| 非空结果率 | 100% |
| 预期字段命中率 | 100% |
| 结果集正确率 | 100% |
| 图表选择准确率 | 86% |
| 只读 SQL 通过率 | 100% |
| 执行轨迹完整率 | 100% |
| 降级率 | 43% |
| 平均延迟 | 33.3222 s |
| P95 延迟 | 120.5049 s |

指标由固定问题集自动计算；切换 mode 后可直接比较本地模板与模型规划的差异。

## 分组指标

| 分组 | 执行率 | 字段命中 | 结果正确 | 图表命中 | 只读 | P95 延迟 |
|---|---:|---:|---:|---:|---:|---:|
| category:category | 100% | 100% | 100% | 0% | 100% | 42.9840 s |
| category:fallback | 100% | 100% | 100% | 100% | 100% | 26.8905 s |
| category:product | 100% | 100% | 100% | 100% | 100% | 4.8302 s |
| category:refund | 100% | 100% | 100% | 100% | 100% | 120.5049 s |
| category:security | 100% | 100% | 100% | 100% | 100% | 0.0013 s |
| category:status | 100% | 100% | 100% | 100% | 100% | 13.4652 s |
| category:trend | 100% | 100% | 100% | 100% | 100% | 24.5795 s |
| difficulty:easy | 100% | 100% | 100% | 80% | 100% | 120.5049 s |
| difficulty:hard | 100% | 100% | 100% | 100% | 100% | 0.0013 s |
| difficulty:medium | 100% | 100% | 100% | 100% | 100% | 26.8905 s |

## 案例

| ID | 执行 | 字段 | 结果 | 图表 | 只读 | 行数 | 延迟 | 实际字段 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| category_01 | 通过 | 通过 | 通过 | 失败 | 通过 | 1 | 42.9840 s | category, order_count, units_sold, revenue |
| unknown_01 | 通过 | 通过 | 通过 | 通过 | 通过 | 20 | 26.8905 s | order_id, order_date, status, total_amount, region |
| product_01 | 通过 | 通过 | 通过 | 通过 | 通过 | 10 | 4.8302 s | product, units_sold |
| refund_01 | 通过 | 通过 | 通过 | 通过 | 通过 | 12 | 120.5049 s | month, order_count, revenue, refund_count, refund_rate_pct |
| unknown_03 | 通过 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0013 s | order_id, order_date, status, total_amount, region |
| status_01 | 通过 | 通过 | 通过 | 通过 | 通过 | 5 | 13.4652 s | status, order_count, pct |
| sales_01 | 通过 | 通过 | 通过 | 通过 | 通过 | 12 | 24.5795 s | month, order_count, revenue |
