"""OCR → 라인 단위 텍스트 + 박스. 엔진: OCR_ENGINE=tesseract(기본) | paddle"""
import os
import re
from functools import cache

import pytesseract
from PIL import Image

_HANGUL = re.compile("[가-힣]")


def ocr_lines(path: str, lang: str = "kor+eng") -> list[dict]:
    """반환: [{text, bbox:[x,y,w,h]}]"""
    if os.getenv("OCR_ENGINE", "tesseract") == "paddle":
        return _paddle_lines(path)
    return _tesseract_lines(path, lang)


@cache
def _paddle():
    from paddleocr import PaddleOCR  # 선택 의존성: pip install paddlepaddle paddleocr
    # lang="korean" → PP-OCRv5 텍스트 검출 + korean_PP-OCRv5_mobile_rec 인식. 첫 실행 때 가중치 자동 다운로드
    return PaddleOCR(lang="korean", use_doc_orientation_classify=False,
                     use_doc_unwarping=False, use_textline_orientation=False)


def _paddle_lines(path: str) -> list[dict]:
    res = _paddle().predict(path)[0]
    return [{"text": t, "bbox": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]}
            for t, (x0, y0, x1, y1) in zip(res["rec_texts"], res["rec_boxes"]) if t.strip()]


def _tesseract_lines(path: str, lang: str) -> list[dict]:
    # psm 6(단일 블록)이 프로필 캡처류에서 가장 안정적이었음
    d = pytesseract.image_to_data(Image.open(path), lang=lang, config="--psm 6",
                                  output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[int]] = {}
    for i, word in enumerate(d["text"]):
        if word.strip() and float(d["conf"][i]) >= 0:
            lines.setdefault((d["block_num"][i], d["par_num"][i], d["line_num"][i]), []).append(i)
    out = []
    for idx in lines.values():
        x0 = min(d["left"][i] for i in idx)
        y0 = min(d["top"][i] for i in idx)
        x1 = max(d["left"][i] + d["width"][i] for i in idx)
        y1 = max(d["top"][i] + d["height"][i] for i in idx)
        # 한글은 글자 단위로 쪼개져 나오므로, 한글끼리는 간격이 글자 높이의 절반을 넘을 때만 띄어 쓴다
        text = d["text"][idx[0]]
        for prev, i in zip(idx, idx[1:]):
            gap = d["left"][i] - (d["left"][prev] + d["width"][prev])
            both_ko = _HANGUL.search(d["text"][prev][-1]) and _HANGUL.search(d["text"][i][0])
            text += ("" if both_ko and gap < 0.5 * d["height"][i] else " ") + d["text"][i]
        out.append({"text": text, "bbox": [x0, y0, x1 - x0, y1 - y0]})
    return out
