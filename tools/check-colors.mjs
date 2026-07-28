#!/usr/bin/env node
/**
 * 영역 배색 검증
 *
 * index.html 안의 팔레트·배색 코드를 그대로 떼어 와서 puzzles.json 의 모든 레벨에
 * 실제로 돌려 보고, 판을 읽을 수 없게 만드는 세 가지를 잡는다.
 *
 *   1) 색 중복      — 서로 다른 두 영역이 같은 색. "이 영역에 토끼를 놨나?"를
 *                     판단할 수 없게 되므로 영역 수가 팔레트보다 적으면 0이어야 한다.
 *   2) 대각 동색    — 모서리만 스친 두 영역이 같은 색. 한 덩어리로 이어져 보인다.
 *   3) 인접 ΔE     — 변을 맞댄 영역 쌍의 색 거리(적록색약 시야 포함)가 SAFE_DE 미만.
 *
 * 사용: node tools/check-colors.mjs
 * 하나라도 걸리면 종료 코드 1.
 */
import { readFileSync, existsSync } from 'node:fs';

const src = readFileSync('index.html', 'utf8');
const from = src.indexOf('const PALETTE = [');
const to = src.indexOf('/** 현재 레벨에서 그 영역에 실제로');
if (from < 0 || to < 0) {
  console.error('index.html 에서 배색 코드를 찾지 못했습니다.');
  process.exit(1);
}
const code = src.slice(from, to) + '\nexport { PALETTE, assignRegionColors, labDist, SAFE_DE };';
const { PALETTE, assignRegionColors, labDist, SAFE_DE } =
  await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));

// 팔레트 자체 요약
let closest = [Infinity, ''];
for (let i = 0; i < PALETTE.length; i++)
  for (let j = i + 1; j < PALETTE.length; j++) {
    const d = labDist(i, j);
    if (d < closest[0]) closest = [d, `${PALETTE[i].name}~${PALETTE[j].name}`];
  }
console.log(`팔레트 ${PALETTE.length}색 · 가장 가까운 쌍 ${closest[1]} ΔE=${closest[0].toFixed(1)}`);
console.log('(팔레트 안에 가까운 쌍이 있는 건 괜찮다 — 배색이 그 둘을 이웃으로 두지만 않으면 된다)\n');

const data = JSON.parse(readFileSync('puzzles.json', 'utf8'));
// 보관해 둔 판(puzzles-retired.json)도 같이 본다 — 되돌릴 때 배색이 깨져 있으면 안 된다
const RETIRED = 'puzzles-retired.json';
const retired = existsSync(RETIRED) ? JSON.parse(readFileSync(RETIRED, 'utf8')).levels : [];
let fails = 0, worstAll = Infinity;

for (const lv of [...data.levels, ...retired]) {
  const n = lv.size, regions = lv.regions;
  const color = assignRegionColors(n, regions);
  const problems = [];

  const tally = {};
  for (const p of color) tally[p] = (tally[p] || 0) + 1;
  const dup = Object.entries(tally).filter(([, v]) => v > 1);
  if (dup.length && n <= PALETTE.length) {
    problems.push('색 중복 ' + dup.map(([p, v]) => `${PALETTE[p].name}×${v}`).join(','));
  }

  let worst = Infinity, weakest = '';
  const seen = new Set();
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const g = regions[r][c];
      const check = (h) => {
        if (h === g) return;
        const key = Math.min(g, h) * n + Math.max(g, h);
        if (seen.has(key)) return;
        seen.add(key);
        const d = labDist(color[g], color[h]);
        if (d < worst) { worst = d; weakest = `${PALETTE[color[g]].name}~${PALETTE[color[h]].name}`; }
        if (d < SAFE_DE) problems.push(`인접 ΔE ${d.toFixed(1)} (${PALETTE[color[g]].name}~${PALETTE[color[h]].name})`);
      };
      if (r + 1 < n) check(regions[r + 1][c]);
      if (c + 1 < n) check(regions[r][c + 1]);
    }
  }
  worstAll = Math.min(worstAll, worst);

  for (let r = 0; r + 1 < n; r++) {
    for (let c = 0; c < n; c++) {
      for (const dc of [-1, 1]) {
        if (c + dc < 0 || c + dc >= n) continue;
        const g = regions[r][c], h = regions[r + 1][c + dc];
        if (g === h || color[g] !== color[h]) continue;
        if (regions[r + 1][c] === g || regions[r + 1][c] === h) continue;   // 변으로도 닿아 있으면 위에서 본다
        if (regions[r][c + dc] === g || regions[r][c + dc] === h) continue;
        problems.push(`대각 동색 (${PALETTE[color[g]].name})`);
      }
    }
  }

  const uniq = [...new Set(problems)];
  if (uniq.length) fails++;
  console.log(
    `${lv.id} n=${String(n).padStart(2)} 최약 인접 ΔE=${worst.toFixed(1).padStart(5)} (${weakest})`.padEnd(52) +
    (uniq.length ? '  ✗ ' + uniq.join(' / ') : '  ok')
  );
}

console.log(`\n전체 최약 인접 ΔE=${worstAll.toFixed(1)} (기준 ${SAFE_DE})`);
if (fails) {
  console.error(`${fails}개 레벨에서 문제가 있습니다.`);
  process.exit(1);
}
console.log(`${data.levels.length}개 레벨 모두 통과.`
  + (retired.length ? ` (+ 보관 ${retired.length}개)` : ''));
