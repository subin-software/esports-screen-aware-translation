import csv
import json
import re
from pathlib import Path

import config


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [
            {k.strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(f)
            if any((v or "").strip() for v in row.values())
        ]


def write_csv(path, rows, fieldnames):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                out[obj["seg_id"]] = obj
    return out


def append_jsonl(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def to_seconds(t):
    """'1:02:03', '12:30', '750', '750.5' -> float 초"""
    t = t.strip()
    if ":" not in t:
        return float(t)
    sec = 0.0
    for part in t.split(":"):
        sec = sec * 60 + float(part)
    return sec


def segments():
    return read_csv(config.SEGMENTS_CSV)


def frame_paths(seg_id):
    d = config.WORK / "frames" / seg_id
    return sorted(d.glob("*.jpg")) if d.exists() else []


def audio_path(seg_id):
    return config.WORK / "audio" / f"{seg_id}.wav"


def norm(s):
    return re.sub(r"\s+", "", s).lower()
