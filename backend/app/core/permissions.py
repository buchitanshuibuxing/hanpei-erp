"""P0 补充：角色 × 模块 × 动作 权限矩阵（唯一事实来源）。

模块代码与前端菜单一一对应；`cost` 动作用来控制成本/毛利/底价字段可见性。
"""
MODULES = {
    "product": "产品中心", "crm": "客户关系", "quotation": "询报价",
    "order": "销售订单", "purchase": "采购管理", "inventory": "库存管理",
    "shipment": "出运跟单", "document": "单证管理", "finance": "财务管理",
    "report": "报表看板", "system": "系统管理", "material": "素材管理",
    "lead": "获客名录", "portal": "客户门户", "claim": "售后索赔",
    "mail": "邮件归档",
}
ACTIONS = {"view": "查看", "create": "新增", "edit": "编辑", "delete": "删除",
           "approve": "审批", "export": "导出", "cost": "成本可见"}

ROLES = {
    "ADMIN": "系统管理员", "MANAGER": "老板/主管", "SALES": "业务员",
    "FOLLOWER": "跟单员", "PURCHASER": "采购员", "FINANCE": "财务",
    "WAREHOUSE": "仓管",
}
ALL = set(ACTIONS)

_MATRIX = {
    "ADMIN": {m: ALL for m in MODULES},
    "MANAGER": {m: ALL for m in MODULES},
    "SALES": {
        "product": {"view", "export"}, "crm": {"view", "create", "edit"},
        "quotation": {"view", "create", "edit", "export"},
        "order": {"view", "create", "edit", "export"},
        "shipment": {"view"}, "document": {"view", "export"},
        "report": {"view", "export"}, "material": {"view", "create", "edit", "export"},
        "lead": {"view", "create", "edit"}, "portal": {"view"},
        "claim": {"view", "create"}, "mail": {"view"},
    },
    "FOLLOWER": {
        "product": {"view"}, "crm": {"view"}, "quotation": {"view"},
        "order": {"view", "edit"}, "purchase": {"view"},
        "inventory": {"view"}, "shipment": {"view", "create", "edit"},
        "document": {"view", "create", "edit", "export"},
        "report": {"view"}, "material": {"view"},
    },
    "PURCHASER": {
        "product": {"view", "edit"}, "crm": {"view"},
        "order": {"view"}, "purchase": ALL,
        "inventory": {"view"}, "shipment": {"view"},
        "report": {"view", "export"},
    },
    "FINANCE": {
        "product": {"view", "cost"}, "crm": {"view"},
        "quotation": {"view", "export"}, "order": {"view", "export"},
        "purchase": {"view", "cost"}, "inventory": {"view", "cost"},
        "shipment": {"view"}, "document": {"view", "export"},
        "finance": ALL, "report": ALL, "system": {"view"},
        "portal": {"view", "edit"}, "claim": {"view", "edit", "approve"},
    },
    "WAREHOUSE": {
        "product": {"view"}, "purchase": {"view", "edit"},
        "inventory": ALL, "shipment": {"view"}, "report": {"view"},
    },
}

COST_FIELDS = [
    "cost_price", "floor_price", "cost_snapshot", "avg_cost", "purchase_cost",
    "net_profit", "margin_pct", "commission_fee", "rebate_amount", "amount",
]


def matrix():
    return {role: {m: sorted(actions) for m, actions in mods.items()}
            for role, mods in _MATRIX.items()}


def can(role: str, module: str, action: str) -> bool:
    if role in ("ADMIN", "MANAGER"):
        return True
    return action in _MATRIX.get(role, {}).get(module, set())


def masked_fields(role: str, module: str):
    """业务员对成本类字段脱敏；财务/管理全量可见。"""
    if can(role, module, "cost") or role in ("ADMIN", "MANAGER"):
        return []
    if module in ("product", "inventory", "finance", "report", "purchase"):
        return COST_FIELDS
    return []
