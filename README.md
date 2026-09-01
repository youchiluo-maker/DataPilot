# DataPilot：自然语言数据分析 Agent

DataPilot 是一个独立的自然语言数据分析 Agent。它面向电商业务分析场景，把自然语言问题转换为可审计的只读 SQL，再根据真实查询结果生成摘要、图表和执行轨迹。

## 能力

- 内置可复现 SQLite 数据集：30 个用户、12 个商品、180 条订单；
- 本地模板支持月度趋势、退款率、品类表现、订单状态和热销商品分析；
- 支持上传多个 CSV，在当前会话内自动建表、推断字段类型并生成动态 Schema；
- 可选 DeepSeek JSON 查询规划，模型不可用时自动降级到本地模式；
- 模型 SQL 执行失败时最多自动修复 1 次，并把失败原因、修复过程写入执行轨迹；
- SQL 单语句校验、危险操作拦截、SQLite authorizer 二次只读防护和表范围 allowlist；
- 查询最大返回行数和执行超时控制；
- 真实结果摘要、原始数据表、图表、SQL 和执行轨迹；
- 统一 `AnalysisService` 服务层，网页和 HTTP API 共用同一条分析链路；
- 每次运行生成 `run_id`，将状态、耗时、SQL、模型、降级和警告写入本地审计库；
- 提供 FastAPI 健康检查、分析接口和运行记录接口，可用 Docker Compose 启动双入口；
- pytest 覆盖数据一致性、SQL 安全、Agent 降级和模型修复流程；
- 60 条固定业务问题评测集，支持本地基线、DeepSeek smoke test 和按场景分组指标。

## 自定义 CSV

在网页左侧将数据源切换为“上传 CSV”，选择一个或多个文件并点击“加载为只读数据源”。文件只在当前 Streamlit 会话的内存中解析，不会写入项目目录；每次刷新或关闭会话后数据都会清除。

导入约束：最多 5 个文件、单文件不超过 5 MB、总大小不超过 15 MB、每个文件最多 100,000 行和 100 列；支持 UTF-8 / GB18030。文件名和字段名会规范化为安全的 SQLite 标识符，页面会同时展示原始文件名、规范化表名和字段映射。

自定义数据建议选择“DeepSeek 规划”模式。Agent 会把动态 Schema 交给模型，再经过只读 SQL 校验、表范围 allowlist、最大行数和超时控制；如果模型不可用，离线模式只返回首个表的安全预览。

## 可重复评测

运行 60 个固定业务问题的本地基线：

```powershell
Set-Location D:\DATAPILOT
.\.venv\Scripts\python.exe run_benchmark.py
```

评测会统计查询执行率、非空结果率、预期字段命中率、图表选择准确率、只读 SQL 通过率、执行轨迹完整率、平均延迟和 P95 延迟，并按意图类别、难度输出分组指标，更新 `benchmark_results/latest.*`。

先用 3 条案例做 DeepSeek smoke test（会消耗 API 额度）：

```powershell
Set-Location D:\DATAPILOT
.\.venv\Scripts\python.exe run_benchmark.py --mode model --limit 3 --output-dir benchmark_results\model_smoke
```

确认配置和结果稳定后，再运行完整 60 条模型评测：

```powershell
.\.venv\Scripts\python.exe run_benchmark.py --mode model --output-dir benchmark_results\model_full
```

`benchmark_results/latest.md` 是可直接放进项目说明的实验报告；本地模式用于稳定回归，模型模式用于衡量真实规划能力，两者不应混为一个指标。

最近一次可复现结果：

- 本地 60 条基线：查询执行率、字段命中率、图表选择、只读通过率、轨迹完整率均为 100%；平均延迟约 0.95 ms，P95 约 1.16 ms；
- DeepSeek 3 条 smoke test：上述正确性指标均为 100%；平均延迟约 43.5 s，P95 约 48.4 s。模型报告保存在 `benchmark_results/model_smoke_v3/`，延迟包含真实网络和模型生成时间。

## 启动

项目路径为 `D:\DATAPILOT`。首次使用：

```powershell
Set-Location D:\DATAPILOT
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run streamlit_app.py --server.port 8502
```

打开 `http://localhost:8502`。选择“本地模板（离线）”不需要 API；选择“DeepSeek 规划”时，在仓库根目录的 `.env` 中配置：

```text
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.siliconflow.cn/v1
DEEPSEEK_MODEL=deepseek-ai/DeepSeek-V4-Pro
```

## 测试

```powershell
Set-Location D:\DATAPILOT
.\.venv\Scripts\python.exe -m pytest -q tests
```

如果 Windows 的默认临时目录权限导致 pytest 报错，可以指定项目内临时目录：

```powershell
New-Item -ItemType Directory -Force .test_tmp | Out-Null
.\.venv\Scripts\python.exe -m pytest -q -p no:faulthandler -p no:cacheprovider --basetemp .test_tmp\run tests
```

## Agent 闭环

```text
用户问题
  -> Schema 注入
  -> DeepSeek 生成 JSON 查询计划
  -> 只读校验 + SQLite authorizer
  -> 查询真实数据
  -> 若是字段/语法执行错误：最多请求一次修复计划
  -> 修复仍失败：降级到本地模板
  -> 摘要、图表、SQL、警告和轨迹
```

安全边界优先于模型能力：危险 SQL 不会进入自动修复环节；所有查询仍受单语句、只读 authorizer、表范围 allowlist、最大行数和执行超时限制。

## 面试可展示的工程点

- **可靠性**：模型不可用、返回非法 JSON、SQL 字段错误时都有可观测的降级路径；
- **安全性**：文本检查和 SQLite authorizer 双重拦截写操作，危险请求仍返回安全的只读数据切片；
- **可评测**：固定 60 条案例、SHA-256 版本指纹、整体与分组指标、平均/P95 延迟；
- **可解释**：结果摘要只从真实查询结果计算，页面展示执行 SQL、模型思路、警告和每一步轨迹；
- **可测试**：核心逻辑与 Streamlit UI 解耦，pytest 覆盖数据库、SQL 防护、规划、修复重试和 benchmark。
- **持续集成**：GitHub Actions 在 push / pull request 时自动安装依赖并执行完整 pytest。
- **服务化**：`api_app.py` 暴露 `/healthz`、`/v1/analyze` 和 `/v1/runs`，支持通过 `DATAPILOT_API_TOKEN` 开启 API Key 校验。
- **可运维**：模型超时、重试次数和运行记录路径均可通过环境变量调整；审计数据默认写入 `.datapilot/audit.db`。

当前仍是单机生产原型：演示数据使用 SQLite 内存库，审计记录使用本地 SQLite 文件。面向多实例生产还需要接入 PostgreSQL、真实身份系统、SQL AST 级 allowlist、限流配额、异步任务队列和集中式日志/指标。

## 服务化运行

本地启动 API：

```powershell
Set-Location D:\DATAPILOT
.\.venv\Scripts\python.exe -m uvicorn api_app:app --host 127.0.0.1 --port 8000
```

查看健康状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

调用分析接口：

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/v1/analyze `
  -ContentType 'application/json' `
  -Body '{"question":"查看订单状态分布"}'
```

设置 `DATAPILOT_API_TOKEN` 后，请在请求头中加入 `X-API-Key`。API 和 Streamlit 共享 `.datapilot` 卷时，可以从运行记录接口查询最近任务。

使用 Docker Compose 同时启动网页和 API：

```powershell
docker compose up --build
```

- Streamlit：`http://localhost:8501`
- API 文档：`http://localhost:8000/docs`

## 推送到 GitHub 前检查

```powershell
Set-Location D:\DATAPILOT
\.venv\Scripts\python.exe -m pytest -q
\.venv\Scripts\python.exe run_benchmark.py --mode local
git status
```

不要提交 `.env` 或任何真实 API Key；`.gitignore` 已默认忽略本地密钥、虚拟环境和临时测试目录。

## 结构

```text
D:\DATAPILOT\
├── .github/workflows/tests.yml
├── streamlit_app.py
├── api_app.py
├── Dockerfile
├── docker-compose.yml
├── data_pilot/
│   ├── agent.py
│   ├── audit.py
│   ├── database.py
│   ├── csv_loader.py
│   ├── benchmark.py
│   ├── config.py
│   ├── llm_client.py
│   └── service.py
├── benchmarks/cases.json
├── benchmark_results/
├── run_benchmark.py
└── tests/
```
