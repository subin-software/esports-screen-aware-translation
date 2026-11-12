"""3단계: EasyOCR로 각 구간 프레임의 화면 텍스트를 읽습니다. -> work/ocr.jsonl

여러 프레임의 결과를 합치고, 신뢰도 낮은 것·숫자만 있는 것(골드, 시간 등)은 버립니다.
사용: python step3_ocr.py [--force]
"""
import argparse
import re

import easyocr
import torch

import config
from common import segments, frame_paths, read_jsonl, append_jsonl

OUT = config.WORK / "ocr.jsonl"


def keep(text, conf):
    t = text.strip()
    if conf < config.OCR_MIN_CONF or len(t) < config.OCR_MIN_LEN:
        return False
    if not re.search(r"[A-Za-z가-힣]", t):     # 숫자·기호만 있는 텍스트(골드, 킬 수, 시간) 제외
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.force and OUT.exists():
        OUT.unlink()
    done = read_jsonl(OUT)

    reader = easyocr.Reader(config.OCR_LANGS, gpu=torch.cuda.is_available())

    for seg in segments():
        sid = seg["seg_id"]
        if sid in done:
            continue
        frames = frame_paths(sid)
        if not frames:
            print(f"[{sid}] 프레임 없음 (step1 먼저)")
            continue

        best = {}   # 소문자 키 -> (원문, 최고 신뢰도)
        for fp in frames:
            for _box, text, conf in reader.readtext(str(fp)):
                if keep(text, conf):
                    k = text.strip().lower()
                    if k not in best or conf > best[k][1]:
                        best[k] = (text.strip(), float(conf))
        terms = sorted(best.values(), key=lambda x: -x[1])[: config.OCR_MAX_TERMS]
        append_jsonl(OUT, {"seg_id": sid,
                           "ocr_terms": [t for t, _ in terms],
                           "ocr_conf": [round(c, 3) for _, c in terms]})
        print(f"[{sid}] {len(terms)}개: {', '.join(t for t, _ in terms[:12])}")


if __name__ == "__main__":
    main()
