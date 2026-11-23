"""系统域：用户/角色/权限矩阵/审批/审计/编号/参数/幂等/附件。"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint

from .base import Base, JSONType, TS


class User(Base, TS):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(64), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role_code = Column(String(32), default="SALES", index=True)
    phone = Column(String(32))
    email = Column(String(128))
    status = Column(String(16), default="ACTIVE")
    failed_count = Column(Integer, default=0)
    locked_until = Column(DateTime)
    last_login_at = Column(DateTime)


class Role(Base, TS):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    description = Column(Text)
    is_system = Column(Boolean, default=True)


class Permission(Base, TS):
    __tablename__ = "permissions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(96), unique=True, nullable=False)
    module = Column(String(48), nullable=False, index=True)
    action = Column(String(24), nullable=False)
    description = Column(Text)


class RolePermission(Base, TS):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_code", "permission_code"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    role_code = Column(String(32), nullable=False)
    permission_code = Column(String(96), nullable=False)
    allowed = Column(Boolean, default=True)
    field_mask = Column(String(255))  # 逗号分隔的脱敏字段


class UserRole(Base, TS):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_code"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    role_code = Column(String(32), nullable=False)


class ApprovalFlow(Base, TS):
    __tablename__ = "approval_flows"
    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_type = Column(String(32), nullable=False)  # DISCOUNT / PAYMENT / CREDIT
    threshold = Column(String(64))                 # 数值或百分比阈值
    approver_role = Column(String(32), default="ADMIN")
    levels = Column(Integer, default=1)
    is_active = Column(Boolean, default=True)


class ApprovalRequest(Base, TS):
    __tablename__ = "approval_requests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    flow_type = Column(String(32), nullable=False, index=True)
    ref_type = Column(String(32))
    ref_id = Column(Integer)
    ref_no = Column(String(64))
    amount = Column(String(64))
    requested_by = Column(String(64))
    status = Column(String(16), default="PENDING", index=True)
    approver = Column(String(64))
    decided_at = Column(DateTime)
    reason = Column(Text)
    payload = Column(JSONType)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, index=True)
    user_name = Column(String(64))
    action = Column(String(64), nullable=False, index=True)
    ref_type = Column(String(32), index=True)
    ref_id = Column(Integer)
    detail = Column(Text)
    before_json = Column(JSONType)
    after_json = Column(JSONType)
    ip = Column(String(64))


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, index=True)
    user_name = Column(String(64), index=True)
    title = Column(String(255))
    content = Column(Text)
    channel = Column(String(16), default="SITE")
    is_read = Column(Boolean, default=False)
    ref_type = Column(String(32))
    ref_id = Column(Integer)


class Sequence(Base, TS):
    __tablename__ = "sequences"
    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_type = Column(String(24), unique=True, nullable=False)
    prefix = Column(String(8), nullable=False)
    date_pattern = Column(String(16), default="%Y%m%d")
    current_date = Column(String(8))         # 当日流水按天归零
    next_no = Column(Integer, default=1)
    version = Column(Integer, default=0)  # 乐观锁，防止并发撞号


class Setting(Base, TS):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(96), unique=True, nullable=False)
    value = Column(Text)
    is_secret = Column(Boolean, default=False)
    description = Column(Text)


class IdempotencyKey(Base):
    """P0 补充：写接口幂等，避免双击/重试重复建单。"""
    __tablename__ = "idempotency_keys"
    id = Column(Integer, primary_key=True, autoincrement=True)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    endpoint = Column(String(128))
    user_name = Column(String(64))
    response_json = Column(JSONType)
    created_at = Column(DateTime, nullable=False)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, index=True)
    username = Column(String(64), index=True)
    ip = Column(String(64))
    success = Column(Boolean, default=False)
    scope = Column(String(16), default="INTERNAL")  # INTERNAL / PORTAL


class Attachment(Base):
    """P0 补充：统一附件（合同/水单/报关单/证书），替代散落的 file_path。"""
    __tablename__ = "attachments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False)
    ref_type = Column(String(32), nullable=False, index=True)
    ref_id = Column(Integer, nullable=False)
    filename = Column(String(255))
    file_path = Column(String(512))
    size = Column(Integer)
    uploaded_by = Column(String(64))
    category = Column(String(32))


class FeatureFlag(Base, TS):
    """默认关闭非核心能力（采集/Agent/MCP/素材库），按阶段开启。"""
    __tablename__ = "feature_flags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(64), unique=True, nullable=False)
    enabled = Column(Boolean, default=False)
    description = Column(Text)
