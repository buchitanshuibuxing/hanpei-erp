"""OE 号归一化：去空格/连字符/下划线，转大写。

与《素材库API开发指南（交底版）.md》第 1 节完全一致，
`25100-03011` / `25100 03011` / `25100_03011` / `2510003011` 命中同一值。
"""
import re

_STRIP = re.compile(r"[\s\-_]+")


def normalize_oe(value) -> str:
    return _STRIP.sub("", str(value or "")).upper()


def parse_oe_list(text, limit=10000):
    """把粘贴区/Excel 单元格里的多行 OE 拆成列表（保留原始写法 + 归一值）。"""
    parts = re.split(r"[\s,;，；、\n\r\t]+", str(text or ""))
    out, seen = [], set()
    for raw in parts:
        raw = raw.strip()
        if not raw:
            continue
        norm = normalize_oe(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append({"raw": raw, "norm": norm})
        if len(out) >= limit:
            break
    return out
