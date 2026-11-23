"""portal confirmations + unique quotation index

Revision ID: b7e2c4a91f30
Revises: d3343c60b06a
Create Date: 2026-11-23

变更：
1. 新增 portal_confirmations（客户门户确认订单的持久化记录）；
2. sales_orders.quotation_id 加唯一索引，数据库层兜底「一份报价只能转一张订单」。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c4a91f30"
down_revision: Union[str, None] = "d3343c60b06a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portal_confirmations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("portal_user", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("confirm_count", sa.Integer(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "customer_id",
                            name="uq_portal_confirmation_order_customer"),
    )
    op.create_index("ix_portal_confirmations_order_id", "portal_confirmations", ["order_id"])
    op.create_index("ix_portal_confirmations_customer_id", "portal_confirmations", ["customer_id"])
    op.create_index("ix_portal_confirmations_confirmed_at", "portal_confirmations", ["confirmed_at"])
    # 启动引导 _ensure_indexes() 用的是同一条 IF NOT EXISTS，生产/开发两种初始化路径互不冲突
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_orders_quotation_id "
               "ON sales_orders (quotation_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sales_orders_quotation_id")
    op.drop_index("ix_portal_confirmations_confirmed_at", table_name="portal_confirmations")
    op.drop_index("ix_portal_confirmations_customer_id", table_name="portal_confirmations")
    op.drop_index("ix_portal_confirmations_order_id", table_name="portal_confirmations")
    op.drop_table("portal_confirmations")
