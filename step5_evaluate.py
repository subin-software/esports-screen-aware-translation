"""5단계: 고유명사 정확도를 계산하고 결과 표·그래프를 만듭니다.

입력: data/entities.csv (정답), work/asr.jsonl, work/ocr.jsonl, work/translations.jsonl
출력: results/summary.md, results/entity_results.csv, results/review.csv, results/accuracy_by_case.png

review.csv의 error_type 칸을 채우고 다시 실행하면 오류 유형 집계가 summary.md에 추가됩니다.
사용: python step5_evaluate.py
"""
import collections
import json
import math
import random
import re

from rapidfuzz import fuzz

import config
from common import read_csv, read_jsonl, write_csv, norm

ASR = config.WORK / "asr.jsonl"
OCR = config.WORK / "ocr.jsonl"
TR = config.WORK / "translations.jsonl"
RES = config.RESULTS

CASE_LABELS = {
    "asr_ok": "① ASR이 맞게 인식",
    "asr_err_screen": "② ASR 오류 + 화면에 단서 있음",
    "asr_err_noscreen": "③ ASR 오류 + 화면에 단서 없음",
}
COND_LABELS = {"A": "A 음성만", "B": "B +OCR", "V": "V +이미지", "O": "O 정답목록(상한)"}


# ---------- 매칭 ----------
def strip_eq(form):
    """accepted 표기 앞의 대소문자 구분 표시 '='를 뗍니다."""
    return form.strip().lstrip("=").strip()


def contains_form(text, form):
    """번역문 안에 허용 표기가 있는지. 영문은 단어 경계, 한글은 공백 무시 부분일치.
    앞에 '='를 붙인 표기(예: =ON, =Career)는 일반 단어와 겹치지 않도록 대소문자까지 정확히 일치해야 인정."""
    form = form.strip()
    case_sensitive = form.startswith("=")
    form = strip_eq(form)
    if not form:
        return False
    if re.fullmatch(r"[\x00-\x7F]+", form):
        pat = r"(?<![A-Za-z0-9])" + re.escape(form) + r"(?![A-Za-z0-9])"
        return re.search(pat, text, flags=0 if case_sensitive else re.IGNORECASE) is not None
    return norm(form) in norm(text)


HANGUL = re.compile(r"[가-힣]")


def _tokens(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).split()


def fuzzy_in(form, text):
    """ASR/OCR 텍스트 안에 고유명사가 들어 있는지.
    영어: 고유명사와 같은 단어 수의 구간을 하나씩 비교해 가장 비슷한 구간의 유사도로 판단.
    한국어: 조사가 붙어 쓰이므로(페이커가) 공백을 무시한 부분 일치로 판단.
    짧은 이름(4글자 이하)은 정확히 일치할 때만 인정합니다."""
    if not form.strip() or not text.strip():
        return False
    if HANGUL.search(form):
        f, t = norm(form), norm(text)
        if len(f) <= 4:
            return f in t
        return fuzz.partial_ratio(f, t) >= config.FUZZY_THRESHOLD
    f, t = _tokens(form), _tokens(text)
    if not f or not t:
        return False
    target = " ".join(f)
    n = len(f)
    windows = [" ".join(t[i:i + n]) for i in range(max(1, len(t) - n + 1))]
    if len(target.replace(" ", "")) <= 4:
        return target in windows
    return max(fuzz.ratio(target, w) for w in windows) >= config.FUZZY_THRESHOLD


# ---------- 통계 ----------
def mcnemar_exact(b, c):
    """짝지은 비교. b: 기준 오답·비교 정답, c: 기준 정답·비교 오답. 양측 정확 이항검정 p값."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def bootstrap_ci(rows, cond, iters, seed=0):
    by_seg = collections.defaultdict(list)
    for r in rows:
        if r.get(f"correct_{cond}") != "":
            by_seg[r["seg_id"]].append(int(r[f"correct_{cond}"]))
    segs = list(by_seg)
    if not segs:
        return None, None
    rng = random.Random(seed)
    accs = []
    for _ in range(iters):
        pick = [by_seg[rng.choice(segs)] for _ in segs]
        tot = sum(len(p) for p in pick)
        accs.append(sum(sum(p) for p in pick) / tot if tot else 0)
    accs.sort()
    return accs[int(0.025 * iters)], accs[int(0.975 * iters) - 1]


def pct(x):
    return "-" if x is None else f"{x * 100:.1f}%"


def acc(rows, cond):
    vals = [int(r[f"correct_{cond}"]) for r in rows if r.get(f"correct_{cond}") != ""]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def md_table(header, body):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(out)


# ---------- 메인 ----------
def main():
    RES.mkdir(parents=True, exist_ok=True)
    segs = {s["seg_id"]: s for s in read_csv(config.SEGMENTS_CSV)}
    ents = read_csv(config.ENTITIES_CSV)
    asr = read_jsonl(ASR)
    ocr = read_jsonl(OCR)

    tr = collections.defaultdict(dict)   # seg -> cond -> {translation, latency}
    if TR.exists():
        with open(TR, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    o = json.loads(line)
                    tr[o["seg_id"]][o["cond"]] = o
    conds = [c for c in config.CONDITIONS if any(c in v for v in tr.values())]
    if not conds:
        raise SystemExit("번역 결과가 없습니다. step4를 먼저 실행하세요.")

    # 엔티티별 판정
    rows = []
    for e in ents:
        sid = e["seg_id"]
        if sid not in asr:
            continue
        accepted = [a.strip() for a in e["accepted"].split("|") if a.strip()]
        # spoken_form도 '|'로 여러 표기 허용 (예: 아이지|IG). 하나라도 ASR에 있으면 맞게 들은 것
        spoken = [s.strip() for s in e["spoken_form"].split("|") if s.strip()]
        asr_text = asr[sid]["asr"]
        ocr_terms = ocr.get(sid, {}).get("ocr_terms", [])
        asr_ok = any(fuzzy_in(s, asr_text) for s in spoken)
        on_screen = e.get("on_screen", "").upper().startswith("Y")
        # 화면에는 해설 언어 표기나 정답 표기(예: 한국어 중계 화면의 영어 ID) 어느 쪽으로든 나올 수 있음
        ocr_has = any(fuzzy_in(form, t) for form in spoken + [strip_eq(a) for a in accepted] for t in ocr_terms)
        case = "asr_ok" if asr_ok else ("asr_err_screen" if on_screen else "asr_err_noscreen")
        row = {
            "seg_id": sid, "screen_type": segs.get(sid, {}).get("screen_type", ""),
            "entity_type": e["entity_type"], "spoken_form": e["spoken_form"],
            "accepted": "|".join(accepted), "on_screen": "Y" if on_screen else "N",
            "asr_ok": int(asr_ok), "ocr_has": int(ocr_has), "case": case,
        }
        for c in config.CONDITIONS:
            t = tr[sid].get(c)
            row[f"correct_{c}"] = "" if t is None else int(any(contains_form(t["translation"], a) for a in accepted))
        rows.append(row)

    fields = (["seg_id", "screen_type", "entity_type", "spoken_form", "accepted", "on_screen",
               "asr_ok", "ocr_has", "case"] + [f"correct_{c}" for c in config.CONDITIONS])
    write_csv(RES / "entity_results.csv", rows, fields)

    # ----- review.csv (사람이 오류 유형을 붙이는 파일, 기존 라벨 유지) -----
    # 키에 accepted도 넣음: 같은 spoken_form이 두 엔티티를 가리킬 때(예: 칼나타 → Kalista, Renata Glasc) 라벨이 섞이지 않게
    old = {(r["seg_id"], r["spoken_form"], r["accepted"], r["cond"]): r for r in
           (read_csv(RES / "review.csv") if (RES / "review.csv").exists() else [])}
    review = []
    for r in rows:
        for c in conds:
            if r[f"correct_{c}"] == 0:
                key = (r["seg_id"], r["spoken_form"], r["accepted"], c)
                prev = old.get(key, {})
                review.append({
                    "seg_id": r["seg_id"], "cond": c, "spoken_form": r["spoken_form"],
                    "accepted": r["accepted"], "case": CASE_LABELS[r["case"]],
                    "asr": asr[r["seg_id"]]["asr"],
                    "ocr_terms": ", ".join(ocr.get(r["seg_id"], {}).get("ocr_terms", [])[:15]),
                    "translation": tr[r["seg_id"]][c]["translation"],
                    "error_type": prev.get("error_type", ""), "note": prev.get("note", ""),
                })
    write_csv(RES / "review.csv", review,
              ["seg_id", "cond", "spoken_form", "accepted", "case", "asr", "ocr_terms",
               "translation", "error_type", "note"])

    # ----- summary.md -----
    L = ["# 결과 요약", "",
         f"- 구간 {len({r['seg_id'] for r in rows})}개, 고유명사 {len(rows)}개, 번역 모델 `{config.LLM_MODEL}`",
         f"- 정확도 = 정답 고유명사가 번역문에 허용 표기로 들어간 비율. 95% 신뢰구간은 구간 단위 부트스트랩({config.BOOTSTRAP_ITERS}회)", ""]

    # 1) 전체
    body = []
    for c in conds:
        a, n = acc(rows, c)
        lo, hi = bootstrap_ci(rows, c, config.BOOTSTRAP_ITERS)
        lat = [tr[s][c]["latency_s"] for s in tr if c in tr[s]]
        body.append([COND_LABELS[c], pct(a), f"{pct(lo)} ~ {pct(hi)}", n,
                     f"{sum(lat) / len(lat):.1f}s" if lat else "-"])
    L += ["## 1. 조건별 고유명사 정확도", "",
          md_table(["조건", "정확도", "95% CI", "N", "평균 지연"], body), ""]

    # 2) 케이스별
    body = []
    for k, label in CASE_LABELS.items():
        sub = [r for r in rows if r["case"] == k]
        body.append([label, len(sub)] + [pct(acc(sub, c)[0]) for c in conds])
    L += ["## 2. 케이스별 정확도 (화면 정보가 효과를 내야 하는 곳은 ②)", "",
          md_table(["케이스", "N"] + [COND_LABELS[c] for c in conds], body), ""]

    # 3) 짝지은 비교
    body = []
    pairs = [("A", "B"), ("A", "V"), ("B", "V"), ("A", "O")]
    for base, comp in pairs:
        if base in conds and comp in conds:
            both = [r for r in rows if r[f"correct_{base}"] != "" and r[f"correct_{comp}"] != ""]
            b = sum(1 for r in both if r[f"correct_{base}"] == 0 and r[f"correct_{comp}"] == 1)
            c_ = sum(1 for r in both if r[f"correct_{base}"] == 1 and r[f"correct_{comp}"] == 0)
            body.append([f"{base} → {comp}", b, c_, f"{mcnemar_exact(b, c_):.3f}"])
    L += ["## 3. 짝지은 비교 (McNemar 정확검정)", "",
          "같은 고유명사에 대해 조건만 바꿨을 때, 고쳐진 수와 새로 틀린 수입니다.", "",
          md_table(["비교", "고쳐짐(오답→정답)", "망가짐(정답→오답)", "p값"], body), ""]

    # 4) 유형·화면 구성별
    for key, title in [("entity_type", "4. 고유명사 유형별"), ("screen_type", "5. 화면 구성별")]:
        groups = sorted({r[key] for r in rows})
        body = []
        for g in groups:
            sub = [r for r in rows if r[key] == g]
            body.append([g or "(미기입)", len(sub)] + [pct(acc(sub, c)[0]) for c in conds])
        L += [f"## {title} 정확도", "", md_table([key, "N"] + [COND_LABELS[c] for c in conds], body), ""]

    # 6) OCR 재현율
    scr = [r for r in rows if r["on_screen"] == "Y"]
    rec = sum(r["ocr_has"] for r in scr) / len(scr) if scr else None
    L += ["## 6. OCR 재현율", "",
          f"화면에 보이는 고유명사 {len(scr)}개 중 OCR이 읽어낸 비율: **{pct(rec)}**", ""]

    # 7) 오류 유형
    labeled = [r for r in review if r["error_type"]]
    if labeled:
        cnt = collections.Counter((r["cond"], r["error_type"]) for r in labeled)
        types = sorted({t for _, t in cnt})
        body = [[t] + [cnt.get((c, t), 0) for c in conds] for t in types]
        L += ["## 7. 오류 유형 (review.csv 수동 라벨)", "",
              md_table(["오류 유형"] + [COND_LABELS[c] for c in conds], body), ""]
    else:
        L += ["## 7. 오류 유형", "", "review.csv의 error_type 칸을 채운 뒤 다시 실행하면 집계됩니다.", ""]

    (RES / "summary.md").write_text("\n".join(L), encoding="utf-8")

    # ----- 그래프 -----
    try:
        import logging
        import matplotlib
        matplotlib.use("Agg")
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
        import matplotlib.pyplot as plt
        plt.rcParams["font.family"] = ["Malgun Gothic", "AppleGothic", "NanumGothic", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        groups = [("전체", rows)] + [(CASE_LABELS[k], [r for r in rows if r["case"] == k]) for k in CASE_LABELS]
        fig, ax = plt.subplots(figsize=(10, 4.8))
        w = 0.8 / len(conds)
        colors = {"A": "#9aa5b1", "B": "#2f6fdb", "V": "#e07b39", "O": "#3c9d5d"}
        for i, c in enumerate(conds):
            ys = [(acc(sub, c)[0] or 0) * 100 for _, sub in groups]
            xs = [g + (i - (len(conds) - 1) / 2) * w for g in range(len(groups))]
            bars = ax.bar(xs, ys, w, label=COND_LABELS[c], color=colors.get(c))
            for x, y in zip(xs, ys):
                ax.text(x, y + 1, f"{y:.0f}", ha="center", fontsize=8)
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels([f"{g}\n(N={len(s)})" for g, s in groups], fontsize=9)
        ax.set_ylabel("고유명사 정확도 (%)")
        ax.set_ylim(0, 110)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, ncol=len(conds), loc="upper center", bbox_to_anchor=(0.5, 1.12))
        fig.tight_layout()
        fig.savefig(RES / "accuracy_by_case.png", dpi=160)
    except Exception as e:  # noqa: BLE001
        print("그래프 생성 실패:", e)

    print((RES / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
