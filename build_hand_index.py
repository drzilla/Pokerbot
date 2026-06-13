#!/usr/bin/env python3
"""
build_hand_index.py — v7.31 (2026-05-05)

Indexes raw HH source files for fast hand_id → raw HH lookup.
Used by gem_squares_gtow.py to extract per-square HH files for GTOW import.

Output JSON: {hand_id: [file_path, byte_start, byte_end]}

USAGE:
  python3 build_hand_index.py <hh_dir> --output hand_index.json

Re-run whenever the HH directory contents change. Index build is fast
(~1s for 50K hands) and safe to regenerate.
"""
import argparse
import glob
import json
import os
import re
import sys
import time


HAND_BOUNDARY = re.compile(r'^Poker Hand #(TM\d+):', re.MULTILINE)


def build_index(hh_dir):
    """Walk all .txt files in hh_dir and index each hand by ID."""
    index = {}
    paths = sorted(glob.glob(os.path.join(hh_dir, '*.txt')))
    sys.stderr.write(f"[build_hand_index] scanning {len(paths)} files in {hh_dir}\n")
    for path in paths:
        with open(path, 'r') as f:
            content = f.read()
        positions = [m.start() for m in HAND_BOUNDARY.finditer(content)]
        positions.append(len(content))
        for i in range(len(positions) - 1):
            chunk_start = positions[i]
            chunk_end = positions[i + 1]
            m = HAND_BOUNDARY.match(content[chunk_start:chunk_start + 60])
            if m:
                index[m.group(1)] = [path, chunk_start, chunk_end]
    return index


def main():
    ap = argparse.ArgumentParser(description="GEM v7.31 hand_id index builder")
    ap.add_argument("hh_dir", help="Directory containing raw HH .txt files")
    ap.add_argument("--output", default="hand_index.json", help="Index output path")
    args = ap.parse_args()

    if not os.path.isdir(args.hh_dir):
        sys.stderr.write(f"[build_hand_index] ERROR: not a directory: {args.hh_dir}\n")
        sys.exit(1)

    t0 = time.time()
    index = build_index(args.hh_dir)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(index, f)
    sys.stderr.write(f"[build_hand_index] indexed {len(index):,} hands in {time.time()-t0:.1f}s → {args.output}\n")


if __name__ == "__main__":
    main()
