"""실행: python -m pytest tests  (또는 python tests/test_pipeline.py). 가상 인물 데이터만 사용."""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytesseract  # noqa: E402

from evaluate import evaluate  # noqa: E402
from kkoripyo import rules  # noqa: E402
from kkoripyo.match import normalize, same_name  # noqa: E402
from kkoripyo.pipeline import run  # noqa: E402
from kkoripyo.schema import LLMFinding, LLMFindings  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "samples")
HAS_KOR = "kor" in pytesseract.get_languages()


def test_normalize():
    assert normalize("phone", "010.1234.5678") == normalize("phone", "010-1234-5678") == "01012345678"
    assert normalize("email", "A.B@Example.com") == "a.b@example.com"


def test_romanization():
    assert same_name("홍길동", "Hong Gildong")
    assert same_name("홍길동", "Gildong Hong")
    assert same_name("이민호", "Lee Minho")
    assert same_name("박지성", "Park Jisung")
    assert not same_name("홍길동", "Kim Minsu")
    assert not same_name("Hong Gildong", "Hong Gildong")  # 같은 문자 체계끼리는 normalize 로 처리


def test_rules_no_overlap():
    types = [h["type"] for h in rules.find("카드 1234-5678-9012-3456 결제")]
    assert types == ["card_number"]  # 카드번호 일부가 전화번호로 중복 탐지되지 않음
    assert [h["type"] for h in rules.find("주민번호 900101-1234567")] == ["rrn"]


def _stub(responses):
    """OpenAI 클라이언트 대역: 호출 순서대로 LLMFindings 를 돌려준다."""
    it = iter(responses)
    parse = lambda **_: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=next(it)))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))


def test_llm_merge():
    client = _stub([LLMFindings(findings=[
        LLMFinding(source_id="profile.biography", type="other_clue", value="26학번", evidence="바이오", confidence=0.8),
        LLMFinding(source_id="없는소스", type="name", value="홍길동", evidence="이름", confidence=0.9),
    ])])
    res = run(profile=json.load(open(os.path.join(ROOT, "fake_profile.json"), encoding="utf-8")), client=client)
    by_val = {e.value: e for e in res.entities}
    assert "26학번" in by_val
    name = next(e for e in res.entities if e.type == "name" and "홍길동" in e.value)
    methods = {i.source.method for i in res.items if i.id in name.item_ids}
    assert {"llm", "profile_field"} <= methods  # LLM 결과가 기존 이름 엔티티로 합쳐짐


def test_fake_sample_end_to_end():
    if not HAS_KOR:
        print("skip: tesseract kor 언어팩 없음")
        return
    res = run(images=[os.path.join(ROOT, "fake_card.png")],
              profile=json.load(open(os.path.join(ROOT, "fake_profile.json"), encoding="utf-8")), use_llm=False)
    rep = evaluate(json.loads(res.model_dump_json()), json.load(open(os.path.join(ROOT, "fake.gold.json"), encoding="utf-8")))
    assert rep["detection"]["recall"] >= 0.8, rep
    assert rep["matching"]["f1"] == 1.0, rep


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
