"""公共基类与通用字段。

跨库策略：只用 SQLite / PostgreSQL 均支持的类型。
JSON 字段在 PostgreSQL 下自动变体为 JSONB（文档第 12 节的 pg_trgm / IDENTITY
属于 PG 专属，本实现用通用类型 + 应用层索引替代，见附录 E）。
"""
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class TS:
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(64))
    updated_by = Column(String(64))


class Soft:
    deleted_at = Column(DateTime)
    remark = Column(Text)
