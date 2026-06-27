#!/usr/bin/env python3
"""Split a text file into overlapping chunks for parallel triple extraction.

Usage:
    python chunk_text.py <full.txt> <out_dir> [--고밀|--중밀|--저밀] [--target-lines N]

Density controls chunk size (smaller chunk -> each agent covers less text -> extracts
more exhaustively instead of summarizing -> higher per-page triple yield). It MUST be
paired with the matching extraction instruction the SKILL injects into each agent.

    --저밀 (low, DEFAULT)  ~1700 lines/chunk — 선별적: 인과·연쇄·핵심 피해/대응 백본만
    --중밀 (medium)        ~900  lines/chunk — 균형: 백본 + 문단별 주요 사실·수치·요인
    --고밀 (high)          ~450  lines/chunk — 망라: 근거 있는 트리플 빠짐없이(표는 행 단위)

English aliases --density low|medium|high also work. --target-lines overrides the profile.
Prints DENSITY=.. and CHUNKS=N so the caller knows how many agents to spawn and which
extraction instruction to use.
"""
import sys, os, argparse

PROFILE = {"고밀": 450, "high": 450, "중밀": 900, "medium": 900, "저밀": 1700, "low": 1700}
CANON = {"고밀": "고밀", "high": "고밀", "중밀": "중밀", "medium": "중밀", "저밀": "저밀", "low": "저밀"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out_dir")
    ap.add_argument("--density", choices=list(PROFILE.keys()), default=None)
    ap.add_argument("--고밀", dest="density", action="store_const", const="고밀")
    ap.add_argument("--중밀", dest="density", action="store_const", const="중밀")
    ap.add_argument("--저밀", dest="density", action="store_const", const="저밀")
    ap.add_argument("--target-lines", type=int, default=None, help="override the density profile")
    ap.add_argument("--overlap", type=int, default=40)
    ap.add_argument("--max-chunks", type=int, default=40)
    a = ap.parse_args()

    density = CANON.get(a.density, "저밀")           # unspecified -> 저밀 (low)
    target = a.target_lines or PROFILE[density]

    with open(a.src, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    n = len(lines)
    chunks = max(1, min(a.max_chunks, (n + target - 1) // target))
    size = n // chunks + 1
    os.makedirs(a.out_dir, exist_ok=True)
    for i in range(chunks):
        start = max(0, i * size - a.overlap)
        end = min(n, (i + 1) * size)
        with open(os.path.join(a.out_dir, f"chunk_{i:02d}.txt"), "w", encoding="utf-8") as g:
            g.write("".join(lines[start:end]))
    print(f"DENSITY={density} (~{target} lines/chunk)")
    print(f"CHUNKS={chunks}")
    for i in range(chunks):
        print(f"  chunk_{i:02d}.txt")


if __name__ == "__main__":
    main()
