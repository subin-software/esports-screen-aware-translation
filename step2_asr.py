"""2단계: Whisper로 각 구간 음성을 받아씁니다. -> work/asr.jsonl

힌트(initial_prompt)를 주지 않은 순수 음성인식 결과를 기준선으로 씁니다.
사용: python step2_asr.py [--force]
"""
import argparse

import torch
import whisper

import config
from common import segments, audio_path, read_jsonl, append_jsonl

OUT = config.WORK / "asr.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if args.force and OUT.exists():
        OUT.unlink()
    done = read_jsonl(OUT)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Whisper '{config.WHISPER_MODEL}' 로드 중 (device={device})")
    model = whisper.load_model(config.WHISPER_MODEL, device=device)

    for seg in segments():
        sid = seg["seg_id"]
        if sid in done:
            continue
        wav = audio_path(sid)
        if not wav.exists():
            print(f"[{sid}] 오디오 없음 (step1 먼저)")
            continue
        r = model.transcribe(str(wav), language=config.WHISPER_LANGUAGE,
                             fp16=(device == "cuda"), condition_on_previous_text=False)
        text = r["text"].strip()
        append_jsonl(OUT, {"seg_id": sid, "asr": text})
        print(f"[{sid}] {text}")


if __name__ == "__main__":
    main()
