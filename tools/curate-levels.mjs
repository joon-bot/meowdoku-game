#!/usr/bin/env node
/**
 * 퍼즐 풀 -> 실제 레벨 순서(puzzles.json)
 *
 * 레벨 커브 설계
 *   1. 첫 5레벨은 5x5 easy 중에서도 "가장 쉬운" 것들만 고른다.
 *      쉬움의 기준(ease):
 *        - 총 추론 수가 적을수록 쉽다 (막히는 구간이 없다)
 *        - 1칸 영역이 많을수록 쉽다 (공짜 시작점)
 *        - 첫 확정이 빠를수록 쉽다
 *        - 가장 큰 영역이 작을수록 쉽다 (한 영역이 보드를 뒤덮으면 눈이 피로하다)
 *   2. 그 뒤로는 크기 순으로 올라가되, 같은 크기 안에서는 쉬운 것부터 배치한다.
 *
 * 생성(느림)과 분리돼 있어서 커브만 바꿔 다시 돌리는 건 순식간이다.
 * 사용: node tools/curate-levels.mjs [풀경로] [출력경로]
 */
import { readFileSync, writeFileSync } from 'node:fs';

const POOL = process.argv[2] || 'puzzles-pool.json';
const OUT = process.argv[3] || 'puzzles.json';

const pool = JSON.parse(readFileSync(POOL, 'utf8'));
if (!Array.isArray(pool.puzzles) || !pool.puzzles.length) {
  console.error(`${POOL} 에 퍼즐이 없습니다.`);
  process.exit(1);
}

/**
 * 난이도는 오직 "추론 깊이"로 매긴다.
 * 영역 크기 분포(1칸 영역이 있는지, 거대 영역이 있는지)와는 완전히 분리돼 있어서,
 * 어려움 레벨에 1칸 영역이 나올 수도 있고 쉬움 레벨에 없을 수도 있다.
 */
const DIFF_BANDS = [
  { max: 6, name: 'easy' },
  { max: 13, name: 'normal' },
  { max: Infinity, name: 'hard' },
];
const difficultyOf = (depth) => DIFF_BANDS.find((b) => depth <= b.max).name;

/** 커브 정렬용 — 같은 크기 안에서 쉬운 것부터 놓는다 */
const hardness = (p) => p.metrics.depth + p.metrics.steps * 0.2;

const OPENING = 5;          // 첫 5레벨: 가장 쉬운 5x5
const PER_SIZE = {
  5: OPENING, 6: 3, 7: 3, 8: 3, 9: 3, 10: 3, 11: 2, 12: 2, 13: 2,
};

const bySize = new Map();
for (const p of pool.puzzles) {
  if (!bySize.has(p.size)) bySize.set(p.size, []);
  bySize.get(p.size).push(p);
}

/*
 * 커브: 판이 커질수록 "추론 깊이"도 함께 올라가야 한다.
 * 크기별로 쉬운 것부터 정렬해 두고, 뒤쪽 크기일수록 더 깊은 구간에서 뽑는다.
 * 다만 첫 5레벨(5x5)은 무조건 가장 쉬운 것들로 — 시작이 어려우면 안 된다.
 */
const sizes = [...bySize.keys()].sort((a, b) => a - b);
const levels = [];
sizes.forEach((size, si) => {
  const want = PER_SIZE[size] ?? 0;
  if (!want) return;
  const sorted = bySize.get(size).slice().sort((a, b) => hardness(a) - hardness(b));
  const room = Math.max(0, sorted.length - want);
  // 첫 크기는 가장 쉬운 쪽에서, 마지막 크기는 가장 어려운 쪽에서 뽑는다
  const frac = sizes.length > 1 ? si / (sizes.length - 1) : 0;
  const offset = size === 5 ? 0 : Math.round(room * frac);
  const picked = sorted.slice(offset, offset + want);
  if (picked.length < want) {
    console.error(`경고: ${size}x${size} 는 ${want}개가 필요한데 ${picked.length}개뿐입니다.`);
  }
  for (const p of picked) {
    levels.push({
      id: '', index: 0,
      size: p.size,
      difficulty: difficultyOf(p.metrics.depth),
      regions: p.regions,
      solution: p.solution,
      metrics: p.metrics,
    });
  }
});

levels.forEach((lv, i) => { lv.id = `L${String(i + 1).padStart(2, '0')}`; lv.index = i + 1; });

writeFileSync(OUT, JSON.stringify({
  version: 2,
  title: '토끼네 자리',
  rules: pool.rules,
  levels,
}) + '\n');

console.log(`\n레벨 커브 (${levels.length}개)`);
console.log('  #  크기   난이도   깊이  Tier  추론  거대영역  미니(1칸)');
levels.forEach((lv, i) => {
  const m = lv.metrics;
  console.log(
    `  ${String(i + 1).padStart(2)}  ${(lv.size + 'x' + lv.size).padEnd(6)} ${lv.difficulty.padEnd(7)}`
    + ` ${String(m.depth).padStart(4)}  T${m.tier}  ${String(m.steps).padStart(4)}`
    + `  ${String(Math.round(m.giantShare * 100) + '%').padStart(7)}  ${m.miniCount}개(${m.onesCount})`);
});
const tally = levels.reduce((a, l) => { a[l.difficulty] = (a[l.difficulty] || 0) + 1; return a; }, {});
console.log(`\n난이도 분포: ${JSON.stringify(tally)}`);
console.log(`-> ${OUT}`);
