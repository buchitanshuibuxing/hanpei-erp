"""初始化数据库与种子数据（幂等，可重复执行）。

用法：cd backend && python seed.py
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core import settings_service  # noqa: E402
from app.core.normalize import normalize_oe  # noqa: E402
from app.core.permissions import ACTIONS, MODULES, ROLES, matrix  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    BankAccount, Category, Customer, FeatureFlag, ForexRate, Permission,
    PortalAccount, Product, ProductOeNumber, Role, RolePermission, Setting,
    Supplier, User, Warehouse,
)

PRODUCTS = [
    ("HP-0001", "机油滤清器", "Oil Filter", "25100-03011", "8421230000", 18.5, 12.2, "BOX", 20, 100, 0.012),
    ("HP-0002", "空气滤清器", "Air Filter", "17801-30030", "8421310000", 24.0, 16.5, "BOX", 20, 80, 0.028),
    ("HP-0003", "前刹车片", "Brake Pad Front", "04465-02220", "6813810000", 62.0, 41.0, "SET", 10, 50, 0.018),
    ("HP-0004", "水泵", "Water Pump", "16100-09070", "8413300000", 86.0, 58.0, "BOX", 10, 40, 0.032),
    ("HP-0005", "火花塞", "Spark Plug", "90919-01253", "8511100000", 9.8, 6.2, "BOX", 50, 200, 0.006),
    ("HP-0006", "减震器", "Shock Absorber", "48510-80518", "8708800000", 118.0, 82.0, "PCS", 1, 20, 0.045),
]

USERS = [
    ("admin", "系统管理员", "ADMIN", "admin123"),
    ("manager", "王主管", "MANAGER", "123456"),
    ("sales1", "李业务", "SALES", "123456"),
    ("sales2", "陈业务", "SALES", "123456"),
    ("finance", "张财务", "FINANCE", "123456"),
    ("purchase", "赵采购", "PURCHASER", "123456"),
    ("follower", "孙跟单", "FOLLOWER", "123456"),
    ("warehouse", "周仓管", "WAREHOUSE", "123456"),
]

CUSTOMERS = [
    ("C0001", "Al Noor Auto Parts Trading", "المملكة العربية السعودية", "SA", "SAR", "李业务", "NEW_DEPOSIT", 30),
    ("C0002", "Gulf Spare Parts LLC", "", "AE", "USD", "陈业务", "OLD_COLLECTION", 15),
    ("C0003", "Al Baraka Trading Co.", "", "SA", "SAR", "李业务", "NEW_DEPOSIT", 30),
]


def run():
    init_db()
    with SessionLocal() as db:
        # 角色与权限矩阵
        for code, name in ROLES.items():
            if not db.query(Role).filter_by(code=code).first():
                db.add(Role(code=code, name=name, is_system=True))
        db.flush()
        for module, label in MODULES.items():
            for action, alabel in ACTIONS.items():
                code = f"{module}.{action}"
                if not db.query(Permission).filter_by(code=code).first():
                    db.add(Permission(code=code, module=module, action=action,
                                      description=f"{label}-{alabel}"))
        db.flush()
        for role, mods in matrix().items():
            for module, actions in mods.items():
                for action in actions:
                    code = f"{module}.{action}"
                    if not db.query(RolePermission).filter_by(role_code=role, permission_code=code).first():
                        db.add(RolePermission(role_code=role, permission_code=code, allowed=True))
        db.flush()

        # 用户
        for username, name, role, pwd in USERS:
            if not db.query(User).filter_by(username=username).first():
                db.add(User(username=username, name=name, role_code=role,
                            password_hash=hash_password(pwd), status="ACTIVE"))

        # 参数
        for key, value in settings_service.DEFAULTS.items():
            if not db.query(Setting).filter_by(key=key).first():
                db.add(Setting(key=key, value=value,
                               is_secret=key in settings_service.SECRET_KEYS, created_by="system"))

        # 功能开关：采集类默认关闭
        for code, desc in [
            ("MAPS_COLLECTOR", "地图批量采集"), ("FB_COLLECTOR", "Facebook 归集"),
            ("BROWSER_AGENT", "browser-use 采集 Agent"), ("MCP_SERVER", "MCP 工具服务"),
            ("MATERIAL_API", "素材库 API 对接"), ("OCR_API", "图片询价 OCR"),
            ("MAIL_SMTP", "SMTP/IMAP 实发实收"), ("FEISHU_PUSH", "飞书推送"),
        ]:
            if not db.query(FeatureFlag).filter_by(code=code).first():
                db.add(FeatureFlag(code=code, enabled=False, description=desc))

        # 仓库
        for code, name, wtype in [("WH01", "成品仓", "FINISHED"), ("WH02", "样品仓", "SAMPLE"),
                                  ("WH03", "退货仓", "RETURN")]:
            if not db.query(Warehouse).filter_by(code=code).first():
                db.add(Warehouse(code=code, name=name, type=wtype, is_active="1"))

        # 汇率（1 外币 = N CNY）
        today = date.today()
        for cur, rate in [("USD", 7.12), ("SAR", 1.897), ("AED", 1.938), ("CNY", 1.0)]:
            if not db.query(ForexRate).filter_by(currency=cur, rate_type="QUOTE").first():
                db.add(ForexRate(currency=cur, rate=rate, rate_type="QUOTE",
                                 effective_date=today, source="MANUAL"))

        # 收款账户（仅财务可改）
        if not db.query(BankAccount).first():
            db.add(BankAccount(alias="Banking Circle", beneficiary="Hanpei International Trading Co., Ltd.",
                               bank_name="Banking Circle", bank_address="Copenhagen, Denmark",
                               swift="BCPLDKKK", account_no="DK00 0000 0000 0000 00",
                               account_type="USD", memo_requirements="Please indicate PI number",
                               is_active=True))
        # 分类
        for name, level in [("滤清器", 1), ("制动系统", 1), ("发动机件", 1), ("电气件", 1)]:
            if not db.query(Category).filter_by(name=name, level=level).first():
                db.add(Category(name=name, level=level, parent_id=None))

        # 产品 + OE 号
        for code, cn, en, oe, hs, price, cost, pkg, inner, carton, cbm in PRODUCTS:
            p = db.query(Product).filter_by(code=code).first()
            if p is None:
                p = Product(code=code, name_cn=cn, name_en=en, unit="PCS",
                            package_type=pkg, inner_qty=inner, carton_qty=carton,
                            carton_volume=cbm, standard_price=price, floor_price=round(price * 0.9, 2),
                            cost_price=cost, currency="USD", hs_code=hs,
                            declare_elements=f"{en}, auto parts", rebate_rate=0.13,
                            safety_stock=50, status="ACTIVE", created_by="system")
                db.add(p)
                db.flush()
            norm = normalize_oe(oe)
            if not db.query(ProductOeNumber).filter_by(product_id=p.id, oe_norm=norm).first():
                db.add(ProductOeNumber(product_id=p.id, oe_no=oe, oe_norm=norm,
                                       oe_type="OE", is_primary=True))
        db.flush()

        # 客户
        for code, name, ar, country, currency, owner, policy, days in CUSTOMERS:
            c = db.query(Customer).filter_by(code=code).first()
            if c is None:
                c = Customer(code=code, name=name, name_ar=ar, country=country,
                             currency=currency, owner_name=owner, payment_policy=policy,
                             payment_terms_days=days, level="A", status="ACTIVE",
                             source_channel="EXHIBITION", created_by="system")
                db.add(c)
        db.flush()
        c1 = db.query(Customer).filter_by(code="C0001").first()
        if c1 and not db.query(PortalAccount).filter_by(customer_id=c1.id).first():
            db.add(PortalAccount(customer_id=c1.id, username="alnoor",
                                 password_hash=hash_password("portal123"), is_active=True))

        if not db.query(Supplier).first():
            db.add(Supplier(code="S0001", name="Ningbo Auto Parts Manufacture Co., Ltd.",
                            country="CN", contact="Mr. Zhou", payment_method="MONTHLY",
                            status="ACTIVE"))

        db.commit()
        print("seed ok: roles=%d users=%d products=%d customers=%d" % (
            db.query(Role).count(), db.query(User).count(),
            db.query(Product).count(), db.query(Customer).count()))


if __name__ == "__main__":
    run()
