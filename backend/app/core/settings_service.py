"""系统参数：settings 表读写，敏感键 Fernet 加密存储、列表接口永不回明文。"""
from ..models.system import Setting
from .security import decrypt_value, encrypt_value

SECRET_KEYS = {
    "mail_password", "imap_password", "llm_api_key", "fb_page_token",
    "google_maps_api_key", "ocr_api_key", "feishu_webhook_url",
    "material_api_key", "smtp_password",
}

DEFAULTS = {
    "company_name": "Hanpei International Trading Co., Ltd.",
    "company_name_ar": "",
    "company_country": "China",
    "company_tel": "",
    "company_email": "",
    "company_contact": "",
    "company_address": "",
    "commission_rate": "0.015",
    "approve_limit": "50000",
    "sales_target": "0",
    "discount_approve_pct": "5",
    "credit_approve_limit": "0",
    "remind_days_deposit": "3",
    "remind_days_collection": "7",
    "remind_days_quote": "10",
    "default_currency": "USD",
    "seal_path": "",
    "seal_enabled": "0",
    "feishu_webhook_url": "",
    "mail_from": "", "smtp_host": "", "smtp_port": "465", "smtp_ssl": "1",
    "smtp_user": "", "smtp_password": "", "imap_host": "", "imap_port": "993",
    "imap_user": "", "imap_password": "", "mail_signature": "",
    "google_maps_api_key": "", "fb_page_id": "", "fb_page_token": "",
    "llm_api_url": "", "llm_api_key": "", "llm_model": "",
    "ocr_api_url": "", "ocr_api_key": "",
    "material_api_base": "", "material_api_key": "",
    "forex_stale_days": "7",
    # P0 补充：口径与验收基线
    "exchange_gain_method": "SETTLE_MINUS_QUOTE",
    "commission_basis": "ALLOCATED_RECEIPT",
    "aging_basis": "DUE_DATE",
    "stock_allocation_lock": "1",
}


def get(db, key, default=None):
    row = db.query(Setting).filter_by(key=key).first()
    if row is None:
        return DEFAULTS.get(key, default)
    return decrypt_value(row.value) if row.is_secret else row.value


def get_float(db, key, default=0.0):
    try:
        return float(get(db, key, default))
    except (TypeError, ValueError):
        return float(default)


def set_value(db, key, value, user="system"):
    row = db.query(Setting).filter_by(key=key).first()
    stored = encrypt_value(value) if key in SECRET_KEYS else ("" if value is None else str(value))
    if row is None:
        row = Setting(key=key, value=stored, is_secret=key in SECRET_KEYS, created_by=user)
        db.add(row)
    else:
        row.value = stored
        row.is_secret = key in SECRET_KEYS
        row.updated_by = user
    return row


def listing(db):
    rows = {r.key: r for r in db.query(Setting).all()}
    out = []
    for key, default in DEFAULTS.items():
        r = rows.get(key)
        raw = r.value if r else default
        out.append({
            "key": key,
            "value": "******" if key in SECRET_KEYS and raw else (raw if r is None else (decrypt_value(raw) if r.is_secret else raw)),
            "is_secret": key in SECRET_KEYS,
            "description": (r.description if r else "") or "",
        })
    return out
