"""JSON2 예측 vs 정답셋 → 탐지 정확도 + 동일정보 매칭 정확도.

정답셋 형식: {"items": [{"type": "name", "value": "홍길동", "entity": "p1"}, ...]}
  - entity 가 같은 정답 항목끼리는 '동일 정보'(예: 한글 이름 ↔ 영문 이름). 생략하면 단독.

탐지: 예측 항목이 정답 항목과 "유형이 같고 정규화 값이 같거나 한쪽이 다른 쪽을 포함"하면 적중.
      face 는 값이 자유 서술이라 유형만 맞으면 적중.
      Precision 분모 = 예측 엔티티 수(중복 제거 후), Recall 분모 = 정답 항목 수.
매칭(쌍 단위): 정답에 적중한 예측 항목들의 모든 쌍에 대해
      "예측에서 같은 엔티티인가" vs "정답에서 같은 정보인가"를 비교.
      → 중복 제거(같은 값이 여러 출처에서 나온 것)와 동일 정보 연결을 함께 평가한다.
"""
import argparse
import json
from itertools import combinations

from kkoripyo.match import normalize


def hit(gold: dict, item: dict) -> bool:
    if gold["type"] != item["type"]:
        return False
    if gold["type"] == "face":
        return True
    g, p = normalize(gold["type"], gold["value"]), item["normalized"]
    return bool(g and p) and (g == p or (min(len(g), len(p)) >= 2 and (g in p or p in g)))


def f1(p, r):
    return round(2 * p * r / (p + r), 3) if p + r else 0.0


def evaluate(pred: dict, gold: dict) -> dict:
    golds = gold["items"]
    for i, g in enumerate(golds):
        g.setdefault("entity", f"_g{i}")
    items = {it["id"]: it for it in pred["items"]}
    ent_of = {iid: e["entity_id"] for e in pred["entities"] for iid in e["item_ids"]}

    # 탐지
    gold_found = [any(hit(g, it) for it in items.values()) for g in golds]
    ent_ok = [any(hit(g, items[i]) for g in golds for i in e["item_ids"]) for e in pred["entities"]]
    P = sum(ent_ok) / len(ent_ok) if ent_ok else 0.0
    R = sum(gold_found) / len(golds)

    # 매칭: 예측 항목 → 처음 적중한 정답 항목의 entity
    gold_ent = {}
    for iid, it in items.items():
        for g in golds:
            if hit(g, it):
                gold_ent[iid] = g["entity"]
                break
    tp = fp = fn = 0
    for a, b in combinations(gold_ent, 2):
        same_pred, same_gold = ent_of[a] == ent_of[b], gold_ent[a] == gold_ent[b]
        tp += same_pred and same_gold
        fp += same_pred and not same_gold
        fn += same_gold and not same_pred
    mP = tp / (tp + fp) if tp + fp else 1.0
    mR = tp / (tp + fn) if tp + fn else 1.0

    return {
        "detection": {"precision": round(P, 3), "recall": round(R, 3), "f1": f1(P, R),
                      "missed": [f'{g["type"]}:{g["value"]}' for g, ok in zip(golds, gold_found) if not ok],
                      "false_positives": [f'{e["type"]}:{e["value"]}'
                                          for e, ok in zip(pred["entities"], ent_ok) if not ok]},
        "matching": {"pair_precision": round(mP, 3), "pair_recall": round(mR, 3), "f1": f1(mP, mR),
                     "pairs": {"tp": tp, "fp": fp, "fn": fn}},
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    ap.add_argument("--gold", required=True)
    a = ap.parse_args()
    report = evaluate(json.load(open(a.pred, encoding="utf-8")), json.load(open(a.gold, encoding="utf-8")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
