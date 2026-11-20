"""기존 SQLite DB 를 지금 표 정의에 맞춘다: 모델에 있는데 DB 표에 없는 칸만 더한다.

create_all 은 없는 표만 만들고 있는 표는 건드리지 않는다. 그래서 모델에 칸을 더하면 기존 DB 에서는
"no such column" 으로 깨진다. 여기서는 기존 줄을 깨지 않고 더할 수 있는 칸(NULL 가능, 또는 글 상수 DDL 기본값이나
글·숫자·참거짓 기본값이 있는 칸)만 ALTER TABLE … ADD COLUMN 으로 더한다(기존 줄은 NULL 이나 그 기본값).
지우기·이름 바꾸기·종류 바꾸기는 하지 않는다. 더할 수 없는 칸(기본값 없는 NOT NULL·함수 기본값·
상수가 아닌 DDL 기본값·기본 키·겹침 금지·색인·외래 키)과 DB 에만 있는 칸은 경고만 남긴다.
칸마다 따로 더하므로 SQLite 가 한 칸을 거절해도(OperationalError) 경고만 남기고 다음 칸으로 간다(시작을 막지 않는다).
기록에는 표·칸 이름만 남긴다. 여러 번 불러도 결과가 같다.
"""

import logging

from sqlalchemy import Column, Engine, MetaData, Table, inspect, literal
from sqlalchemy.exc import OperationalError
from sqlalchemy.schema import CreateColumn, DefaultClause

logger = logging.getLogger(__name__)

_LITERALS = (str, int, float)  # DDL 기본값으로 바로 쓸 수 있는 값 기본값(bool 은 int)


def _value_default(column: Column) -> object | None:
    default = column.default
    if default is None or not default.is_scalar or not isinstance(default.arg, _LITERALS):
        return None
    return default.arg


def _addable(column: Column) -> bool:
    if column.primary_key or column.unique or column.index or column.foreign_keys:
        return False
    if column.server_default is not None:  # SQLite 는 상수가 아닌 기본값(CURRENT_TIMESTAMP·함수)으로 더하지 못한다
        default = column.server_default
        return isinstance(default, DefaultClause) and isinstance(default.arg, str)
    return column.nullable or _value_default(column) is not None


def _column_ddl(column: Column, engine: Engine) -> str:
    ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
    if not column.nullable and column.server_default is None:  # NOT NULL 은 DDL 기본값이 있어야 더할 수 있다
        value = literal(_value_default(column), column.type)
        ddl += " DEFAULT " + str(value.compile(dialect=engine.dialect, compile_kwargs={"literal_binds": True}))
    return ddl


def _add(engine: Engine, table: Table, column: Column) -> bool:
    """한 칸을 따로 된 트랜잭션으로 더한다. SQLite 가 거절하면 경고만 남기고 False."""
    name = engine.dialect.identifier_preparer.format_table(table)
    try:
        with engine.begin() as conn:  # exec_driver_sql: 기본값 글 속의 ':이름' 을 바인드 인자로 읽지 않는다
            conn.exec_driver_sql(f"ALTER TABLE {name} ADD COLUMN {_column_ddl(column, engine)}")
    except OperationalError:
        logger.warning("기존 DB 에 칸을 더하지 못해 그대로 둡니다: %s.%s", table.name, column.name)
        return False
    logger.info("기존 DB 에 칸을 더했습니다: %s.%s", table.name, column.name)
    return True


def add_missing_columns(engine: Engine, metadata: MetaData) -> list[str]:
    """DB 에 이미 있는 표마다 빠진 칸을 더하고 더한 칸 이름("표.칸")을 차례대로 돌려준다. create_all 뒤에 부른다."""
    added = []
    found = inspect(engine)
    tables = set(found.get_table_names())
    for table in metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {c["name"] for c in found.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing:
                continue
            if not _addable(column):
                logger.warning("기존 DB 에 더할 수 없는 칸이라 그대로 둡니다: %s.%s", table.name, column.name)
            elif _add(engine, table, column):
                added.append(f"{table.name}.{column.name}")
        for extra in sorted(existing - {c.name for c in table.columns}):
            logger.warning("DB 에만 있는 칸이라 그대로 둡니다: %s.%s", table.name, extra)
    return added
