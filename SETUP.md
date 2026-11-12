# 실행 가이드 (노트북, GPU 없이)

**한국어 중계 → 영어 자막** 실험입니다. 음성인식(Whisper)과 OCR(EasyOCR)은 노트북 CPU로 돌리고, 번역은 Google Gemini 무료 API로 합니다.
(`config.py`의 `DIRECTION = "en2ko"`로 바꾸면 영어 중계 → 한국어 자막으로도 돌릴 수 있습니다.)
네 가지 번역 조건(A/B/V/O)에 **같은 Gemini 모델**을 쓰기 때문에 입력 정보의 효과만 비교할 수 있습니다.

## 0. 일정
| 언제 | 할 일 | 예상 시간 |
|---|---|---|
| 11/11 오전 | 1. 설치, API 키 발급 | 30분 |
| 11/11 오후 | 2. 구간 고르기 + 3. 정답 라벨링 | 3~4시간 |
| 11/11 저녁 | 4. 파이프라인 실행 (step1~4) | 1~2시간 (대부분 기다리는 시간) |
| 11/12 오전 | 5. 평가, 오류 유형 라벨링 | 2시간 |
| 11/12 오후 | 6. README 정리, GitHub 업로드 | 2시간 |

---

## 1. 설치 (VS Code 터미널, PowerShell)

### 1-1. ffmpeg (영상·오디오 자르기용)
```powershell
winget install Gyan.FFmpeg
```
설치 후 **VS Code를 껐다 켜고** `ffmpeg -version`이 나오는지 확인하세요.

### 1-2. 가상환경과 패키지
압축을 푼 폴더를 VS Code로 열고 터미널에서:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
- PyTorch CPU 버전이 같이 설치됩니다. 용량이 커서 몇 분 걸릴 수 있습니다.
- `activate`에서 "스크립트를 실행할 수 없습니다" 오류가 나면 먼저 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 실행하세요.

### 1-3. Gemini API 키 (무료)
1. https://aistudio.google.com 에 **개인 Google 계정**으로 로그인합니다. 산학 프로젝트 때 쓴 회사 키는 쓰지 마세요.
2. **Get API key → Create API key**를 누르고 키를 복사합니다.
3. 터미널에서 환경변수로 등록합니다. **코드나 GitHub에는 절대 넣지 마세요.**
```powershell
setx GEMINI_API_KEY "복사한_키"
```
4. VS Code를 껐다 켠 뒤 `echo $env:GEMINI_API_KEY`로 확인합니다.

- `config.py`의 `GEMINI_MODEL`은 `gemini-3.1-flash-lite`로 설정돼 있습니다.
- 무료 티어는 분당 호출 수 제한이 있어서 호출 사이에 7초씩 쉬도록 해 뒀습니다. 30구간 × 4조건 = 120번 호출이면 약 15~20분 걸립니다. 429 오류가 계속 나면 `GEMINI_MIN_INTERVAL_S`를 15로 늘리세요.

### CPU 예상 시간 (30구간 기준)
| 단계 | 예상 시간 | 너무 느릴 때 |
|---|---|---|
| step2 Whisper `turbo` | 15~40분 | `config.py`의 `WHISPER_MODEL = "small"` |
| step3 EasyOCR (프레임 90장) | 5~15분 | `FRAME_POSITIONS = [0.5]`로 프레임 1장만 |

---

## 2. 구간 고르기 → `data/segments.csv`

**Worlds 2026 한국어 중계 VOD**(LCK 공식 YouTube 또는 치지직 다시보기)에서 10~20초 구간을 **25~30개** 고릅니다.
- 치지직 VOD가 step1에서 다운로드되지 않으면 YouTube에 올라온 한국어 중계 영상을 쓰세요.

**고르는 기준**
- 해설이 **선수명, 팀명, 챔피언명, 스킬명**을 말하는 구간
- 한 경기에 몰리지 않게 **여러 경기와 여러 팀**에서 고르기
- 화면 구성을 골고루 섞기. 이 분석이 화면 구성별 효과 비교가 됩니다.
  - `ingame`: 인게임 (하단 스코어보드와 선수 캠)
  - `draft`: 밴픽 화면 (선수명과 챔피언명이 크게 보임)
  - `replay`: 리플레이나 하이라이트 (화면 텍스트가 적음)
  - `desk`: 분석 데스크나 인터뷰
- **일부러 섞을 것**: 화면에 이름이 **안 보이는데** 해설이 언급하는 구간도 5개 이상 넣으세요. "화면 정보가 소용없는 경우"도 결과의 일부입니다.

**작성법**
```csv
seg_id,url,start,end,screen_type,note
s01,https://www.youtube.com/watch?v=XXXX,1:02:15,1:02:30,ingame,T1 vs GEN 1세트 한타
s02,https://www.youtube.com/watch?v=XXXX,0:08:40,0:08:55,draft,밴픽
```
- 시간은 `시:분:초` 또는 `분:초` 형식입니다. 구간 하나는 **10~20초**로 잡으세요. Whisper는 짧을수록 정확합니다.

---

## 3. 정답 라벨링 → `data/entities.csv`

각 구간에서 **해설이 실제로 말한** 고유명사만 적습니다. 화면에만 있고 말하지 않은 이름은 적지 않습니다.

```csv
seg_id,entity_type,spoken_form,accepted,on_screen
s01,player,페이커,Faker,Y
s01,champion,아지르,Azir,Y
s01,skill,황제의 진영,Emperor's Divide,N
s02,team,젠지,Gen.G|GenG|Gen G,Y
```

| 칸 | 설명 |
|---|---|
| `entity_type` | `player`, `team`, `champion`, `skill`, `item`, `other` 중 하나 |
| `spoken_form` | 해설이 말한 이름의 **올바른 한국어 표기** (예: 페이커, 쵸비, 아지르). 음성인식이 맞게 들었는지 확인하는 데 씁니다. 영문 약칭처럼 한글·영문 어느 쪽으로 받아써도 맞는 이름은 `\|`로 함께 적습니다 (예: `아이지\|IG`, `티원\|T1`). 대체 표기는 **ASR 결과를 보기 전에** 정합니다 |
| `accepted` | 영어 번역문에 들어 있으면 **정답으로 인정할 영어 표기**. `\|`로 구분합니다. 일반 영어 단어와 겹치는 ID는 앞에 `=`를 붙이면 대소문자까지 일치해야 인정합니다 (예: `=ON`, `=Career`). 선수·팀은 공식 영어 ID, 챔피언·스킬은 게임 공식 영어 이름 |
| `on_screen` | 선택한 프레임 시점의 **화면에 그 이름이 보이는지** (Y/N). 확인은 step1 이후 `work/frames/s01/` 이미지를 보고 하세요 |

**팁**
- 라벨링은 **ASR 결과를 보기 전에** 영상을 직접 들으면서 하세요. 결과를 보고 정답을 정하면 편향이 생깁니다.
- 목표는 **고유명사 80~120개**입니다. 구간 하나에 평균 3~4개입니다.

---

## 4. 파이프라인 실행
```powershell
python step1_clips.py       # 구간 다운로드, 오디오·프레임 추출  → work/
python step2_asr.py         # Whisper 음성인식               → work/asr.jsonl
python step3_ocr.py         # EasyOCR 화면 텍스트            → work/ocr.jsonl
python step4_translate.py   # 4조건 번역                      → work/translations.jsonl
```
- 각 단계는 중간에 끊겨도 다시 실행하면 **이어서 진행**합니다. 처음부터 다시 하려면 `--force`를 붙이세요.
- 먼저 **구간 2~3개만** 넣고 step1~5를 끝까지 돌려 보세요. 문제가 없으면 나머지 구간을 추가해서 다시 실행하면 됩니다(이미 처리된 구간은 건너뜁니다).
- 데스크탑(RTX 5060)에 환경을 갖추면 `config.py`의 `LLM_BACKEND = "ollama"`로 로컬 모델(qwen2.5vl:7b)을 쓸 수도 있습니다. 이번 마감에는 노트북 + Gemini 조합을 추천합니다.
- step1 이후 `work/frames/`의 이미지를 보고 `entities.csv`의 `on_screen`을 채우세요.

## 5. 평가
```powershell
python step5_evaluate.py
```
결과는 `results/`에 생깁니다.
- `summary.md`: 조건별 정확도, 케이스별 정확도, McNemar 검정, 유형별·화면별 정확도, OCR 재현율
- `accuracy_by_case.png`: README에 넣을 그래프
- `review.csv`: 틀린 사례 목록. **`error_type` 칸을 채우고** 다시 실행하면 오류 유형 집계가 추가됩니다.

**`error_type`에 쓸 분류** (같은 이름으로 통일하세요)
- `ASR 오인식`: 음성인식이 이름을 다른 말로 받아씀 (페이커 → 페이크, 쵸비 → 초비)
- `철자 오류`: 이름은 맞게 들었는데 영어 ID 철자를 틀림 (쵸비 → Chobi)
- `공식명 오류`: 챔피언이나 스킬을 공식 영어 이름이 아닌 말로 번역함 (황제의 진영 → Emperor's Camp)
- `화면 단서 없음`: 화면에 정보가 없어서 고칠 방법이 없었음
- `OCR 오류`: 화면에는 있었는데 OCR이 못 읽었거나 잘못 읽음
- `단서 무시`: 정보를 줬는데도 LLM이 반영하지 않음
- `과잉 삽입`: 화면에만 있고 말하지 않은 이름을 끼워 넣음

## 6. GitHub 업로드
- `work/` 폴더(영상, 오디오, 프레임)는 `.gitignore`에 들어 있어 **올라가지 않습니다**. 영상 원본은 공개하지 마세요.
- `README.md`의 `[ ]` 부분을 결과 숫자로 채우고, 그래프와 대표 사례 3~5개를 넣으세요.
