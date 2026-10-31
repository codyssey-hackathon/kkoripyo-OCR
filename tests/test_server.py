"""OCR 서버 요청 검증 테스트. 실행: python -m pytest tests (fastapi, httpx 필요)"""
import base64
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from kkoripyo import server  # noqa: E402

client = TestClient(server.app)


def _png(color="white") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), color).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _post(images):
    return client.post("/ocr", json={"images": images})


def test_request_level_validation():
    assert _post([]).status_code == 422                       # 이미지 목록이 비어 있음
    assert client.post("/ocr", json={}).status_code == 422     # images 필드 없음
    assert _post([{"id": str(i), "base64": _png()} for i in range(21)]).status_code == 422  # 개수 초과


def test_per_image_status(monkeypatch):
    seen = []
    monkeypatch.setattr(server, "tesseract_lines", lambda p: seen.append(p) or [])  # 글자 없음
    big = base64.b64encode(b"0" * (server.MAX_BYTES + 1)).decode()
    r = _post([
        {"id": "empty"},                                       # url/base64 둘 다 없음
        {"id": "bad64", "base64": "%%%"},
        {"id": "notimg", "base64": base64.b64encode(b"hello").decode()},
        {"id": "big", "base64": big},
        {"id": "ftp", "url": "ftp://x/y.png"},
        {"id": "blank", "base64": _png()},                     # 글자 없는 이미지
    ])
    assert r.status_code == 200
    got = {x["id"]: x["status"] for x in r.json()["results"]}
    assert got == {"empty": "no_image", "bad64": "invalid_image", "notimg": "invalid_image",
                   "big": "too_large", "ftp": "fetch_failed", "blank": "no_text"}
    assert _png() not in r.text  # 입력 이미지를 응답에 되돌려주지 않음
    assert all(not os.path.exists(p) for p in seen)  # 임시 파일 삭제됨


def test_text_found(monkeypatch):
    monkeypatch.setattr(server, "tesseract_lines", lambda p: [{"text": "홍길동", "bbox": [1, 2, 3, 4]}])
    res = _post([{"id": "card", "base64": _png()}]).json()["results"][0]
    assert res == {"id": "card", "status": "ok", "has_text": True,
                   "lines": [{"text": "홍길동", "bbox": [1, 2, 3, 4]}], "error": None}
