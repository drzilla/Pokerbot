#!/usr/bin/env python3
"""Pre-parse Dave's CoinPoker hands locally."""
import sys, json, os
sys.path.insert(0, os.path.dirname(__file__))
from gem_parser import parse_one_hand

inpath = r'C:\Users\ron\Downloads\dave_coinpoker_converted.txt'
raw = open(inpath, encoding='utf-8').read()
chunks = [c.strip() for c in raw.split('\n\n') if c.strip().startswith('Poker Hand')]
print(f'Chunks: {len(chunks)}')

hands = []
errors = 0
seen = set()
for i, chunk in enumerate(chunks):
    try:
        h = parse_one_hand(chunk, f'dave_converted_{i}.txt')
        if h and h['id'] not in seen:
            seen.add(h['id'])
            hands.append(h)
    except Exception as e:
        errors += 1
        if errors <= 3:
            print(f'  Error {errors}: {e}')

print(f'Parsed: {len(hands)} hands, {errors} errors, {len(chunks) - len(hands) - errors} dupes')

dates = set(h.get('date', '') for h in hands)
players = set(h.get('hero', '') for h in hands[:100])
tourneys = set(h.get('tournament_id', '') or h.get('tournament', '') for h in hands)
print(f'Dates: {sorted(dates)[:5]}')
print(f'Hero names (sample): {players}')
print(f'Tournaments: {len(tourneys)}')

# Save
outpath = r'C:\Users\ron\Downloads\dave_hands_preparsed.json'
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(hands, f, default=str, ensure_ascii=False)
print(f'Saved: {outpath} ({os.path.getsize(outpath) / 1024 / 1024:.1f} MB)')
