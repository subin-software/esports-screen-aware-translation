"""4단계: 같은 LLM(Gemini 또는 Ollama)에 입력 정보만 바꿔 4가지 조건으로 번역합니다. -> work/translations.jsonl

  A: 음성인식 텍스트만
  B: 음성인식 텍스트 + 화면 OCR 텍스트
  V: 음성인식 텍스트 + 화면 이미지(프레임) 직접 입력
  O: 음성인식 텍스트 + 정답 고유명사 목록 (상한선)

사용: python step4_translate.py                 # 모든 조건
      python step4_translate.py --cond A B      # 일부 조건만
      python step4_translate.py --force         # 다시 번역
"""
import argparse
import base64
import collections
import json
import os
import time

import requests

import config
from common import segments, frame_paths, read_jsonl, read_csv

ASR = config.WORK / "asr.jsonl"
OCR = config.WORK / "ocr.jsonl"
OUT = config.WORK / "translations.jsonl"

SYSTEM = (
    f"당신은 리그 오브 레전드 e스포츠 생중계의 {config.SOURCE_LANG} 해설을 실시간 {config.TARGET_LANG} 자막으로 번역하는 번역가입니다.\n"
    "규칙:\n"
    + config.NAME_RULES
    + "- 음성인식 결과에는 고유명사가 잘못 들린 오류가 있을 수 있습니다. 주어진 참고 정보가 있으면 그것을 근거로 바로잡으세요.\n"
    "- 참고 정보에 있더라도 해설에서 언급되지 않은 내용은 추가하지 마세요.\n"
    "- 번역문만 출력하세요. 설명, 따옴표, 원문은 쓰지 마세요."
)


def build_prompt(cond, asr_text, ocr_terms, frames, oracle):
    """조건별 사용자 프롬프트와 첨부 이미지(base64 jpg 목록)를 만듭니다."""
    user = f"[해설 음성인식 결과]\n{asr_text}\n"
    images = []
    if cond == "B":
        terms = ", ".join(ocr_terms) if ocr_terms else "(없음)"
        user += f"\n[같은 시점 중계 화면에서 OCR로 읽은 텍스트 — 인식 오류가 섞여 있을 수 있음]\n{terms}\n"
    elif cond == "V":
        user += "\n[첨부 이미지: 같은 시점의 중계 화면 캡처]\n"
        images = [base64.b64encode(p.read_bytes()).decode() for p in frames]
    elif cond == "O":
        gl = "\n".join(f"- {src} → {tgt}" for src, tgt in oracle) or "(없음)"
        user += f"\n[이 구간에 등장하는 고유명사 정답 목록]\n{gl}\n"
    user += f"\n위 해설을 {config.TARGET_LANG} 자막으로 번역하세요."
    return user, images


_last_call = [0.0]


def _call_gemini(user, images):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("환경변수 GEMINI_API_KEY가 없습니다. SETUP.md의 API 키 단계를 확인하세요.")
    parts = [{"text": user}] + [{"inline_data": {"mime_type": "image/jpeg", "data": b}} for b in images]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.GEMINI_MODEL}:generateContent"
    r = requests.post(url, params={"key": key}, timeout=300, json={
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0},
    })
    _last_call[0] = time.time()
    if r.status_code == 429:
        raise RuntimeError("호출 한도 초과(429) — 잠시 후 재시도")
    r.raise_for_status()
    cands = r.json().get("candidates", [])
    if not cands or "content" not in cands[0]:
        raise RuntimeError(f"응답 없음: {r.text[:300]}")
    return "".join(p.get("text", "") for p in cands[0]["content"]["parts"]).strip()


def wait_rate_limit():
    """무료 티어 호출 간격 맞추기 (지연 시간 측정에서 제외되도록 호출 전에 따로 기다림)."""
    if config.LLM_BACKEND == "gemini":
        wait = config.GEMINI_MIN_INTERVAL_S - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)


def _call_ollama(user, images):
    msg = {"role": "user", "content": user}
    if images:
        msg["images"] = images
    r = requests.post(config.OLLAMA_URL, timeout=600, json={
        "model": config.OLLAMA_MODEL, "stream": False, "options": config.OLLAMA_OPTIONS,
        "messages": [{"role": "system", "content": SYSTEM}, msg],
    })
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def call_llm(user, images, retries=4):
    fn = _call_gemini if config.LLM_BACKEND == "gemini" else _call_ollama
    for i in range(retries):
        try:
            return fn(user, images)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            delay = 20 * (i + 1)
            print(f"  재시도 {i + 1}/{retries} ({delay}s 후): {e}")
            time.sleep(delay)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", nargs="+", default=config.CONDITIONS)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    asr = read_jsonl(ASR)
    ocr = read_jsonl(OCR)
    oracle = collections.defaultdict(list)
    for e in read_csv(config.ENTITIES_CSV):
        # spoken_form의 '|' 대체 표기는 프롬프트에서 ' / '로 보여 줌 (예: 아이지 / IG → IG)
        src = " / ".join(s.strip() for s in e["spoken_form"].split("|") if s.strip())
        # accepted 앞의 '='(대소문자 구분 표시)는 프롬프트에 보이지 않게 뗌
        oracle[e["seg_id"]].append((src, e["accepted"].split("|")[0].strip().lstrip("=").strip()))

    # 이미 번역된 (seg, cond) 조합은 건너뜀
    done = set()
    if OUT.exists() and not args.force:
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    o = json.loads(line)
                    done.add((o["seg_id"], o["cond"]))
    elif OUT.exists() and args.force:
        keep_lines = []
        with open(OUT, encoding="utf-8") as f:
            for line in f:
                if line.strip() and json.loads(line)["cond"] not in args.cond:
                    keep_lines.append(line)
        OUT.write_text("".join(keep_lines), encoding="utf-8")

    if config.LLM_BACKEND == "ollama":
        try:
            requests.get(config.OLLAMA_URL.replace("/api/chat", "/api/tags"), timeout=5)
        except Exception:
            raise SystemExit("Ollama 서버에 연결할 수 없습니다. Ollama 앱이 실행 중인지 확인하세요.")
    elif not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("환경변수 GEMINI_API_KEY가 없습니다. SETUP.md의 API 키 단계를 확인하세요.")
    print(f"번역 모델: {config.LLM_BACKEND} / {config.LLM_MODEL}")

    with open(OUT, "a", encoding="utf-8") as out:
        for seg in segments():
            sid = seg["seg_id"]
            if sid not in asr:
                print(f"[{sid}] ASR 결과 없음 (step2 먼저)")
                continue
            for cond in args.cond:
                if (sid, cond) in done:
                    continue
                frames = frame_paths(sid)
                if cond == "V" and not frames:
                    print(f"[{sid}] 프레임 없음, V 건너뜀")
                    continue
                if cond == "B" and sid not in ocr:
                    print(f"[{sid}] OCR 결과 없음, B 건너뜀")
                    continue
                user, images = build_prompt(cond, asr[sid]["asr"], ocr.get(sid, {}).get("ocr_terms", []),
                                            frames, oracle.get(sid, []))
                wait_rate_limit()
                t0 = time.time()
                text = call_llm(user, images)
                if text is None:
                    print(f"[{sid}][{cond}] 실패")
                    continue
                rec = {"seg_id": sid, "cond": cond, "translation": text,
                       "latency_s": round(time.time() - t0, 2), "model": config.LLM_MODEL}
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                print(f"[{sid}][{cond}] ({rec['latency_s']}s) {text[:80]}")


if __name__ == "__main__":
    main()
