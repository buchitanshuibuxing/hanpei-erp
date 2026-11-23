"""路由共用工具：文件下载（RFC 5987 中文文件名）、上传落盘、前台响应。"""
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import Response

from ..db import ROOT

UPLOAD_DIR = ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def download(content: bytes, filename: str, media_type: str):
    safe = quote(filename, safe="")
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename=\"{safe}\"; filename*=UTF-8''{safe}",
        "Access-Control-Expose-Headers": "Content-Disposition",
    })


def save_bytes(content: bytes, prefix: str, filename: str):
    folder = UPLOAD_DIR / prefix
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    path = folder / f"{stamp}_{os.path.basename(filename)}"
    path.write_bytes(content)
    return str(path.relative_to(ROOT).as_posix())


def pdf_response(content: bytes, filename: str):
    return download(content, filename, "application/pdf")


def xlsx_response(content: bytes, filename: str):
    return download(content, filename,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
