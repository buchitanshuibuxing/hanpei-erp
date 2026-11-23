"""单据 PDF：报价单/PI 按附录 A 版式，客户版装箱单按附录 B 版式。

默认英文版式（与样本 QT20260721001 一致）。中文抬头在检测到系统中文字体时启用；
阿拉伯语 RTL 需要字形整形依赖，当前版本不渲染 name_ar（见附录 E 差异说明）。
"""
import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from ..core.settings_service import get
from ..core.utils import num

BLUE = colors.HexColor("#1F4E79")
LIGHT = colors.HexColor("#EAF1F8")
GREY = colors.HexColor("#666666")
_FONT = None


def _font():
    global _FONT
    if _FONT:
        return _FONT
    for path in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                 "C:/Windows/Fonts/simsun.ttc",
                 "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"]:
        try:
            pdfmetrics.registerFont(TTFont("HanpeiCN", path, subfontIndex=0))
            _FONT = "HanpeiCN"
            return _FONT
        except Exception:
            continue
    _FONT = "Helvetica"
    return _FONT


def money(v, currency=""):
    return f"{num(v):,.2f} {currency}".strip()


def _styles():
    f = _font()
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", fontName=f, fontSize=17, textColor=BLUE,
                                alignment=2, spaceAfter=2, leading=20),
        "h": ParagraphStyle("h", fontName=f, fontSize=9, textColor=colors.white, leading=12),
        "n": ParagraphStyle("n", fontName=f, fontSize=8.5, leading=11),
        "s": ParagraphStyle("s", fontName=f, fontSize=7.5, textColor=GREY, leading=10),
        "f": f,
    }


def _company(db):
    return {
        "name": get(db, "company_name", "Hanpei International Trading Co., Ltd."),
        "country": get(db, "company_country", "China"),
        "tel": get(db, "company_tel", ""), "email": get(db, "company_email", ""),
        "address": get(db, "company_address", ""),
    }


def _base_doc(story, title, company, st):
    head = Table([[Paragraph(f"<b>{company['name']}</b><br/>{company['country']}"
                             f"&nbsp;&nbsp;Tel: {company['tel']}&nbsp;&nbsp;Email: {company['email']}", st["n"]),
                   Paragraph(title, st["title"])]], colWidths=[110 * mm, 65 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                              ("LINEBELOW", (0, 0), (-1, -1), 1.2, BLUE)]))
    story += [head, Spacer(1, 4 * mm)]


def _kv_table(rows, st, widths=None):
    data = [[Paragraph(f"<b>{k}</b>", st["n"]), Paragraph(str(v or ""), st["n"])] for k, v in rows]
    t = Table(data, colWidths=widths or [35 * mm, 55 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), st["f"]), ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _party_table(seller, buyer, st):
    data = [[Paragraph("<b>SELLER</b>", st["h"]), Paragraph("<b>BUYER</b>", st["h"])],
            [Paragraph(f"{seller['name']}<br/>{seller.get('address','')}<br/>Tel: {seller['tel']}", st["n"]),
             Paragraph(f"{buyer.get('name','')}<br/>{buyer.get('address','')}<br/>"
                       f"Tel: {buyer.get('tel','')} Attn: {buyer.get('contact','')}", st["n"])]]
    t = Table(data, colWidths=[87.5 * mm, 87.5 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _items_table(headers, rows, widths, st, money_cols=()):
    data = [[Paragraph(f"<b>{h}</b>", st["h"]) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c), st["n"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#BBBBBB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]
    for c in money_cols:
        style.append(("ALIGN", (c, 1), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


def _pdf(story, company):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm,
                            title="Hanpei ERP Document", author=company["name"])
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont(_font(), 7)
        canvas.setFillColor(GREY)
        canvas.drawString(12 * mm, 8 * mm, f"{company['name']}  |  {company['email']}")
        canvas.drawRightString(A4[0] - 12 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def build_quotation_pdf(db, q, customer, items, bank=None, is_pi=False):
    st = _styles()
    company = _company(db)
    seller = dict(company)
    buyer = {"name": customer.name if customer else "",
             "address": customer.address if customer else "",
             "tel": customer.whatsapp if customer else "",
             "contact": ""}
    title = "PROFORMA INVOICE" if is_pi else "QUOTATION / PROFORMA INVOICE"
    story = []
    _base_doc(story, title, company, st)
    story.append(_party_table(seller, buyer, st))
    story.append(Spacer(1, 3 * mm))
    cards = [
        [("NO.", getattr(q, "quote_no", "") or getattr(q, "order_no", "")),
         ("DATE", (q.created_at or "").strftime("%Y-%m-%d") if getattr(q, "created_at", None) else ""),
         ("CURRENCY", q.currency)],
        [("TRADE TERMS", q.trade_terms or ""), ("LOADING PORT", q.loading_port or ""),
         ("DESTINATION", q.destination or "")],
        [("VALID UNTIL", str(q.valid_until or "") if hasattr(q, "valid_until") else ""),
         ("DELIVERY", f"{num(getattr(q, 'delivery_days', 0)):.0f} days"),
         ("PAYMENT", "T/T")],
    ]
    for row in cards:
        t = Table([[Paragraph(f"<b>{k}</b><br/>{v}", st["n"]) for k, v in row]],
                  colWidths=[58 * mm] * 3)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.white),
                               ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.append(t)
    story.append(Spacer(1, 4 * mm))
    rows = []
    for i, it in enumerate(items, 1):
        rows.append([i, getattr(it, "oe_no", "") or "", getattr(it, "name_snapshot", "") or "",
                     getattr(it, "package_snapshot", "") or "", getattr(it, "unit", "PCS"),
                     f"{num(getattr(it, 'qty', 0)):,.0f}",
                     money(getattr(it, "unit_price", 0), ""), money(getattr(it, "amount", 0), "")])
    widths = [9 * mm, 27 * mm, 51 * mm, 24 * mm, 12 * mm, 15 * mm, 21 * mm, 22 * mm]
    story.append(_items_table(["#", "OE NO.", "PRODUCT NAME", "PACKAGE", "UNIT", "QTY",
                               "UNIT PRICE", "AMOUNT"], rows, widths, st, money_cols=(5, 6, 7)))
    subtotal = num(getattr(q, "subtotal", 0))
    discount = num(getattr(q, "discount_amount", 0) or getattr(q, "discount", 0))
    total = num(getattr(q, "total", 0))
    summary = Table([["", "Subtotal", money(subtotal, q.currency)],
                     ["", f"Discount ({num(getattr(q, 'discount_pct', 0)):.0f}%)", money(discount, q.currency)],
                     ["", "TOTAL", money(total, q.currency)]],
                    colWidths=[100 * mm, 40 * mm, 41 * mm])
    summary.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), st["f"]), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("LINEABOVE", (1, 2), (2, 2), 0.8, BLUE),
        ("BACKGROUND", (1, 2), (2, 2), LIGHT), ("FONTNAME", (1, 2), (2, 2), st["f"]),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [Spacer(1, 2 * mm), summary, Spacer(1, 4 * mm)]
    terms = getattr(q, "payment_terms_json", None) or [{"pct": 30, "label": "Deposit"},
                                                       {"pct": 70, "label": "Before shipment"}]
    lines = [f"T/T {t.get('pct')}% {t.get('label','')}: {money(total * num(t.get('pct')) / 100, q.currency)}"
             for t in terms]
    story.append(Paragraph("<b>PAYMENT TERMS</b>", st["n"]))
    for line in lines:
        story.append(Paragraph(line, st["n"]))
    story.append(Spacer(1, 3 * mm))
    if bank:
        story.append(Paragraph("<b>BANK DETAILS</b>", st["n"]))
        story.append(_kv_table([("Beneficiary", bank.beneficiary), ("Bank", bank.bank_name),
                                ("Address", bank.bank_address), ("SWIFT", bank.swift),
                                ("Account", bank.account_no),
                                ("Memo", bank.memo_requirements)], st,
                               [35 * mm, 140 * mm]))
    note = getattr(q, "footer_note", "") or "This quotation is valid until the date stated above."
    story += [Spacer(1, 3 * mm), Paragraph(note, st["s"])]
    return _pdf(story, company)


def build_packing_list_pdf(db, shipment, order, customer, cartons, items):
    st = _styles()
    company = _company(db)
    story = []
    _base_doc(story, "PACKING LIST", company, st)
    story.append(_party_table(dict(company), {
        "name": customer.name if customer else "",
        "address": customer.address if customer else "", "tel": "", "contact": ""}, st))
    story.append(Spacer(1, 3 * mm))
    story.append(_kv_table([
        ("PL NO.", shipment.shipment_no), ("DATE", str(shipment.etd or "")),
        ("ORDER NO.", order.order_no if order else ""), ("BL NO.", shipment.bl_no or ""),
        ("TOTAL CTN", num(shipment.total_ctn)), ("TOTAL CBM", f"{num(shipment.total_cbm):.3f}"),
        ("TOTAL WEIGHT", f"{num(shipment.total_weight):.2f} KG"),
    ], st, [35 * mm, 140 * mm]))
    story.append(Spacer(1, 4 * mm))
    rows = [[i + 1, getattr(it, "name_snapshot", "") or "", getattr(it, "oe_no", "") or "",
             f"{num(getattr(it, 'qty', 0)):,.0f}", getattr(it, "ctn_no", "") or ""]
            for i, it in enumerate(items)]
    story.append(_items_table(["NO.", "PART NAME", "OE NO.", "QTY", "CTN."], rows,
                              [12 * mm, 72 * mm, 38 * mm, 25 * mm, 28 * mm], st,
                              money_cols=(3,)))
    story.append(Spacer(1, 4 * mm))
    if cartons:
        crows = [[c.ctn_no, f"{num(c.length)} x {num(c.width)} x {num(c.height)}",
                  f"{num(num(c.length) * num(c.width) * num(c.height)):.3f}",
                  f"{num(c.weight):.2f}", c.note or ""] for c in cartons]
        story.append(Paragraph("<b>CARTON DETAILS</b>", st["n"]))
        story.append(_items_table(["C/NO.", "SIZE (M)", "CBM", "WEIGHT (KG)", "NOTE"], crows,
                                  [22 * mm, 45 * mm, 25 * mm, 30 * mm, 53 * mm], st))
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph("Total quantity / Total cartons / Measurement / Total CBM / TOTAL WEIGHT "
                           "are calculated from the shipment cartons above.", st["s"]))
    return _pdf(story, company)
