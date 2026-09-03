from __future__ import annotations

import json
import sqlite3

import pytest

from data_pilot.agent import DataAgentError, DataPilotAgent
from data_pilot.database import (
    DemoDatabase,
    QueryExecutionError,
    SQLSafetyError,
    validate_read_only_sql,
)
from data_pilot.csv_loader import CSVUploadError, load_csv_dataset


class FakeLLMClient:
    def __init__(self, response: str):
        self.response = response

    def chat(self, messages, model=None, max_tokens=900):
        return self.response


class QueueLLMClient:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, model=None, max_tokens=900):
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture()
def database() -> DemoDatabase:
    return DemoDatabase()


def test_demo_database_is_deterministic(database: DemoDatabase) -> None:
    result = database.execute_read_only("SELECT COUNT(*) AS order_count FROM orders")

    assert result.rows == [(180,)]
    assert result.columns == ["order_count"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET status = 'paid'",
        "DROP TABLE orders",
        "SELECT * FROM orders; DELETE FROM orders",
        "PRAGMA table_info(orders)",
    ],
)
def test_read_only_validator_rejects_write_or_multi_statement_sql(sql: str) -> None:
    with pytest.raises(SQLSafetyError):
        validate_read_only_sql(sql)


def test_read_only_query_has_a_row_limit(database: DemoDatabase) -> None:
    limited = DemoDatabase(max_rows=50)
    result = limited.execute_read_only("SELECT id FROM orders ORDER BY id")

    assert len(result.rows) == 50
    assert "LIMIT 50" in result.sql


def test_authorizer_blocks_sqlite_write_even_if_keyword_is_hidden(database: DemoDatabase) -> None:
    database._install_read_only_authorizer()
    try:
        with pytest.raises(sqlite3.DatabaseError):
            database.connection.execute("DELETE FROM orders")
    finally:
        database.connection.set_authorizer(None)


def test_authorizer_blocks_tables_outside_demo_schema(database: DemoDatabase) -> None:
    with pytest.raises(QueryExecutionError):
        database.execute_read_only("SELECT name FROM sqlite_master")


def test_local_agent_returns_real_rows_and_trace(database: DemoDatabase) -> None:
    result = DataPilotAgent(database).analyze("哪个品类的销售额最高？请给出订单数和销量")

    assert result.title == "各品类销售表现"
    assert result.rows
    assert result.columns == ["category", "order_count", "units_sold", "revenue"]
    assert any("只读查询" in step for step in result.trace)
    assert result.model == "local"
    assert result.evidence
    assert "品类" in result.evidence[0]["claim"]


def test_local_agent_answers_peak_refund_month_with_evidence(database: DemoDatabase) -> None:
    result = DataPilotAgent(database).analyze("分析每个月的退款率，并找出退款率最高的月份")

    assert "退款率最高" in result.summary
    assert result.evidence[0]["row_numbers"]
    assert result.evidence[0]["values"]["refund_rate_pct"] is not None
    json.dumps(result.to_dict(), ensure_ascii=False)


def test_local_agent_handles_unknown_question_with_safe_default(database: DemoDatabase) -> None:
    result = DataPilotAgent(database).analyze("给我看一份可以核对的数据")

    assert result.chart_type == "table"
    assert result.rows
    assert result.sql.lstrip().upper().startswith("SELECT")


def test_model_plan_is_parsed_and_executed(database: DemoDatabase) -> None:
    client = FakeLLMClient(
        '{"sql":"SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status",'
        '"chart_type":"bar","title":"订单状态分布","reasoning":"按状态聚合"}'
    )
    result = DataPilotAgent(database, llm_client=client, model="fake-model").analyze("查看订单状态")

    assert result.model == "fake-model"
    assert result.title == "订单状态分布"
    assert result.rows
    assert result.warnings == []


def test_unsafe_model_plan_falls_back_to_local_template(database: DemoDatabase) -> None:
    client = FakeLLMClient(
        '{"sql":"DELETE FROM orders","chart_type":"table",'
        '"title":"危险操作","reasoning":"不应执行"}'
    )
    result = DataPilotAgent(database, llm_client=client).analyze("查看订单状态分布")

    assert result.rows
    assert result.model == "local-fallback"
    assert any("安全检查" in warning for warning in result.warnings)


def test_model_query_error_is_repaired_once(database: DemoDatabase) -> None:
    client = QueueLLMClient(
        [
            '{"sql":"SELECT missing_column FROM orders", "chart_type":"table",'
            '"title":"错误计划","reasoning":"使用不存在字段"}',
            '{"sql":"SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status",'
            '"chart_type":"bar","title":"修复后的状态分布","reasoning":"按状态聚合"}',
        ]
    )

    result = DataPilotAgent(database, llm_client=client, model="fake-model").analyze(
        "查看订单状态"
    )

    assert client.calls == 2
    assert result.model == "fake-model"
    assert result.title == "修复后的状态分布"
    assert result.rows
    assert any("修复后的模型计划执行成功" in step for step in result.trace)


def test_model_result_contract_is_repaired_once(database: DemoDatabase) -> None:
    client = QueueLLMClient(
        [
            '{"sql":"SELECT substr(order_date, 1, 7) AS month, SUM(total_amount) AS sales '
            'FROM orders GROUP BY month", "chart_type":"line",'
            '"title":"不完整趋势","reasoning":"只返回金额"}',
            '{"sql":"SELECT substr(order_date, 1, 7) AS month, COUNT(*) AS order_count, '
            'SUM(total_amount) AS revenue FROM orders GROUP BY month", "chart_type":"line",'
            '"title":"完整趋势","reasoning":"返回月份、订单数和销售额"}',
        ]
    )

    result = DataPilotAgent(database, llm_client=client, model="fake-model").analyze(
        "查看月度销售额和订单量趋势"
    )

    assert client.calls == 2
    assert result.title == "完整趋势"
    assert set(result.columns) == {"month", "order_count", "revenue"}
    assert any("缺少问题所需字段" in warning for warning in result.warnings)


def test_unsafe_model_plan_does_not_trigger_repair_call(database: DemoDatabase) -> None:
    client = QueueLLMClient(
        [
            '{"sql":"DELETE FROM orders", "chart_type":"table",'
            '"title":"危险操作","reasoning":"不应执行"}',
            '{"sql":"SELECT 1", "chart_type":"table",'
            '"title":"不应使用","reasoning":"不应使用"}',
        ]
    )

    result = DataPilotAgent(database, llm_client=client).analyze("查看订单状态分布")

    assert client.calls == 1
    assert result.model == "local-fallback"
    assert result.rows


def test_destructive_request_is_blocked_before_model_call(database: DemoDatabase) -> None:
    client = QueueLLMClient(
        ['{"sql":"DELETE FROM orders", "chart_type":"table", "title":"x", "reasoning":"x"}']
    )
    agent = DataPilotAgent(database, llm_client=client)

    result = agent.analyze("删除全部订单，然后给我看结果")

    assert client.calls == 0
    assert result.model == "policy-fallback"
    assert result.warnings
    assert database.execute_read_only("SELECT COUNT(*) FROM orders").rows == [(180,)]


def test_recent_order_contract_repairs_missing_amount(database: DemoDatabase) -> None:
    client = QueueLLMClient(
        [
            '{"sql":"SELECT id AS order_id, order_date, status FROM orders ORDER BY order_date DESC LIMIT 10",'
            '"chart_type":"table","title":"最近订单","reasoning":"查询明细"}',
            '{"sql":"SELECT id AS order_id, order_date, status, total_amount FROM orders ORDER BY order_date DESC, id DESC LIMIT 20",'
            '"chart_type":"table","title":"最近订单","reasoning":"补齐订单金额"}',
        ]
    )

    result = DataPilotAgent(database, llm_client=client).analyze("给我看最近订单明细")

    assert client.calls == 2
    assert "total_amount" in result.columns
    assert result.model == "deepseek-ai/DeepSeek-V4-Pro"


def test_empty_question_is_rejected(database: DemoDatabase) -> None:
    with pytest.raises(DataAgentError):
        DataPilotAgent(database).analyze("  ")


def test_csv_loader_normalizes_tables_and_columns() -> None:
    dataset = load_csv_dataset(
        [
            ("销售明细.csv", "订单日期,销售额,区域\n2025-01-01,12.5,华东\n".encode("utf-8")),
            ("sales.csv", "id,amount\n1,20\n".encode("utf-8")),
        ]
    )

    assert len(dataset.profiles) == 2
    assert dataset.total_rows == 2
    assert dataset.profiles[0].table_name == "table_1"
    assert dataset.profiles[0].columns == ("column_1", "column_2", "column_3")
    assert dataset.profiles[0].original_columns == ("订单日期", "销售额", "区域")
    result = dataset.database.execute_read_only(
        f'SELECT "column_2" FROM "{dataset.profiles[0].table_name}"'
    )
    assert result.rows == [(12.5,)]


def test_csv_loader_rejects_too_many_files() -> None:
    files = [(f"{index}.csv", b"a\n1\n") for index in range(6)]
    with pytest.raises(CSVUploadError):
        load_csv_dataset(files)


def test_uploaded_database_blocks_system_table_and_local_fallback_is_safe() -> None:
    dataset = load_csv_dataset([("events.csv", b"event,value\nlogin,1\n")])

    with pytest.raises(QueryExecutionError):
        dataset.database.execute_read_only("SELECT name FROM sqlite_master")
    result = DataPilotAgent(dataset.database).analyze("查看一份数据")
    assert result.model == "local"
    assert result.columns == ["event", "value"]
