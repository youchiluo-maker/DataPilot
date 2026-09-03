from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from data_pilot.agent import AnalysisResult
from data_pilot.audit import AuditStore
from data_pilot.config import load_settings
from data_pilot.database import DemoDatabase
from data_pilot.llm_client import DeepSeekClient
from data_pilot.csv_loader import CSVUploadError, UploadedDataset, load_csv_dataset
from data_pilot.service import AnalysisService


st.set_page_config(
    page_title="DataPilot 数据分析 Agent",
    page_icon=":material/analytics:",
    layout="wide",
)


EXAMPLES = [
    "统计 2025 年每个月的销售额和订单量趋势",
    "哪个品类的销售额最高？请给出订单数和销量",
    "分析每个月的退款率，并找出退款率最高的月份",
    "查看订单状态分布",
    "列出销量最高的商品 Top 10",
]

COLUMN_LABELS = {
    "month": "月份",
    "order_count": "订单数",
    "revenue": "销售额",
    "refund_count": "退款订单数",
    "refund_rate_pct": "退款率（%）",
    "category": "品类",
    "units_sold": "销量",
    "status": "订单状态",
    "total_amount": "订单金额",
    "product": "商品",
    "order_id": "订单编号",
    "order_date": "下单日期",
    "region": "地区",
}


@st.cache_resource
def get_database() -> DemoDatabase:
    return DemoDatabase()


@st.cache_resource
def get_audit_store(path: str) -> AuditStore:
    return AuditStore(path)


def _render_chart(result: AnalysisResult) -> None:
    frame = result.dataframe()
    if frame.empty or result.chart_type == "none":
        return
    numeric = frame.select_dtypes(include="number").columns.tolist()
    categorical = [column for column in frame.columns if column not in numeric]
    if not numeric or not categorical:
        return
    x_column = categorical[0]
    preferred = ["refund_rate_pct", "revenue", "units_sold", "order_count", "total_amount"]
    y_column = next((column for column in preferred if column in numeric), numeric[0])
    if result.chart_type == "line":
        st.line_chart(
            frame,
            x=x_column,
            y=y_column,
            x_label=COLUMN_LABELS.get(x_column, x_column),
            y_label=COLUMN_LABELS.get(y_column, y_column),
        )
    elif result.chart_type == "bar":
        st.bar_chart(
            frame,
            x=x_column,
            y=y_column,
            x_label=COLUMN_LABELS.get(x_column, x_column),
            y_label=COLUMN_LABELS.get(y_column, y_column),
        )


def _render_result(result: AnalysisResult) -> None:
    if result.warnings:
        for warning in result.warnings:
            st.warning(warning)

    with st.container(horizontal=True):
        st.metric("返回行数", len(result.rows), border=True)
        st.metric("字段数量", len(result.columns), border=True)
        st.metric("查询耗时", f"{result.duration_seconds:.2f}s", border=True)
        st.metric("执行模式", "DeepSeek" if result.model.startswith("deepseek") else "本地模板", border=True)
        st.metric("运行 ID", result.run_id or "未记录", border=True)

    with st.container(border=True):
        st.subheader(result.title)
        st.info(result.summary)
        if result.evidence:
            st.markdown("**数据证据**")
            for evidence in result.evidence:
                rows = ", ".join(str(number) for number in evidence.get("row_numbers", []))
                suffix = f"（结果第 {rows} 行）" if rows else ""
                st.success(f"{evidence['claim']}{suffix}")
        _render_chart(result)
        st.dataframe(
            result.dataframe().rename(columns=COLUMN_LABELS),
            hide_index=True,
            width="stretch",
        )

    overview, evidence = st.tabs(["分析说明", "SQL 与执行轨迹"])
    with overview:
        st.markdown("**查询规划思路**")
        st.write(result.reasoning)
        st.caption("摘要由真实查询结果计算生成，不是模型凭空编写。")
    with evidence:
        st.markdown("**安全执行 SQL**")
        st.code(result.executed_sql, language="sql")
        st.markdown("**Agent 执行轨迹**")
        for index, step in enumerate(result.trace, start=1):
            st.write(f"{index}. {step}")
        st.download_button(
            "下载分析 JSON",
            data=json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            file_name="datapilot-analysis.json",
            mime="application/json",
            icon=":material/download:",
        )


def _render_run_history(store: AuditStore) -> None:
    records = store.recent(10)
    if not records:
        return
    with st.expander("最近运行记录", expanded=False):
        history = pd.DataFrame(
            [
                {
                    "运行 ID": record.run_id,
                    "时间（UTC）": record.created_at,
                    "问题": record.question,
                    "模型": record.model,
                    "状态": record.status,
                    "行数": record.row_count,
                    "耗时（秒）": round(record.duration_seconds, 3),
                    "降级": "是" if record.fallback_used else "否",
                }
                for record in records
            ]
        )
        st.dataframe(history, hide_index=True, width="stretch")


st.title("DataPilot 数据分析 Agent")
st.caption("上传真实 CSV 或使用演示数据，把自然语言问题转换为可审计的只读 SQL、摘要和图表。")

settings = load_settings()
database = get_database()
st.session_state.setdefault("analysis_result", None)
st.session_state.setdefault("analysis_question", EXAMPLES[0])
st.session_state.setdefault("uploaded_dataset", None)
st.session_state.setdefault("data_source", "演示电商数据")


def _use_selected_example() -> None:
    selected = st.session_state.get("selected_example")
    if selected:
        st.session_state["analysis_question"] = selected


def _switch_data_source() -> None:
    st.session_state["analysis_result"] = None
    if st.session_state.get("data_source") == "演示电商数据":
        uploaded_dataset = st.session_state.get("uploaded_dataset")
        if uploaded_dataset is not None:
            uploaded_dataset.database.close()
            st.session_state["uploaded_dataset"] = None
        st.session_state["analysis_question"] = EXAMPLES[0]
    else:
        st.session_state["analysis_question"] = "统计每个数据表的记录数，并概括主要字段"

with st.sidebar:
    st.header("运行设置")
    source = st.selectbox(
        "数据源",
        ["演示电商数据", "上传 CSV"],
        key="data_source",
        on_change=_switch_data_source,
    )
    mode = st.selectbox(
        "分析模式",
        ["本地模板（离线）", "DeepSeek 规划"],
        index=1 if settings.model_configured else 0,
    )
    model_options = list(settings.allowed_models)
    model = st.selectbox("模型", model_options, disabled=mode == "本地模板（离线）")
    st.success("全部查询默认只读")
    st.caption("写操作、管理操作和多语句 SQL 会在执行前被拦截。")
    if settings.model_configured:
        st.caption("已检测到 DeepSeek API 配置。")
    else:
        st.warning("未检测到 API Key；模型模式会自动降级到离线模板。")
    st.divider()
    if source == "演示电商数据":
        st.markdown("**内置数据集**")
        st.caption("180 条订单、30 个用户、12 个商品，数据每次启动均可复现。")
    else:
        st.markdown("**上传限制**")
        st.caption("最多 5 个 CSV；单文件 5 MB；总计 15 MB；每表最多 10 万行、100 列。")

if source == "上传 CSV":
    with st.container(border=True):
        st.subheader("导入自己的数据", help="文件仅在当前会话的内存中解析，不写入项目目录。")
        uploaded_files = st.file_uploader(
            "选择一个或多个 CSV 文件",
            type=["csv"],
            accept_multiple_files=True,
            help="支持 UTF-8 和 GB18030 编码；文件名会被规范化为 SQLite 表名。",
            key="csv_files",
        )
        if st.button(
            "加载为只读数据源",
            icon=":material/database_upload:",
            type="primary",
            disabled=not uploaded_files,
        ):
            try:
                payload = [(file.name, file.getvalue()) for file in uploaded_files]
                next_dataset = load_csv_dataset(payload)
                previous_dataset = st.session_state.get("uploaded_dataset")
                if previous_dataset is not None:
                    previous_dataset.database.close()
                st.session_state["uploaded_dataset"] = next_dataset
                st.session_state["analysis_result"] = None
                st.success("CSV 已加载到当前会话的内存数据库。")
            except CSVUploadError as exc:
                st.error(f"CSV 导入失败：{exc}")

    uploaded_dataset: UploadedDataset | None = st.session_state["uploaded_dataset"]
    if uploaded_dataset is not None:
        with st.container(horizontal=True):
            st.metric("数据表", len(uploaded_dataset.profiles), border=True)
            st.metric("总行数", f"{uploaded_dataset.total_rows:,}", border=True)
            st.metric(
                "总字段数",
                sum(profile.column_count for profile in uploaded_dataset.profiles),
                border=True,
            )
        profile_frame = pd.DataFrame(
            [
                {
                    "原始文件": profile.original_filename,
                    "SQLite 表名": profile.table_name,
                    "行数": profile.row_count,
                    "列数": profile.column_count,
                    "编码": profile.encoding,
                    "字段映射": ", ".join(
                        f"{original} -> {normalized}"
                        for original, normalized in zip(
                            profile.original_columns, profile.columns
                        )
                    ),
                }
                for profile in uploaded_dataset.profiles
            ]
        )
        with st.container(border=True):
            st.subheader("数据结构")
            st.dataframe(profile_frame, hide_index=True, width="stretch")
            preview_table = st.selectbox(
                "预览数据表",
                [profile.table_name for profile in uploaded_dataset.profiles],
            )
            st.dataframe(
                uploaded_dataset.tables[preview_table].head(20),
                hide_index=True,
                width="stretch",
                key="uploaded_preview",
            )
        if mode == "本地模板（离线）":
            st.info("自定义 CSV 的自然语言聚合需要 DeepSeek 规划；离线模式只返回首个表的安全预览。")

if source == "演示电商数据":
    selected_example = st.pills(
        "示例问题",
        EXAMPLES,
        selection_mode="single",
        label_visibility="visible",
        key="selected_example",
        on_change=_use_selected_example,
    )

with st.form("analysis_form", border=True):
    question = st.text_area(
        "你想分析什么？",
        height=100,
        help="可以询问趋势、排名、分布或退款率等业务问题。",
        key="analysis_question",
    )
    submitted = st.form_submit_button(
        "运行分析 Agent",
        type="primary",
        width="stretch",
        icon=":material/play_arrow:",
    )

if submitted:
    uploaded_dataset = st.session_state.get("uploaded_dataset")
    if source == "上传 CSV" and uploaded_dataset is None:
        st.error("请先上传并加载 CSV 数据。")
        st.stop()
    client = DeepSeekClient(settings) if mode == "DeepSeek 规划" and settings.model_configured else None
    active_database = database if source == "演示电商数据" else uploaded_dataset.database
    audit_store = get_audit_store(settings.audit_db_path)
    with st.spinner("Agent 正在理解问题、规划 SQL 并执行只读查询……"):
        try:
            st.session_state["analysis_result"] = AnalysisService(
                database=active_database,
                llm_client=client,
                model=model,
                audit_store=audit_store,
                source="demo" if source == "演示电商数据" else "csv-upload",
            ).analyze(question)
        except Exception as exc:
            st.error(f"分析失败：{exc}")

result = st.session_state["analysis_result"]
if result is not None:
    _render_result(result)
else:
    st.info("先选择一个示例问题，或输入自己的业务问题，然后运行 Agent。")

_render_run_history(get_audit_store(settings.audit_db_path))
