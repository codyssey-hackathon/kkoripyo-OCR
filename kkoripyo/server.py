"""GPU 서버용 OCR API (Tesseract). 실행: uvicorn kkoripyo.server:app --host 0.0.0.0 --port 8000

요청마다 이미지를 검증 → 글자 유무 판단 → 인식 순으로 처리하고, 이미지별 상태를 돌려준다.
입력 이미지·원문은 응답에 다시 싣지 않고, 임시 파일은 처리 직후 지운다(개인정보).
"""
import base64
import binascii
import io
import tempfile
import urllib.request
from typing import Literal, Optional

from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel, Field

from .ocr import tesseract_lines

MAX_BYTES = 10 * 1024 * 1024
MAX_IMAGES = 20
FETCH_TIMEOUT = 10

Status = Literal["ok", "no_text", "no_image", "invalid_image", "too_large", "fetch_failed"]


class ImageIn(BaseModel):
    id: str = Field(min_length=1)            # 예: "post:ABC123/0"
    url: Optional[str] = None                # 크롤러가 준 이미지 URL
    base64: Optional[str] = None             # 또는 이미지 바이트(base64)


class OcrRequest(BaseModel):
    images: list[ImageIn] = Field(min_length=1, max_length=MAX_IMAGES)


class Line(BaseModel):
    text: str
    bbox: list[int]


class ImageOut(BaseModel):
    id: str
    status: Status
    has_text: bool
    lines: list[Line]
    error: Optional[str] = None


class OcrResponse(BaseModel):
    engine: str
    results: list[ImageOut]


app = FastAPI(title="kkoripyo OCR")


@app.get("/health")
def health():
    return {"ok": True, "engine": "tesseract"}


@app.post("/ocr", response_model=OcrResponse)
def ocr(req: OcrRequest) -> OcrResponse:
    # 한 장이 실패해도 나머지는 처리한다
    return OcrResponse(engine="tesseract", results=[_one(i) for i in req.images])


def _one(img: ImageIn) -> ImageOut:
    fail = lambda status, msg: ImageOut(id=img.id, status=status, has_text=False, lines=[], error=msg)

    data, err = _load(img)
    if err:
        return fail(*err)
    try:
        im = Image.open(io.BytesIO(data))
        fmt = (im.format or "png").lower()
        im.verify()
    except Exception:
        return fail("invalid_image", "이미지로 열 수 없는 데이터")

    with tempfile.NamedTemporaryFile(suffix=f".{fmt}") as f:
        f.write(data)
        f.flush()
        lines = tesseract_lines(f.name)
    # Tesseract가 읽은 글자가 하나도 없으면 글자 없는 이미지로 판단
    return ImageOut(id=img.id, status="ok" if lines else "no_text", has_text=bool(lines),
                    lines=[Line(**l) for l in lines])


def _load(img: ImageIn) -> tuple[bytes, Optional[tuple[str, str]]]:
    if img.base64:
        try:
            data = base64.b64decode(img.base64, validate=True)
        except (binascii.Error, ValueError):
            return b"", ("invalid_image", "base64 디코딩 실패")
    elif img.url:
        if not img.url.startswith(("http://", "https://")):
            return b"", ("fetch_failed", "http(s) URL만 허용")
        try:
            with urllib.request.urlopen(img.url, timeout=FETCH_TIMEOUT) as r:
                data = r.read(MAX_BYTES + 1)
        except Exception as e:
            return b"", ("fetch_failed", f"이미지 다운로드 실패: {type(e).__name__}")
    else:
        return b"", ("no_image", "url 또는 base64 가 없음")
    if not data:
        return b"", ("no_image", "빈 이미지")
    if len(data) > MAX_BYTES:
        return b"", ("too_large", f"{MAX_BYTES // 1024 // 1024}MB 초과")
    return data, None
