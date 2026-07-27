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

/** 낮을수록 쉽다. 같은 크기끼리 비교하는 용도라 크기는 넣지 않는다. */
function hardness(p) {
  const m = p.metrics;
  const cells = p.size * p.size;
  return m.steps                              // 추론이 많을수록 어렵다
    + m.firstPlace * 2                        // 시작을 못 찾으면 훨씬 어렵게 느껴진다
    - m.onesCount * 3                         // 공짜 시작점은 크게 쉬워진다
    + (m.maxRegion / cells) * 10;             // 거대한 영역 하나 = 읽기 피로
}

const OPENING = 5;          // 첫 5레벨: 가장 쉬운 5x5
const PER_SIZE = {          // 크기별로 실제 사용할 개수
  5: OPENING, 6: 3, 7: 3, 8: 3, 9: 3, 10: 3, 11: 2, 12: 2, 13: 2, 14: 2,
};

const bySize = new Map();
for (const p of pool.puzzles) {
  if (!bySize.has(p.size)) bySize.set(p.size, []);
  bySize.get(p.size).push(p);
}

const levels = [];
const report = [];
for (const size of [...bySize.keys()].sort((a, b) => a - b)) {
  const want = PER_SIZE[size] ?? 0;
  if (!want) continue;
  const sorted = bySize.get(size).slice().sort((a, b) => hardness(a) - hardness(b));
  const picked = sorted.slice(0, want);
  if (picked.length < want) {
    console.error(`경고: ${size}x${size} 는 ${want}개가 필요한데 ${picked.length}개뿐입니다.`);
  }
  for (const p of picked) {
    levels.push({
      id: '', index: 0,
      size: p.size,
      difficulty: p.difficulty,
      regions: p.regions,
      solution: p.solution,
      metrics: p.metrics,
    });
    report.push({ size, ...p.metrics, hardness: +hardness(p).toFixed(1), used: true });
  }
  const dropped = sorted.length - picked.length;
  if (dropped > 0) console.error(`   ${size}x${size}: ${picked.length}개 채택, ${dropped}개 보류(더 어려운 쪽)`);
}

levels.forEach((lv, i) => { lv.id = `L${String(i + 1).padStart(2, '0')}`; lv.index = i + 1; });

writeFileSync(OUT, JSON.stringify({
  version: 2,
  title: '토끼네 자리',
  rules: pool.rules,
  levels,
}) + '\n');

console.log(`\n레벨 커브 (${levels.length}개)`);
console.log('  #  크기   난이도   추론  첫확정  1칸  영역크기     체감난이도');
levels.forEach((lv, i) => {
  const m = lv.metrics;
  console.log(
    `  ${String(i + 1).padStart(2)}  ${lv.size}x${lv.size}`.padEnd(12)
    + ` ${lv.difficulty.padEnd(7)} ${String(m.steps).padStart(4)} ${String(m.firstPlace).padStart(6)}`
    + ` ${String(m.onesCount).padStart(4)}  ${String(m.minRegion + '~' + m.maxRegion).padEnd(10)} ${report[i].hardness}`);
});
console.log(`\n-> ${OUT}`);
