"""실험 전체 설정. 여기 값만 바꾸면 모든 단계에 반영됩니다."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
WORK = ROOT / "work"          # 클립·오디오·프레임 (GitHub에 올리지 않음)
RESULTS = ROOT / "results"    # 결과물 (GitHub에 올림)

SEGMENTS_CSV = DATA / "segments.csv"
ENTITIES_CSV = DATA / "entities.csv"

# --- 번역 방향 ---
# "ko2en": 한국어 중계 → 영어 자막 (기본값)
# "en2ko": 영어 중계 → 한국어 자막
DIRECTION = "ko2en"

if DIRECTION == "ko2en":
    WHISPER_LANGUAGE = "ko"
    OCR_LANGS = ["ko", "en"]
    SOURCE_LANG = "한국어"
    TARGET_LANG = "영어"
    NAME_RULES = (
        "- 선수 닉네임(ID)과 팀명은 공식 영어 표기로 씁니다. (예: 페이커 → Faker, 젠지 → Gen.G)\n"
        "- 챔피언·스킬·아이템 이름은 게임 공식 영어 명칭으로 씁니다. (예: 아지르 → Azir)\n"
    )
else:
    WHISPER_LANGUAGE = "en"
    OCR_LANGS = ["en"]
    SOURCE_LANG = "영어"
    TARGET_LANG = "한국어"
    NAME_RULES = (
        "- 선수 닉네임(ID)과 팀명은 영어 표기 그대로 둡니다. (예: Faker, Gen.G)\n"
        "- 챔피언·스킬·아이템 이름은 한국 서버 공식 한국어 명칭으로 번역합니다.\n"
    )

# --- 클립 / 프레임 ---
VIDEO_MAX_HEIGHT = 720
FRAME_POSITIONS = [0.2, 0.5, 0.8]   # 구간 길이 대비 프레임 캡처 위치 (OCR·VLM 입력)

# --- ASR (openai-whisper) ---
WHISPER_MODEL = "turbo"   # large-v3-turbo. CPU에서 너무 느리면 "small"로 바꾸세요

# --- OCR (EasyOCR) ---
OCR_MIN_CONF = 0.4
OCR_MIN_LEN = 2
OCR_MAX_TERMS = 40

# --- 번역 LLM (모든 조건에 같은 모델 사용) ---
# "gemini": Google AI Studio 무료 API (GPU 없는 노트북용, 기본값)
# "ollama": 로컬 GPU에서 qwen2.5vl 실행
LLM_BACKEND = "gemini"

# Gemini: API 키는 코드에 적지 말고 환경변수 GEMINI_API_KEY로 넣습니다 (SETUP.md 참고)
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_MIN_INTERVAL_S = 7           # 무료 티어 분당 호출 제한을 피하기 위한 호출 간격

# Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5vl:7b"
OLLAMA_OPTIONS = {"temperature": 0, "seed": 0, "num_ctx": 8192}

LLM_MODEL = GEMINI_MODEL if LLM_BACKEND == "gemini" else OLLAMA_MODEL

# 실험 조건
#  A: 음성인식 텍스트만
#  B: 음성인식 텍스트 + 화면 OCR 텍스트
#  V: 음성인식 텍스트 + 화면 이미지 직접 입력
#  O: 음성인식 텍스트 + 정답 고유명사 목록 (상한선, oracle)
CONDITIONS = ["A", "B", "V", "O"]

# --- 평가 ---
FUZZY_THRESHOLD = 85   # ASR/OCR 안에 고유명사가 있는지 판단할 때 쓰는 유사도 기준 (0~100)
BOOTSTRAP_ITERS = 2000
