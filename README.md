# kkoripyo-OCR

SNS 프로필·게시글·댓글 텍스트와 사진에서 **개인정보를 찾아내고(OCR · Vision LLM · LLM)**, 
**유형·값·근거·출처로 구조화**한 뒤 **중복 제거 + 동일 정보 매칭**까지 해서 **JSON2**로 내보내는 모듈입니다.

```
크롤러 결과(JSON1: 프로필·캡션·댓글)  ─┐
게시물 이미지 ─────────────────────────┼─▶ kkoripyo ─▶ JSON2 ─▶ 관계 그래프 · 위험 점수(다른 파트)
추가 텍스트 ───────────────────────────┘
```

## 담당 범위

| 항목 | 구현 위치 | 상태 |
|---|---|---|
| 개인정보 탐지·분류 기준 정의 (개인정보보호위원회·법령 참고) | `kkoripyo/schema.py` `TAXONOMY` | ✅ |
| 텍스트(프로필, 게시글, 댓글)에서 개인정보 추출 | `rules.py`(정규식) + `llm.py`(LLM) | ✅ |
| OCR로 사진 속 텍스트 추출 | `ocr.py` (Tesseract `kor+eng` / PaddleOCR `korean_PP-OCRv5_mobile_rec`) | ✅ Tesseract / ⚠️ Paddle 실행 미검증 |
| Vision LLM으로 사진 속 개인정보·식별 단서 탐지 | `llm.py` `extract_image` (OpenAI) | ✅ 코드 / ⚠️ 실호출 미검증 |
| 유형·값·근거·출처로 구조화 (Structured Outputs) | `schema.py` (Pydantic → `chat.completions.parse`) | ✅ |
| 중복 제거 및 동일 정보 매칭 | `match.py` | ✅ |
| 탐지 정확도 / 매칭 정확도 평가 | `evaluate.py` | ✅ |

## 처리 흐름

```
1. 텍스트 소스 수집   profile.full_name / profile.biography / post:<코드>.caption / post:<코드>.commentN
2. 이미지 OCR        Tesseract psm 6 → 라인별 텍스트 + bbox (한글 글자단위 분리 → 간격 기준으로 다시 붙임)
3. 규칙 탐지          텍스트·OCR 라인에 정규식 적용 (주민번호, 전화, 이메일, 카드, 학번, 차량번호, 소속 …)
4. LLM 탐지 (선택)    · 텍스트: 모든 소스를 [source_id] 로 묶어 1회 호출
                     · 이미지: 이미지 + OCR 결과를 함께 보내 Vision LLM 1회 호출 (얼굴, 명찰, 교복, 장소 등)
                     · 응답은 Structured Outputs(LLMFindings 스키마)로 강제
5. 구조화            모든 탐지 결과 → PIIItem(유형·분류·값·정규화값·근거·출처·신뢰도)
6. 매칭              같은 유형 안에서 union-find 로 묶어 Entity 생성
```

규칙(3)은 API 없이도 돌아가는 **기준선**이고, LLM(4)은 규칙이 못 잡는 이름·얼굴·문맥 단서를 보강합니다. 둘의 결과는 6단계에서 합쳐집니다.

## 개인정보 분류 기준

| type | 분류 | 설명 | 근거 |
|---|---|---|---|
| `rrn` `passport` `driver_license` `alien_reg` | 고유식별정보 | 주민등록·여권·운전면허·외국인등록번호 | 개인정보 보호법 제24조, 시행령 제19조 |
| `sensitive` | 민감정보 | 사상·신념, 노조·정당, 정치적 견해, 건강, 성생활, 유전·범죄경력, 생체인식, 인종·민족 | 법 제23조, 시행령 제18조 |
| `card_number` `bank_account` | 금융정보 | 카드번호, 계좌번호 | 유출 시 직접 피해 |
| `name` `phone` `email` `address` `birth_date` `student_id` `vehicle_plate` `sns_account` `face` | 일반개인정보 | 그 자체로 개인을 알아볼 수 있는 정보 | 법 제2조 제1호 가목 |
| `affiliation` `location` `other_clue` | 준식별자 | 단독으론 약하지만 **결합하면** 식별 가능 (소속, 위치, 학년·재학상태, 교복·명찰 …) | 법 제2조 제1호 나목, 가명정보 처리 가이드라인의 식별자/준식별자 구분 |

- `face`: 얼굴 사진은 알아볼 수 있으면 개인정보. 특징을 추출해 식별에 쓰면 생체인식정보(민감정보)가 되지만, 이 모듈은 "노출 여부"만 판단하므로 일반개인정보로 둡니다.
- 서비스 목적이 "제3자가 무엇을 알아낼 수 있나"이므로 **준식별자도 적극적으로 수집**합니다. 결합 위험 계산은 다음 단계(관계 그래프)의 몫입니다.
- 표는 `TAXONOMY` 한 곳에서 관리하고, LLM 프롬프트도 이 표로 자동 생성됩니다.

## JSON2 스키마

```jsonc
{
  "schema_version": "json2/v1",
  "subject": "gildong_hong",          // 분석 대상 계정
  "llm_used": false,                  // LLM 단계가 실제로 돌았는지
  "items": [                          // 탐지된 개별 결과 (출처마다 1개)
    {
      "id": "I4",
      "type": "phone",
      "category": "일반개인정보",
      "value": "010.1234.5678",       // 원문 값
      "normalized": "01012345678",    // 매칭용 정규화 값
      "evidence": "📞 010.1234.5678", // 근거 (주변 문맥 또는 LLM 설명)
      "source": {
        "input_id": "profile.biography",            // 어디서
        "modality": "text",                         // text | image
        "method": "regex",                          // regex | ocr+regex | profile_field | llm | vision_llm
        "bbox": null                                // 이미지면 [x, y, w, h]
      },
      "confidence": 0.9
    }
    // I8: 댓글의 010-1234-5678, I17: 학생증 이미지 OCR의 010-1234-5678 …
  ],
  "entities": [                       // 동일 정보로 묶인 결과
    {
      "entity_id": "E3",
      "type": "phone",
      "value": "010.1234.5678",       // 대표값
      "item_ids": ["I4", "I8", "I17"],
      "sources": ["profile.biography", "post:FAKE001.comment0", "image:fake_card.png"],
      "match_reasons": ["normalized"],
      "confidence": 0.9
    }
  ]
}
```

`entities[].sources` 가 "같은 정보가 몇 군데에 노출됐는가"를 바로 보여주므로 위험 점수 계산에 그대로 쓸 수 있습니다.

## 동일 정보 매칭 규칙

같은 `type` 끼리만 비교하고, 하나라도 맞으면 같은 엔티티로 묶습니다(union-find).

| 규칙 | 예 | `match_reasons` |
|---|---|---|
| 정규화 값 일치 (숫자형은 숫자만, 이메일·계정은 소문자, 나머지는 공백·괄호 제거) | `010.1234.5678` = `010-1234-5678` | `normalized` |
| 이름 한글 ↔ 영문: 한글을 로마자로 바꾼 뒤 표기 흔들림(k/g, oo/u, ee/i, eo/u, r/l …)을 접어서 유사도 ≥ 0.8 | `홍길동` = `Hong Gildong` = `Gildong Hong` | `romanization` |
| 소속·주소 포함 관계 (짧은 쪽 4자 이상) | `컴퓨터공학과` ⊂ `한국대학교 컴퓨터공학과` | `contains` |
| 얼굴: 한 분석 안의 얼굴은 같은 사람으로 가정 | | `face` |

규칙으로 찾은 영문 이름(`Hong Gildong` 형태)은 오탐이 많아서 **한글 이름과 짝이 맞을 때만** 남깁니다(`Life Captured` 같은 캡션은 버려짐).

## 실행

```bash
# 1) Tesseract + 한국어 언어팩
brew install tesseract tesseract-lang          # macOS
# sudo apt install tesseract-ocr tesseract-ocr-kor   # Ubuntu (해커톤 서버)

# 2) 파이썬 패키지
pip install -r requirements.txt

# 3) API 키 (.env 는 커밋 금지)
cp .env.example .env    # OPENAI_API_KEY 입력, 모델 변경은 OPENAI_MODEL

# 4) 실행
python -m kkoripyo --profile samples/fake_profile.json --image samples/fake_card.png -o out.json
python -m kkoripyo --image some.jpg --text "댓글 내용" --no-llm      # OCR+정규식만
```

### OCR 엔진 선택

| `OCR_ENGINE` | 모델 | 설치 |
|---|---|---|
| `tesseract` (기본) | Tesseract 5 `kor+eng` | 위 1) |
| `paddle` | PaddleOCR PP-OCRv5 검출 + [`korean_PP-OCRv5_mobile_rec`](https://aistudio.baidu.com/modelsdetail/31927/intro) 인식 | `pip install paddlepaddle paddleocr` (첫 실행 때 가중치 자동 다운로드) |

```bash
OCR_ENGINE=paddle python -m kkoripyo --image private/student_card.jpg --no-llm -o private/out_paddle.json
python evaluate.py --pred private/out_paddle.json --gold private/student_card.gold.json
```

장소·얼굴·간판·교복 같은 **글자가 아닌 단서는 OCR로는 못 잡고** Vision LLM 단계(`llm.py`)에서 `location` / `face` / `other_clue` 로 찾습니다.

`OPENAI_API_KEY` 가 없으면 경고를 띄우고 OCR+정규식만으로 돌며, 출력의 `llm_used` 가 `false` 가 됩니다.

## 평가

```bash
python evaluate.py --pred out.json --gold samples/fake.gold.json
python -m pytest tests          # 또는 python tests/test_pipeline.py
```

정답셋 형식: `{"items": [{"type": "name", "value": "홍길동", "entity": "p1"}, ...]}` — `entity` 가 같은 항목은 동일 정보.

| 지표 | 정의 |
|---|---|
| 탐지 Precision | 정답과 맞는 예측 엔티티 / 전체 예측 엔티티 (중복 제거 후 기준) |
| 탐지 Recall | 예측에 잡힌 정답 항목 / 전체 정답 항목 |
| 매칭 Pair P/R/F1 | 정답에 적중한 예측 항목들의 모든 쌍에 대해 "예측에서 같은 엔티티인가" vs "정답에서 같은 정보인가" 비교 → 중복 제거와 동일 정보 연결을 함께 평가 |

적중 조건: 유형이 같고 정규화 값이 같거나 한쪽이 다른 쪽을 포함(`1학년` ↔ `1학년(기)`). `face` 는 유형만 맞으면 적중.

### 현재 결과 (OCR + 정규식만, LLM 미사용)

| 데이터 | 탐지 P | 탐지 R | 탐지 F1 | 매칭 F1 | 놓친 것 / 오탐 |
|---|---|---|---|---|---|
| `samples/` 가상 인물 (프로필 + 학생증 이미지) | 0.80 | 0.90 | 0.85 | 1.00 | 놓침: `26학번` / 오탐: `연락처`·`길동아`(이름 휴리스틱) |
| 실제 학생증 캡처 1장 (비공개, `private/`) | 1.00 | 0.71 | 0.83 | 1.00 | 놓침: `재학`(흰 글씨/파란 배경 OCR 실패), 얼굴 |

놓친 항목은 모두 Vision LLM 이 맡을 영역(얼굴, 배경색 위 글자, 문맥 단서)입니다. **LLM 포함 수치는 API 키로 직접 돌려서 이 표에 추가해야 합니다** (아래 "남은 문제").

## 개인정보 취급 주의

- 실제 사람의 사진·정답셋·출력물은 **`private/` 에만** 두세요. `.gitignore` 로 제외되어 있습니다. 커밋 전 `git status` 로 다시 확인.
- `samples/` 는 전부 **가상 인물**(홍길동, `example.com`)입니다. 실데이터를 여기에 넣지 마세요.
- `.env`, API 키는 커밋 금지. 필요한 키 이름은 `.env.example` 에만.
- OpenAI 로 이미지를 보내면 외부 전송입니다. 시연·테스트는 본인 동의를 받은 데이터로만.

## 남은 문제

- **Vision LLM 실호출 미검증**: 개발 환경에서 `api.openai.com` 접근이 막혀 있어, LLM 단계는 대역(stub) 클라이언트로 병합 로직만 테스트했습니다. 키를 넣고 `private/` 데이터로 한 번 돌려 위 표를 채워주세요. 기본 모델은 `gpt-4o-mini`, `.env` 의 `OPENAI_MODEL` 로 변경.
- **PaddleOCR 실행 미검증**: 개발 환경에서 모델 가중치 서버 접근이 막혀, 결과 변환 로직만 대역으로 테스트했습니다. 맥에서 위 명령으로 돌려 Tesseract 수치와 비교해 주세요.
- 규칙 기반 이름 탐지는 "3음절 + 흔한 성씨" 휴리스틱이라 오탐(`연락처`)이 납니다. LLM 사용 시 LLM 결과를 우선 보세요.
- 얼굴 매칭은 "한 분석 = 한 사람" 가정. 여러 사진에 여러 얼굴이면 얼굴 임베딩 비교가 필요합니다.
- 서로 다른 유형 간 연결(이 이름 ↔ 이 학번이 같은 사람)은 하지 않습니다. 관계 그래프 파트에서 `entities` 를 노드로 쓰면 됩니다.
- 정답셋이 아직 2건뿐이라 수치는 참고용입니다. 팀 테스트 데이터를 `private/` 에 모아 늘려야 합니다.

## 참고

- 개인정보 보호법 제2조(정의), 제23조(민감정보), 제24조(고유식별정보), 제24조의2(주민등록번호 처리 제한)
- 개인정보보호위원회, 가명정보 처리 가이드라인 — 식별자·준식별자 구분
- 개인정보보호위원회, 인공지능(AI) 개발·서비스를 위한 공개된 개인정보 처리 안내서 — 공개 SNS 데이터 수집·활용 시 참고
- OpenAI Structured Outputs — Pydantic 모델로 응답 형식 강제
