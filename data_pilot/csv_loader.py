from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import re
import unicodedata
from collections.abc import Sequence

import pandas as pd

from .database import DemoDatabase


MAX_FILES = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 15 * 1024 * 1024
MAX_ROWS_PER_FILE = 100_000
MAX_COLUMNS = 100


class CSVUploadError(ValueError):
    """Raised when uploaded CSV data is unsafe or cannot be parsed."""


@dataclass(frozen=True)
class TableProfile:
    original_filename: str
    table_name: str
    row_count: int
    column_count: int
    columns: tuple[str, ...]
    original_columns: tuple[str, ...]
    encoding: str


@dataclass
class UploadedDataset:
    database: DemoDatabase
    tables: dict[str, pd.DataFrame]
    profiles: list[TableProfile]

    @property
    def total_rows(self) -> int:
        return sum(profile.row_count for profile in self.profiles)


def _normalize_identifier(value: str, *, fallback: str) -> str:
    value = unicodedata.normalize("NFKC", str(value)).strip()
    value = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"{fallback}_{value}"
    if value.lower().startswith("sqlite_"):
        value = f"data_{value}"
    return value[:64]


def _unique_identifiers(values: Sequence[str], *, prefix: str) -> list[str]:
    result: list[str] = []
    used: set[str] = set()
    for index, value in enumerate(values, start=1):
        base = _normalize_identifier(value, fallback=f"{prefix}_{index}")
        candidate = base
        suffix = 2
        while candidate.casefold() in used:
            candidate = f"{base[:58]}_{suffix}"
            suffix += 1
        used.add(candidate.casefold())
        result.append(candidate)
    return result


def _decode_csv(content: bytes, filename: str) -> tuple[str, str]:
    if b"\x00" in content:
        raise CSVUploadError(f"{filename} 包含二进制空字符，不像有效 CSV。")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CSVUploadError(f"{filename} 不是支持的 UTF-8 或 GB18030 编码。")


def load_csv_dataset(files: Sequence[tuple[str, bytes]]) -> UploadedDataset:
    if not files:
        raise CSVUploadError("请至少上传一个 CSV 文件。")
    if len(files) > MAX_FILES:
        raise CSVUploadError(f"一次最多上传 {MAX_FILES} 个 CSV 文件。")

    total_size = sum(len(content) for _, content in files)
    if total_size > MAX_TOTAL_BYTES:
        raise CSVUploadError("上传文件总大小不能超过 15 MB。")

    table_names = _unique_identifiers(
        [Path(filename).stem for filename, _ in files], prefix="table"
    )
    tables: dict[str, pd.DataFrame] = {}
    profiles: list[TableProfile] = []
    descriptions: dict[str, str] = {}

    for (filename, content), table_name in zip(files, table_names):
        if Path(filename).suffix.lower() != ".csv":
            raise CSVUploadError(f"只支持 .csv 文件：{filename}")
        if not content:
            raise CSVUploadError(f"文件为空：{filename}")
        if len(content) > MAX_FILE_BYTES:
            raise CSVUploadError(f"单个 CSV 不能超过 5 MB：{filename}")

        decoded, encoding = _decode_csv(content, filename)
        try:
            frame = pd.read_csv(StringIO(decoded), on_bad_lines="error")
        except (pd.errors.ParserError, UnicodeError, ValueError) as exc:
            raise CSVUploadError(f"无法解析 {filename}：{exc}") from exc
        if frame.empty:
            raise CSVUploadError(f"CSV 没有数据行：{filename}")
        if len(frame) > MAX_ROWS_PER_FILE:
            raise CSVUploadError(f"单个 CSV 不能超过 {MAX_ROWS_PER_FILE:,} 行：{filename}")
        if len(frame.columns) > MAX_COLUMNS:
            raise CSVUploadError(f"单个 CSV 不能超过 {MAX_COLUMNS} 列：{filename}")

        original_columns = tuple(str(column) for column in frame.columns)
        normalized_columns = _unique_identifiers(original_columns, prefix="column")
        frame = frame.copy()
        frame.columns = normalized_columns
        frame = frame.where(pd.notna(frame), None)
        tables[table_name] = frame
        descriptions[table_name] = (
            f"用户上传文件 {filename}，共 {len(frame):,} 行；字段："
            + ", ".join(
                f"{original} -> {normalized}"
                for original, normalized in zip(original_columns, normalized_columns)
            )
        )
        profiles.append(
            TableProfile(
                original_filename=filename,
                table_name=table_name,
                row_count=len(frame),
                column_count=len(normalized_columns),
                columns=tuple(normalized_columns),
                original_columns=original_columns,
                encoding=encoding,
            )
        )

    database = DemoDatabase(
        dataframes=tables,
        table_descriptions=descriptions,
        max_rows=500,
        timeout_seconds=2.0,
    )
    return UploadedDataset(database=database, tables=tables, profiles=profiles)
