"""1단계: segments.csv의 각 구간을 내려받아 오디오(16kHz wav)와 프레임(jpg)을 추출합니다.

필요: yt-dlp(pip), ffmpeg(PATH)
사용: python step1_clips.py            # 아직 처리 안 된 구간만
      python step1_clips.py --force    # 전부 다시
"""
import argparse
import re
import shutil
import subprocess
import sys

import requests

import config
from common import segments, to_seconds, audio_path


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("  [실패]", " ".join(str(c) for c in cmd[:3]), "...")
        print(r.stderr[-800:])
        return False
    return True


def fmt(sec):
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


CHZZK_VIDEO = re.compile(r"chzzk\.naver\.com/video/(\d+)")


def chzzk_direct_url(url):
    """치지직 VOD의 오디오 포함 mp4(progressive) 직접 주소를 찾습니다.
    2026-11 기준 치지직 재생 API가 매니페스트를 JSON으로 돌려줘서 yt-dlp 추출기가 실패하므로 우회합니다.
    찾지 못하면 None (그때는 yt-dlp로 시도)."""
    m = CHZZK_VIDEO.search(url)
    if not m:
        return None
    try:
        h = {"User-Agent": "Mozilla/5.0"}
        meta = requests.get(f"https://api.chzzk.naver.com/service/v3/videos/{m.group(1)}",
                            headers=h, timeout=30).json()["content"]
        pb = requests.get(f"https://apis.naver.com/neonplayer/vodplay/v1/playback/{meta['videoId']}",
                          params={"key": meta["inKey"], "env": "real", "lc": "en_US", "cpl": "en_US"},
                          headers=h, timeout=30).json()
        best = None
        for period in pb.get("period", []):
            for aset in period.get("adaptationSet", []):
                if aset.get("mimeType") != "video/mp4":
                    continue
                for rep in aset.get("representation", []):
                    height = rep.get("height") or 0
                    base = next((b.get("value") for b in rep.get("baseURL", []) if b.get("value")), None)
                    if base and height <= config.VIDEO_MAX_HEIGHT and (best is None or height > best[0]):
                        best = (height, base)
        return best[1] if best else None
    except Exception as ex:  # 네트워크·형식 변경 시 yt-dlp로 넘어감
        print(f"  [치지직 직접 주소 실패] {ex}")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg를 찾을 수 없습니다. SETUP.md의 설치 단계를 확인하세요.")

    clips = config.WORK / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    (config.WORK / "audio").mkdir(parents=True, exist_ok=True)

    for seg in segments():
        sid = seg["seg_id"]
        start, end = to_seconds(seg["start"]), to_seconds(seg["end"])
        dur = end - start
        if dur <= 0:
            print(f"[{sid}] end가 start보다 앞섭니다. 건너뜀")
            continue

        frames_dir = config.WORK / "frames" / sid
        if not args.force and audio_path(sid).exists() and frames_dir.exists() and any(frames_dir.glob("*.jpg")):
            print(f"[{sid}] 이미 처리됨")
            continue
        print(f"[{sid}] {seg['url']} {fmt(start)} ~ {fmt(end)}")

        clip = clips / f"{sid}.mp4"
        if args.force or not clip.exists():
            for old in clips.glob(f"{sid}.*"):
                old.unlink()
            direct = chzzk_direct_url(seg["url"])
            if direct:
                # mp4를 HTTP로 바로 열어 필요한 구간만 받음 (재인코딩해서 구간 경계를 정확히 맞춤)
                ok = run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", direct,
                          "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                          "-c:a", "aac", "-b:a", "128k", str(clip)])
            else:
                ok = run([
                    sys.executable, "-m", "yt_dlp",
                    "-f", f"bv*[height<={config.VIDEO_MAX_HEIGHT}]+ba/b[height<={config.VIDEO_MAX_HEIGHT}]",
                    "--download-sections", f"*{fmt(start)}-{fmt(end)}",
                    "--force-keyframes-at-cuts",
                    "--merge-output-format", "mp4",
                    "-o", str(clips / f"{sid}.%(ext)s"),
                    seg["url"],
                ])
            if not ok or not clip.exists():
                continue

        # 오디오: 16kHz mono wav
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
             "-ac", "1", "-ar", "16000", str(audio_path(sid))])

        # 프레임
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        frames_dir.mkdir(parents=True)
        for i, pos in enumerate(config.FRAME_POSITIONS):
            t = max(0.0, min(dur - 0.05, dur * pos))
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(clip),
                 "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "2",
                 str(frames_dir / f"f{i}_{int(pos * 100):02d}.jpg")])
        print(f"  -> 오디오 1개, 프레임 {len(list(frames_dir.glob('*.jpg')))}개")


if __name__ == "__main__":
    main()
