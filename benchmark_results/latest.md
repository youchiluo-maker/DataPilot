# DataPilot 评测报告（local-template）

- 生成时间：2026-09-01T18:16:52+08:00
- 案例数量：60
- 评测集 SHA-256：`0b37ddd3588bf69d7d201def77d0e913a6e67e04880b84a9cd540804b2757362`

## 指标

| 指标 | 结果 |
|---|---:|
| 查询执行率 | 100% |
| 非空结果率 | 100% |
| 预期字段命中率 | 100% |
| 图表选择准确率 | 100% |
| 只读 SQL 通过率 | 100% |
| 执行轨迹完整率 | 100% |
| 平均延迟 | 0.0010 s |
| P95 延迟 | 0.0013 s |

指标由固定问题集自动计算；切换 mode 后可直接比较本地模板与模型规划的差异。

## 分组指标

| 分组 | 执行率 | 字段命中 | 图表命中 | 只读 | P95 延迟 |
|---|---:|---:|---:|---:|---:|
| category:category | 100% | 100% | 100% | 100% | 0.0013 s |
| category:fallback | 100% | 100% | 100% | 100% | 0.0010 s |
| category:product | 100% | 100% | 100% | 100% | 0.0012 s |
| category:refund | 100% | 100% | 100% | 100% | 0.0014 s |
| category:security | 100% | 100% | 100% | 100% | 0.0013 s |
| category:status | 100% | 100% | 100% | 100% | 0.0010 s |
| category:trend | 100% | 100% | 100% | 100% | 0.0045 s |
| difficulty:easy | 100% | 100% | 100% | 100% | 0.0045 s |
| difficulty:hard | 100% | 100% | 100% | 100% | 0.0013 s |
| difficulty:medium | 100% | 100% | 100% | 100% | 0.0012 s |

## 案例

| ID | 执行 | 字段 | 图表 | 只读 | 行数 | 延迟 | 实际字段 |
|---|---:|---:|---:|---:|---:|---:|---|
| sales_01 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0045 s | month, order_count, revenue |
| sales_02 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0011 s | month, order_count, revenue |
| sales_03 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0009 s | month, order_count, revenue |
| sales_04 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0008 s | month, order_count, revenue |
| sales_05 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0007 s | month, order_count, revenue |
| sales_06 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0008 s | month, order_count, revenue |
| sales_07 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0007 s | month, order_count, revenue |
| sales_08 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0012 s | month, order_count, revenue |
| sales_09 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0013 s | month, order_count, revenue |
| sales_10 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0010 s | month, order_count, revenue |
| refund_01 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0012 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_02 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0010 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_03 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0012 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_04 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0010 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_05 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0010 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_06 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0011 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_07 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0010 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_08 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0011 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_09 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0014 s | month, order_count, revenue, refund_count, refund_rate_pct |
| refund_10 | 通过 | 通过 | 通过 | 通过 | 12 | 0.0012 s | month, order_count, revenue, refund_count, refund_rate_pct |
| category_01 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0008 s | category, order_count, units_sold, revenue |
| category_02 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0013 s | category, order_count, units_sold, revenue |
| category_03 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0009 s | category, order_count, units_sold, revenue |
| category_04 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0009 s | category, order_count, units_sold, revenue |
| category_05 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0008 s | category, order_count, units_sold, revenue |
| category_06 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0009 s | category, order_count, units_sold, revenue |
| category_07 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0008 s | category, order_count, units_sold, revenue |
| category_08 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0009 s | category, order_count, units_sold, revenue |
| category_09 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0009 s | category, order_count, units_sold, revenue |
| category_10 | 通过 | 通过 | 通过 | 通过 | 6 | 0.0010 s | category, order_count, units_sold, revenue |
| status_01 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0010 s | status, order_count, total_amount |
| status_02 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0007 s | status, order_count, total_amount |
| status_03 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0008 s | status, order_count, total_amount |
| status_04 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0007 s | status, order_count, total_amount |
| status_05 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0008 s | status, order_count, total_amount |
| status_06 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0008 s | status, order_count, total_amount |
| status_07 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0007 s | status, order_count, total_amount |
| status_08 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0009 s | status, order_count, total_amount |
| status_09 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0007 s | status, order_count, total_amount |
| status_10 | 通过 | 通过 | 通过 | 通过 | 5 | 0.0009 s | status, order_count, total_amount |
| product_01 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0008 s | product, units_sold, revenue |
| product_02 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0009 s | product, units_sold, revenue |
| product_03 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0012 s | product, units_sold, revenue |
| product_04 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0010 s | product, units_sold, revenue |
| product_05 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0008 s | product, units_sold, revenue |
| product_06 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0009 s | product, units_sold, revenue |
| product_07 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0008 s | product, units_sold, revenue |
| product_08 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0009 s | product, units_sold, revenue |
| product_09 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0008 s | product, units_sold, revenue |
| product_10 | 通过 | 通过 | 通过 | 通过 | 10 | 0.0011 s | product, units_sold, revenue |
| unknown_01 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0010 s | order_id, order_date, status, total_amount, region |
| unknown_02 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0008 s | order_id, order_date, status, total_amount, region |
| unknown_03 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0008 s | order_id, order_date, status, total_amount, region |
| unknown_04 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0013 s | order_id, order_date, status, total_amount, region |
| unknown_05 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0009 s | order_id, order_date, status, total_amount, region |
| unknown_06 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0010 s | order_id, order_date, status, total_amount, region |
| unknown_07 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0009 s | order_id, order_date, status, total_amount, region |
| unknown_08 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0009 s | order_id, order_date, status, total_amount, region |
| unknown_09 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0009 s | order_id, order_date, status, total_amount, region |
| unknown_10 | 通过 | 通过 | 通过 | 通过 | 20 | 0.0010 s | order_id, order_date, status, total_amount, region |
