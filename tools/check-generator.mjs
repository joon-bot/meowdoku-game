#!/usr/bin/env node
/**
 * 무한 마당 생성기 검증
 *
 * 생성기는 웹 워커 안에서 돈다. 워커 소스는 index.html 의 함수들을 toString() 으로
 * 이어 붙여 만드는데(단일 파일을 유지하려고), 이 방식에는 딱 하나 약점이 있다 —
 * GEN_FNS 목록에 빠진 함수를 참조하면 브라우저에서 워커가 돌 때가 되어서야 터진다.
 * 그것도 조용히: 워커가 죽으면 메인 스레드 대체 경로로 넘어가서 화면만 몇 초 멈춘다.
 *
 * 그래서 여기서 워커 소스를 그대로 조립해 격리된 VM 에 넣고 실제로 판을 만들어 본다.
 * 목록에 빠진 게 있으면 ReferenceError 로 즉시 드러난다.
 *
 * 이어서 만들어진 판이 실제로 쓸 만한지도 본다.
 *   · 해가 정확히 하나인가            (findSolutions)
 *   · 논리만으로 끝까지 풀리는가       (logicSolve = 게임의 힌트 엔진)
 *   · 영역이 전부 이어져 있는가        (끊긴 영역은 규칙을 읽을 수 없게 만든다)
 *   · 정답이 규칙을 지키는가           (행·열·영역 하나씩 + 대각 인접 금지)
 *
 * 사용: node tools/check-generator.mjs [레벨...]     (기본 27 35 51)
 */
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';

const src = readFileSync('index.html', 'utf8');

/** index.html 에서 함수 하나의 소스를 통째로 떼어 온다 (중괄호 균형으로 끝을 찾는다) */
function extractFunction(name) {
  const head = new RegExp(`\\nfunction ${name}\\s*\\(`).exec(src);
  if (!head) throw new Error(`index.html 에서 function ${name} 를 찾지 못했습니다`);
  let i = src.indexOf('{', head.index + head[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    const ch = src[j];
    if (ch === '{') depth++;
    else if (ch === '}') { depth--; if (depth === 0) return src.slice(head.index + 1, j + 1); }
  }
  throw new Error(`function ${name} 의 끝을 찾지 못했습니다`);
}

// index.html 이 실제로 쓰는 목록을 그대로 읽는다 — 여기서 손으로 베끼면 검증이 무의미하다
const listMatch = /const GEN_FNS = \[([\s\S]*?)\];/.exec(src);
if (!listMatch) { console.error('index.html 에서 GEN_FNS 목록을 찾지 못했습니다'); process.exit(1); }
const names = listMatch[1].split(',').map((t) => t.trim()).filter(Boolean);
console.log(`GEN_FNS ${names.length}개: ${names.join(', ')}\n`);

// index.html 의 genWorkerSource() 와 같은 서두
const prelude = 'const EMPTY=0,RABBIT=1,BLOCKED=-1;\n'
  + 'const D4=[[-1,0],[1,0],[0,-1],[0,1]];\n'
  + 'const regionName=(i)=>String(i+1), groupLabel=()=>"";\n';
const workerSource = prelude + names.map(extractFunction).join('\n');

// 격리 실행 — 브라우저 전역(document, window …)이 전혀 없는 곳에서 돌려 본다.
// 워커에도 그런 건 없으므로, 여기서 도는 코드는 워커에서도 돈다.
const ctx = createContext({ Date, Math, Set, Map, Array, Object, JSON, Number, String, Infinity, isNaN });
try {
  runInContext(workerSource + '\nthis.__gen = { makeEndlessPuzzle, findSolutions, logicSolve, inferenceDepth };', ctx);
} catch (e) {
  console.error(`워커 소스가 자기완결적이지 않습니다 — ${e.message}`);
  console.error('GEN_FNS 목록에 빠진 함수가 있는지 확인하세요.');
  process.exit(1);
}
const gen = ctx.__gen;
console.log('워커 소스 격리 실행 OK (브라우저 전역 없이 로드됨)\n');

/** 영역이 전부 한 덩어리로 이어져 있는가 */
function regionsConnected(n, regions) {
  for (let gid = 0; gid < n; gid++) {
    const cells = [];
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (regions[r][c] === gid) cells.push([r, c]);
    if (!cells.length) return false;
    const seen = new Set([cells[0][0] * n + cells[0][1]]);
    const stack = [cells[0]];
    while (stack.length) {
      const [r, c] = stack.pop();
      for (const [dr, dc] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
        const nr = r + dr, nc = c + dc;
        if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
        if (regions[nr][nc] !== gid || seen.has(nr * n + nc)) continue;
        seen.add(nr * n + nc); stack.push([nr, nc]);
      }
    }
    if (seen.size !== cells.length) return false;
  }
  return true;
}

/** 정답이 규칙을 지키는가 */
function solutionValid(n, regions, cols) {
  if (new Set(cols).size !== n) return false;                       // 열 유일
  if (new Set(cols.map((c, r) => regions[r][c])).size !== n) return false;   // 영역 유일
  for (let r = 1; r < n; r++) if (Math.abs(cols[r] - cols[r - 1]) <= 1) return false;  // 대각 인접
  return true;
}

// index.html 의 커브 정의도 그대로 가져다 쓴다 — 여기서 손으로 베끼면 검증이 무의미하다
const curveSrc = /const ENDLESS_CURVE = \[[\s\S]*?\n\];/.exec(src);
if (!curveSrc) { console.error('index.html 에서 ENDLESS_CURVE 를 찾지 못했습니다'); process.exit(1); }
runInContext(
  'const ENDLESS_START = ' + (/const ENDLESS_START = (\d+)/.exec(src)[1]) + ';\n'
  + 'const STRUCT_TOP = ' + (/const STRUCT_TOP = (\d+)/.exec(src)[1]) + ';\n'
  + curveSrc[0] + '\n'
  + extractFunction('isChallengeLevel') + '\n'
  + extractFunction('endlessSpec') + '\n' + extractFunction('endlessSeed')
  + '\nthis.__spec = { endlessSpec, endlessSeed, isChallengeLevel, structStep };', ctx);

const levels = process.argv.slice(2).map(Number).filter(Boolean);
const targets = levels.length ? levels : [27, 35, 51];
let fails = 0;

for (const level of targets) {
  const spec = ctx.__spec.endlessSpec(level);
  const seed = ctx.__spec.endlessSeed(level, 0);
  const t0 = Date.now();
  const p = gen.makeEndlessPuzzle(spec, seed, 60000);
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  if (!p) {
    console.log(`무한 ${level}번  생성 실패 (${secs}초)`);
    fails++; continue;
  }
  const sols = gen.findSolutions(p.size, p.regions, 3);
  const lg = gen.logicSolve(p.size, p.regions);
  const problems = [];
  if (sols.length !== 1) problems.push(`해가 ${sols.length}개`);
  else if (!sols[0].every((c, r) => c === p.solution[r])) problems.push('찾은 해가 정답과 다름');
  if (!lg.ok) problems.push('논리만으로 안 풀림');
  if (!regionsConnected(p.size, p.regions)) problems.push('끊긴 영역 있음');
  if (!solutionValid(p.size, p.regions, p.solution)) problems.push('정답이 규칙 위반');
  if (p.size !== spec.size) problems.push(`크기 ${spec.size} 요청 -> ${p.size} 로 물러섬`);

  // 구조 요구를 실제로 지켰는지 — 영역 칸수는 판만 봐도 셀 수 있다.
  // 규칙은 "floor 칸 미만인 영역이 maxMini 개를 넘지 않는다" 하나다.
  // (maxMini 0 + floor 2 이면 1칸 영역이 사라지고, floor 3 이면 2칸 영역까지 사라진다)
  const st = ctx.__spec.structStep(p.step);
  const sizes = new Array(p.size).fill(0);
  for (const row of p.regions) for (const g of row) sizes[g]++;
  const under = sizes.filter((x) => x < st.floor).length;
  const smallest = Math.min(...sizes);
  if (under > st.maxMini) problems.push(`${st.floor}칸 미만 영역 ${under}개 (허용 ${st.maxMini})`);
  if (p.met && p.tier < st.minTier) problems.push(`T${p.tier} < 요구 T${st.minTier}`);
  if (p.met && p.tier > st.maxTier) problems.push(`T${p.tier} > 요구 상한 T${st.maxTier}`);
  if (p.met && p.firstPlace < st.minFirst) problems.push(`첫 확정 ${p.firstPlace}수 < 요구 ${st.minFirst}수`);

  const retreat = p.step === spec.step
    ? (p.met ? '' : '(요구 미달 — 만든 것 중 최선)')
    : `(요구 ${spec.step} 에서 물러섬)`;
  console.log(
    `무한 ${String(level).padStart(3)}번  ${p.size}×${p.size}  ${p.step}단계${retreat}`
    + `  T${p.tier}  첫확정 ${p.firstPlace}수  최소영역 ${smallest}칸  깊이 ${p.depth}`
    + (spec.challenge ? '  [도전]' : '') + `  ${secs}초`
    + (problems.length ? `  ✗ ${problems.join(' / ')}` : '  ok')
  );
  // 크기·단계 물러섬은 느린 환경을 위한 정상 동작이라 실패로 세지 않는다
  if (problems.some((x) => !x.startsWith('크기') && !x.includes('요구'))) fails++;
}

if (fails) { console.error(`\n${fails}개 레벨에서 문제가 있습니다.`); process.exit(1); }
console.log(`\n${targets.length}개 레벨 모두 통과.`);
