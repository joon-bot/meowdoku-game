#!/usr/bin/env node
/**
 * puzzles.json 검증 + index.html 내장 사본 갱신
 *
 * 1) 모든 레벨을 다시 검사한다 (해가 정말 유일한지, 정답이 규칙을 지키는지)
 * 2) puzzles.json 을 index.html 의 <script id="puzzles-embedded"> 안에 넣는다.
 *    -> 로컬 파일(file://)로 열어도 fetch 없이 바로 플레이 가능
 *
 * 사용: node tools/build.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';

const data = JSON.parse(readFileSync('puzzles.json', 'utf8'));

function findSolutions(n, regions, limit = 2) {
  const colUsed = new Array(n).fill(false);
  const regUsed = new Array(n).fill(false);
  const cols = new Array(n).fill(-1);
  const found = [];
  (function rec(r) {
    if (found.length >= limit) return;
    if (r === n) { found.push(cols.slice()); return; }
    for (let c = 0; c < n; c++) {
      if (colUsed[c]) continue;
      const g = regions[r][c];
      if (regUsed[g]) continue;
      if (r > 0 && Math.abs(cols[r - 1] - c) <= 1) continue;
      colUsed[c] = true; regUsed[g] = true; cols[r] = c;
      rec(r + 1);
      colUsed[c] = false; regUsed[g] = false; cols[r] = -1;
      if (found.length >= limit) return;
    }
  })(0);
  return found;
}

function regionsConnected(n, regions) {
  const seen = new Set();
  for (let gid = 0; gid < n; gid++) {
    const cells = [];
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (regions[r][c] === gid) cells.push([r, c]);
    if (!cells.length) return `영역 ${gid} 이(가) 비어 있음`;
    const q = [cells[0]]; const vis = new Set([cells[0][0] * n + cells[0][1]]);
    while (q.length) {
      const [r, c] = q.pop();
      for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const nr = r + dr, nc = c + dc;
        if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
        if (regions[nr][nc] !== gid) continue;
        const k = nr * n + nc;
        if (vis.has(k)) continue;
        vis.add(k); q.push([nr, nc]);
      }
    }
    if (vis.size !== cells.length) return `영역 ${gid} 이(가) 끊어져 있음`;
    seen.add(gid);
  }
  return null;
}

let bad = 0;
for (const lv of data.levels) {
  const n = lv.size;
  const problems = [];
  if (lv.regions.length !== n || lv.regions.some((row) => row.length !== n)) problems.push('영역 격자 크기 불일치');
  const conn = regionsConnected(n, lv.regions);
  if (conn) problems.push(conn);

  // 정답 자체 검증
  const s = lv.solution;
  if (new Set(s).size !== n) problems.push('정답의 열이 중복');
  if (new Set(s.map((c, r) => lv.regions[r][c])).size !== n) problems.push('정답이 한 영역에 두 마리');
  for (let r = 1; r < n; r++) if (Math.abs(s[r] - s[r - 1]) <= 1) problems.push('정답에 인접한 토끼');

  const sols = findSolutions(n, lv.regions, 3);
  if (sols.length !== 1) problems.push(`해가 ${sols.length}개 (유일하지 않음)`);
  else if (sols[0].join() !== s.join()) problems.push('저장된 정답과 실제 해가 다름');

  if (problems.length) { bad++; console.error(`✗ ${lv.id} (${n}x${n}): ${problems.join(', ')}`); }
}

if (bad) { console.error(`\n검증 실패: ${bad}개 레벨에 문제가 있습니다.`); process.exit(1); }
console.log(`✓ ${data.levels.length}개 레벨 검증 통과`);

// index.html 에 내장
const html = readFileSync('index.html', 'utf8');
const OPEN = '<script id="puzzles-embedded" type="application/json">';
const CLOSE = '</' + 'script>';
const start = html.indexOf(OPEN);
if (start < 0) { console.error('index.html 에서 puzzles-embedded 태그를 찾지 못했습니다.'); process.exit(1); }
const from = start + OPEN.length;
const end = html.indexOf(CLOSE, from);
// JSON 안의 </script> 는 나올 수 없지만 방어적으로 이스케이프
const json = JSON.stringify(data).replace(/</g, '\\u003c');
const out = html.slice(0, from) + json + html.slice(end);
writeFileSync('index.html', out);
console.log(`✓ index.html 내장 사본 갱신 (${(json.length / 1024).toFixed(1)} KB)`);
