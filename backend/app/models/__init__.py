"""全部模型注册入口。新增域时在此导入，create_all 才会建表。"""
from .base import Base, JSONType, Soft, TS  # noqa: F401
from .system import (  # noqa: F401
    ApprovalFlow, ApprovalRequest, Attachment, AuditLog, FeatureFlag,
    IdempotencyKey, LoginAttempt, Notification, Permission, Role,
    RolePermission, Sequence, Setting, User, UserRole,
)
from .product import (  # noqa: F401
    Category, Product, ProductAttachment, ProductImage, ProductOeNumber,
    ProductRelation, WatermarkTemplate,
)
from .crm import (  # noqa: F401
    Customer, CustomerContact, CustomerPriceItem, FollowUp, Lead,
    SocialPost, Supplier, SupplierPriceHistory,
)
from .sales import (  # noqa: F401
    OrderChangeLog, OrderStatusLog, Quotation, QuotationItem,
    SalesOrder, SalesOrderItem,
)
from .purchase import (  # noqa: F401
    PurchaseOrder, PurchaseOrderItem, PurchaseReturn, PurchaseReturnItem,
)
from .inventory import (  # noqa: F401
    StockBalance, StockBatch, StockMove, Stocktake, StocktakeItem, Warehouse,
)
from .shipping import (  # noqa: F401
    Document, FreightCost, Shipment, ShipmentCarton, ShipmentContainer,
    ShipmentItem,
)
from .finance import (  # noqa: F401
    AfterSalesClaim, BankAccount, Commission, Expense, ForexRate, Forwarder,
    OrderProfit, Payment, PaymentAllocation, Rebate, Refund,
)
from .extended import CustomsRecord, MailMessage, PortalAccount  # noqa: F401

__all__ = ["Base", "JSONType", "TS", "Soft"]
