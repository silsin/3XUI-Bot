"""ساخت QR به‌صورت PNG در حافظه (بدون وابستگی سنگین)."""

from __future__ import annotations

import io

import segno


def make_qr_png(data: str, scale: int = 6, border: int = 2) -> bytes:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=scale, border=border)
    return buf.getvalue()
