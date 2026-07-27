#!/usr/bin/env node
/**
 * "토끼네 자리" 퍼즐 생성기 — 난이도별 영역 크기 프로필을 강제한다.
 *
 * 규칙(Queens / Star-Battle 계열):
 *   - N x N 보드, N개의 색 영역
 *   - 각 행 / 각 열 / 각 영역에 토끼가 정확히 한 마리
 *   - 토끼끼리 상하좌우 + 대각선으로 인접 불가
 *
 * 난이도의 정의는 "보드 크기"가 아니라 "영역 크기 분포"다:
 *   easy   1칸 영역 1~2개 + 2~3칸 영역 1~2개  -> 즉시 확정되는 시작점이 있다
 *   normal 모든 영역 2칸 이상                  -> 공짜 시작점이 없다
 *   hard   모든 영역 3칸 이상                  -> 작은 영역이 아예 없다
 *
 * 여기에 더해 easy 는 "첫 확정까지 걸리는 추론 수"(firstPlace)를 0~1로 강제한다.
 * 1칸 영역이 있으면 T0 가 즉시 발화하므로 보통 0이 된다.
 *
 * 출력은 "풀(pool)"이다. 실제 레벨 순서는 tools/curate-levels.mjs 가 정한다.
 * 사용: node tools/generate-puzzles.mjs [출력경로]   (기본 puzzles-pool.json)
 */

import { writeFileSync, readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// 이 파일은 스크립트이자 모듈이다. 다른 도구가 솔버만 가져다 쓸 수 있도록
// 아래 생성 루틴은 직접 실행했을 때만 돈다.
const IS_MAIN = import.meta.url === pathToFileURL(process.argv[1] || '').href;

// ---------------------------------------------------------------- RNG (재현 가능)
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffle(arr, rnd) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// ---------------------------------------------------------------- 1) 해답 배치
function randomSolution(n, rnd) {
  // cols[r] = r행에 놓인 토끼의 열. 행/열 유일 + 인접 행끼리 열 차이 >= 2
  const cols = new Array(n).fill(-1);
  const used = new Array(n).fill(false);
  function rec(r) {
    if (r === n) return true;
    for (const c of shuffle([...Array(n).keys()], rnd)) {
      if (used[c]) continue;
      if (r > 0 && Math.abs(cols[r - 1] - c) <= 1) continue;
      used[c] = true; cols[r] = c;
      if (rec(r + 1)) return true;
      used[c] = false; cols[r] = -1;
    }
    return false;
  }
  return rec(0) ? cols : null;
}

// ---------------------------------------------------------------- 난이도 프로필
export function difficultyOf(n) {
  if (n <= 7) return 'easy';
  if (n <= 10) return 'normal';
  return 'hard';
}

/**
 * 영역별 [min, max] 목표. 이 프로필이 생성 내내 불변식으로 지켜진다.
 * easy 의 1칸/2~3칸 영역은 여기서 자리를 배정받고, 이후 절대 크기가 바뀌지 않는다.
 */
function makeProfile(n, difficulty, maxFactor, rnd) {
  const profile = new Array(n);
  if (difficulty !== 'easy') {
    const min = difficulty === 'normal' ? 2 : 3;
    const cap = Math.max(8, Math.ceil(maxFactor * n));
    for (let i = 0; i < n; i++) profile[i] = { min, max: cap };
    return profile;
  }

  // easy: 1칸 영역 1~2개, 2~3칸 영역 1~2개, 나머지는 넉넉하게
  const order = shuffle([...Array(n).keys()], rnd);
  const tiny = 1 + Math.floor(rnd() * 2);                       // 1 또는 2
  const small = n <= 5 ? 1 : 1 + Math.floor(rnd() * 2);         // 5x5 는 자리가 좁아 1개
  const restCount = n - tiny - small;
  if (restCount < 2) return null;                               // 나머지 영역이 너무 적음

  const consumed = tiny * 1 + small * 2;
  const restMax = Math.ceil(((n * n - consumed) / restCount) * 1.8);

  order.slice(0, tiny).forEach((i) => { profile[i] = { min: 1, max: 1 }; });
  order.slice(tiny, tiny + small).forEach((i) => { profile[i] = { min: 2, max: 3 }; });
  order.slice(tiny + small).forEach((i) => { profile[i] = { min: 4, max: restMax }; });
  return profile;
}

// ---------------------------------------------------------------- 2) 영역 성장
const D4 = [[-1, 0], [1, 0], [0, -1], [0, 1]];

function growRegions(n, cols, profile, rnd) {
  const regions = Array.from({ length: n }, () => new Array(n).fill(-1));
  const sizes = new Array(n).fill(1);
  for (let r = 0; r < n; r++) regions[r][cols[r]] = r;   // 영역 i 의 씨앗 = i행의 토끼 칸

  const frontierOf = (g) => {
    const out = [];
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (regions[r][c] !== g) continue;
        for (const [dr, dc] of D4) {
          const nr = r + dr, nc = c + dc;
          if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
          if (regions[nr][nc] === -1) out.push([nr, nc]);
        }
      }
    }
    return out;
  };

  let remaining = n * n - n;

  // 1단계: 각 영역을 자기 min 까지 먼저 채운다 (min=1 인 영역은 그대로 둔다)
  for (let pass = 0; pass < 4 && remaining > 0; pass++) {
    for (const g of shuffle([...Array(n).keys()], rnd)) {
      while (sizes[g] < profile[g].min && remaining > 0) {
        const f = frontierOf(g);
        if (!f.length) break;
        const [fr, fc] = f[Math.floor(rnd() * f.length)];
        regions[fr][fc] = g; sizes[g]++; remaining--;
      }
    }
  }
  for (let g = 0; g < n; g++) if (sizes[g] < profile[g].min) return null;

  // 2단계: 남은 칸을 max 여유가 있는 영역에 가중 랜덤으로 배분
  const targets = new Array(n).fill(0).map(() => 1 + rnd() * 1.2);
  let guard = 0;
  while (remaining > 0 && guard++ < n * n * 60) {
    const weights = [];
    let total = 0;
    for (let i = 0; i < n; i++) {
      const w = sizes[i] >= profile[i].max ? 0 : targets[i] / (sizes[i] * sizes[i]);
      weights.push(w); total += w;
    }
    if (total <= 0) return null;                       // 모두 상한 -> 이 배치는 포기
    let pick = rnd() * total, g = 0;
    for (; g < n; g++) { pick -= weights[g]; if (pick <= 0 && weights[g] > 0) break; }
    if (g >= n) g = weights.findIndex((w) => w > 0);

    const frontier = frontierOf(g);
    if (!frontier.length) { targets[g] = 0; continue; }
    const [fr, fc] = frontier[Math.floor(rnd() * frontier.length)];
    regions[fr][fc] = g; sizes[g]++; remaining--;
  }
  return remaining > 0 ? null : regions;
}

// ---------------------------------------------------------------- 3) 해 찾기
/**
 * 행 단위 백트래킹 + 비트마스크 가지치기.
 * 아직 토끼를 못 받은 영역이 "남은 행" 또는 "남은 열"에 전혀 없으면 즉시 중단한다.
 */
export function findSolutions(n, regions, limit = 2) {
  const regRowMask = new Array(n).fill(0);
  const regColMask = new Array(n).fill(0);
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const g = regions[r][c];
      regRowMask[g] |= 1 << r;
      regColMask[g] |= 1 << c;
    }
  }
  const full = (1 << n) - 1;
  const cols = new Array(n).fill(-1);
  const found = [];
  let colUsedMask = 0, regUsedMask = 0;

  function feasible(r) {
    const rowsLeft = full & ~((1 << r) - 1);
    const colsLeft = full & ~colUsedMask;
    for (let g = 0; g < n; g++) {
      if (regUsedMask & (1 << g)) continue;
      if (!(regRowMask[g] & rowsLeft)) return false;
      if (!(regColMask[g] & colsLeft)) return false;
    }
    return true;
  }
  function rec(r) {
    if (found.length >= limit) return;
    if (r === n) { found.push(cols.slice()); return; }
    if (!feasible(r)) return;
    for (let c = 0; c < n; c++) {
      if (colUsedMask & (1 << c)) continue;
      const g = regions[r][c];
      if (regUsedMask & (1 << g)) continue;
      if (r > 0 && Math.abs(cols[r - 1] - c) <= 1) continue;
      colUsedMask |= 1 << c; regUsedMask |= 1 << g; cols[r] = c;
      rec(r + 1);
      colUsedMask &= ~(1 << c); regUsedMask &= ~(1 << g); cols[r] = -1;
      if (found.length >= limit) return;
    }
  }
  rec(0);
  return found;
}

// ---------------------------------------------------------------- 4) 영역 수선
// 칸 하나의 소속을 바꿔 "가짜 해"를 깨뜨린다.
// 정답 칸은 절대 옮기지 않으므로 원래 정답은 항상 유효하게 유지되고,
// 프로필(min/max)도 매 수선마다 검사하므로 난이도 규칙이 깨지지 않는다.
function regionStaysConnected(n, regions, cell, gid) {
  const [er, ec] = cell;
  const cells = [];
  for (let r = 0; r < n; r++)
    for (let c = 0; c < n; c++)
      if (regions[r][c] === gid && !(r === er && c === ec)) cells.push([r, c]);
  if (!cells.length) return false;
  const seen = new Set([cells[0][0] * n + cells[0][1]]);
  const stack = [cells[0]];
  while (stack.length) {
    const [r, c] = stack.pop();
    for (const [dr, dc] of D4) {
      const nr = r + dr, nc = c + dc;
      if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
      if (nr === er && nc === ec) continue;
      if (regions[nr][nc] !== gid) continue;
      const key = nr * n + nc;
      if (seen.has(key)) continue;
      seen.add(key); stack.push([nr, nc]);
    }
  }
  return seen.size === cells.length;
}

function touchesRegion(n, regions, r, c, gid) {
  for (const [dr, dc] of D4) {
    const nr = r + dr, nc = c + dc;
    if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
    if (regions[nr][nc] === gid) return true;
  }
  return false;
}

export function regionSizes(n, regions) {
  const s = new Array(n).fill(0);
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) s[regions[r][c]]++;
  return s;
}

/** (r,c) 를 gid 영역으로 옮길 수 있는가? (정답 칸 고정, 연결성 유지, 프로필 준수) */
function canRecolor(n, regions, sol, r, c, gid, sizes, profile) {
  const src = regions[r][c];
  if (src === gid) return false;
  if (sol[r] === c) return false;
  if (sizes[src] - 1 < profile[src].min) return false;
  if (sizes[gid] + 1 > profile[gid].max) return false;
  if (!touchesRegion(n, regions, r, c, gid)) return false;
  return regionStaysConnected(n, regions, [r, c], src);
}

function breakingMoves(n, regions, sol, alt, sizes, profile) {
  const moves = [];
  for (let r1 = 0; r1 < n; r1++) {
    for (let r2 = 0; r2 < n; r2++) {
      if (r1 === r2) continue;
      const a = [r1, alt[r1]];
      const gb = regions[r2][alt[r2]];
      if (regions[a[0]][a[1]] === gb) continue;
      // a 를 b 의 영역으로 옮기면 alt 는 한 영역에 토끼 2마리가 되어 무효
      if (canRecolor(n, regions, sol, a[0], a[1], gb, sizes, profile)) moves.push([a[0], a[1], gb]);
    }
  }
  return moves;
}

/** 목표 크기에서 많이 벗어난 영역을 되돌리는 방향의 수를 선호 */
function pickBalanced(n, regions, moves, sizes, profile, rnd) {
  const slack = (g) => sizes[g] - profile[g].min;
  const scored = moves.map((m) => ({ m, v: slack(regions[m[0]][m[1]]) - slack(m[2]) }));
  scored.sort((a, b) => b.v - a.v);
  const top = scored.slice(0, Math.max(1, Math.ceil(scored.length / 2)));
  return top[Math.floor(rnd() * top.length)].m;
}

function randomNudge(n, regions, sol, profile, rnd) {
  const sizes = regionSizes(n, regions);
  for (const k of shuffle([...Array(n * n).keys()], rnd)) {
    const r = Math.floor(k / n), c = k % n;
    for (const [dr, dc] of shuffle([...D4], rnd)) {
      const nr = r + dr, nc = c + dc;
      if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
      const gid = regions[nr][nc];
      if (canRecolor(n, regions, sol, r, c, gid, sizes, profile)) { regions[r][c] = gid; return true; }
    }
  }
  return false;
}

// ---------------------------------------------------------------- 5) 논리 솔버
const EMPTY = 0, RABBIT = 1, BLOCKED = -1;

function buildGroups(n, regions) {
  const groups = [];
  for (let i = 0; i < n; i++) groups.push({ kind: 'row', index: i, cells: [] });
  for (let i = 0; i < n; i++) groups.push({ kind: 'col', index: i, cells: [] });
  for (let i = 0; i < n; i++) groups.push({ kind: 'region', index: i, cells: [] });
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      groups[r].cells.push([r, c]);
      groups[n + c].cells.push([r, c]);
      groups[2 * n + regions[r][c]].cells.push([r, c]);
    }
  }
  return groups;
}

function combinations(arr, k) {
  const out = [];
  (function rec(start, cur) {
    if (cur.length === k) { out.push(cur.slice()); return; }
    for (let i = start; i < arr.length; i++) { cur.push(arr[i]); rec(i + 1, cur); cur.pop(); }
  })(0, []);
  return out;
}

/**
 * 논리 추론만으로 풀어본다.
 * 반환: ok(완주 여부), tier(사용한 최고 규칙 단계), steps(총 추론 수),
 *       firstPlace(첫 토끼 확정 전에 필요한 추론 수)
 */
export function logicSolve(n, regions, maxTier = 3) {
  const state = Array.from({ length: n }, () => new Array(n).fill(EMPTY));
  const groups = buildGroups(n, regions);
  let tier = 0, steps = 0, firstPlace = -1;

  const place = (r, c) => {
    state[r][c] = RABBIT;
    for (let i = 0; i < n; i++) {
      if (state[r][i] === EMPTY) state[r][i] = BLOCKED;
      if (state[i][c] === EMPTY) state[i][c] = BLOCKED;
    }
    const gid = regions[r][c];
    for (let rr = 0; rr < n; rr++)
      for (let cc = 0; cc < n; cc++)
        if (regions[rr][cc] === gid && state[rr][cc] === EMPTY) state[rr][cc] = BLOCKED;
    for (let dr = -1; dr <= 1; dr++)
      for (let dc = -1; dc <= 1; dc++) {
        const nr = r + dr, nc = c + dc;
        if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
        if (state[nr][nc] === EMPTY) state[nr][nc] = BLOCKED;
      }
  };
  const cands = (g) => g.cells.filter(([r, c]) => state[r][c] === EMPTY);
  const done = (g) => g.cells.some(([r, c]) => state[r][c] === RABBIT);

  let progress = true;
  while (progress) {
    progress = false;

    // T0: 후보가 하나뿐인 그룹 -> 확정
    for (const g of groups) {
      if (done(g)) continue;
      const cs = cands(g);
      if (!cs.length) return { ok: false };
      if (cs.length === 1) {
        if (firstPlace < 0) firstPlace = steps;
        steps++; place(cs[0][0], cs[0][1]); progress = true; break;
      }
    }
    if (progress) continue;

    // T1: 영역이 한 줄에 갇힘 / 줄이 한 영역에 갇힘
    if (maxTier >= 1) {
      for (const g of groups) {
        if (done(g)) continue;
        const cs = cands(g);
        const hits = [];
        if (g.kind === 'region') {
          const rows = new Set(cs.map((p) => p[0]));
          const cols = new Set(cs.map((p) => p[1]));
          if (rows.size === 1) {
            const r = [...rows][0];
            for (let c = 0; c < n; c++) if (state[r][c] === EMPTY && regions[r][c] !== g.index) hits.push([r, c]);
          } else if (cols.size === 1) {
            const c = [...cols][0];
            for (let r = 0; r < n; r++) if (state[r][c] === EMPTY && regions[r][c] !== g.index) hits.push([r, c]);
          }
        } else {
          const regs = new Set(cs.map((p) => regions[p[0]][p[1]]));
          if (regs.size === 1) {
            const gi = [...regs][0];
            for (let r = 0; r < n; r++)
              for (let c = 0; c < n; c++) {
                if (state[r][c] !== EMPTY || regions[r][c] !== gi) continue;
                if (g.kind === 'row' ? r !== g.index : c !== g.index) hits.push([r, c]);
              }
          }
        }
        if (hits.length) {
          for (const [r, c] of hits) state[r][c] = BLOCKED;
          tier = Math.max(tier, 1); steps++; progress = true; break;
        }
      }
      if (progress) continue;
    }

    if (maxTier >= 2 && kSetRule(n, regions, state, groups, cands, done)) {
      tier = Math.max(tier, 2); steps++; continue;
    }
    if (maxTier >= 3 && trialRule(n, regions, state, groups, cands, done)) {
      tier = Math.max(tier, 3); steps++; continue;
    }
  }

  const total = state.flat().filter((v) => v === RABBIT).length;
  return { ok: total === n, tier, steps, firstPlace: firstPlace < 0 ? Infinity : firstPlace };
}

function kSetRule(n, regions, state, groups, cands, done) {
  for (const kind of ['row', 'col']) {
    const lines = groups.filter((g) => g.kind === kind && !done(g));
    const regs = groups.filter((g) => g.kind === 'region' && !done(g));
    for (let k = 2; k <= 3; k++) {
      if (lines.length > k) {
        for (const combo of combinations(lines, k)) {
          const set = new Set();
          for (const g of combo) for (const [r, c] of cands(g)) set.add(regions[r][c]);
          if (set.size !== k) continue;
          const hits = [];
          for (const rg of regs) {
            if (!set.has(rg.index)) continue;
            for (const [r, c] of cands(rg)) {
              const idx = kind === 'row' ? r : c;
              if (!combo.some((g) => g.index === idx)) hits.push([r, c]);
            }
          }
          if (hits.length) { for (const [r, c] of hits) state[r][c] = BLOCKED; return true; }
        }
      }
      if (regs.length > k) {
        for (const combo of combinations(regs, k)) {
          const set = new Set();
          for (const g of combo) for (const [r, c] of cands(g)) set.add(kind === 'row' ? r : c);
          if (set.size !== k) continue;
          const hits = [];
          for (const ln of lines) {
            if (!set.has(ln.index)) continue;
            for (const [r, c] of cands(ln)) if (!combo.some((g) => g.index === regions[r][c])) hits.push([r, c]);
          }
          if (hits.length) { for (const [r, c] of hits) state[r][c] = BLOCKED; return true; }
        }
      }
    }
  }
  return false;
}

function trialRule(n, regions, state, groups, cands, done) {
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (state[r][c] !== EMPTY) continue;
      const killed = new Set();
      const kill = (rr, cc) => killed.add(rr * n + cc);
      for (let i = 0; i < n; i++) { kill(r, i); kill(i, c); }
      const gid = regions[r][c];
      for (let rr = 0; rr < n; rr++) for (let cc = 0; cc < n; cc++) if (regions[rr][cc] === gid) kill(rr, cc);
      for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
        const nr = r + dr, nc = c + dc;
        if (nr >= 0 && nc >= 0 && nr < n && nc < n) kill(nr, nc);
      }
      killed.delete(r * n + c);
      for (const g of groups) {
        if (done(g)) continue;
        if (g.cells.some((p) => p[0] === r && p[1] === c)) continue;
        if (cands(g).every((p) => killed.has(p[0] * n + p[1]))) { state[r][c] = BLOCKED; return true; }
      }
    }
  }
  return false;
}

// ---------------------------------------------------------------- 6) 난이도 규칙 검사
/**
 * 채택 기준: 이 단계까지의 규칙만으로 풀려야 한다 (찍기 없음).
 * easy/normal 은 T0(유일 후보) + T1(갇힘)만 요구한다.
 * hard 는 큰 판에서 "모든 영역 3칸 이상"과 T1 완주를 동시에 만족시키기가
 * 사실상 불가능해서 T2(k개 줄 <-> k개 영역)까지 허용한다.
 * T2 도 사람이 따라갈 수 있는 추론이고, 게임의 힌트 엔진은 여전히 상위 집합이다.
 */
const acceptTierFor = (difficulty, n) => {
  // 판이 커질수록 "모든 영역 3칸 이상"과 얕은 추론만으로 풀리는 조건을
  // 동시에 만족시키기 어려워진다. 작은 영역이 없으면 T0 가 초반에 안 터지기 때문.
  // 그래서 큰 판에는 더 깊은 규칙을 허용한다. 어느 쪽도 "찍기"는 아니고,
  // 게임의 힌트 엔진이 T3 까지 전부 말로 설명해 준다.
  if (n >= 14) return 3;
  if (difficulty === 'hard') return 2;
  return 1;
};

/** 생성 결과가 난이도 규격을 만족하는가? 어긋나면 사유 문자열을 돌려준다. */
export function checkDifficulty(n, difficulty, sizes, lg) {
  const ones = sizes.filter((s) => s === 1).length;
  const smalls = sizes.filter((s) => s >= 2 && s <= 3).length;
  const min = Math.min(...sizes);
  if (difficulty === 'easy') {
    if (ones < 1 || ones > 2) return `1칸 영역 ${ones}개 (1~2개여야 함)`;
    if (smalls < 1) return '2~3칸 영역이 없음';
    if (lg.firstPlace > 1) return `첫 확정까지 ${lg.firstPlace}수 (0~1이어야 함)`;
  } else if (difficulty === 'normal') {
    if (min < 2) return `최소 영역 ${min}칸 (2칸 이상이어야 함)`;
  } else {
    if (min < 3) return `최소 영역 ${min}칸 (3칸 이상이어야 함)`;
  }
  return null;
}

// ---------------------------------------------------------------- 7) 퍼즐 1개 만들기
function makePuzzle(n, difficulty, maxFactor, rnd, deadline, outerTries = 400, repairSteps = 3000) {
  const acceptTier = acceptTierFor(difficulty, n);
  for (let t = 0; t < outerTries; t++) {
    if (Date.now() > deadline) return null;
    const cols = randomSolution(n, rnd);
    if (!cols) continue;
    const profile = makeProfile(n, difficulty, maxFactor, rnd);
    if (!profile) continue;
    const regions = growRegions(n, cols, profile, rnd);
    if (!regions) continue;

    for (let step = 0; step < repairSteps; step++) {
      if ((step & 63) === 0 && Date.now() > deadline) return null;

      // 논리 풀이를 먼저 돌린다. 모든 규칙이 "확정된 수"만 만들기 때문에,
      // 논리만으로 완주했다는 것은 곧 해가 유일하다는 뜻이다.
      // (tools/build.mjs 가 최종 결과의 유일성을 독립적으로 다시 검증한다)
      const lg = logicSolve(n, regions, acceptTier);
      if (lg.ok) {
        const sizes = regionSizes(n, regions);
        const why = checkDifficulty(n, difficulty, sizes, lg);
        if (!why) return { regions, cols, sizes, lg, steps: step + 1 };
        if (!randomNudge(n, regions, cols, profile, rnd)) break;
        continue;
      }

      const sols = findSolutions(n, regions, 2);
      if (sols.length === 0) break;
      if (sols.length === 1) {
        if (!randomNudge(n, regions, cols, profile, rnd)) break;   // 유일하지만 논리로 안 풀림
        continue;
      }
      const alt = sols.find((s) => s.some((c, r) => c !== cols[r])) || sols[1];
      const sizes = regionSizes(n, regions);
      const moves = breakingMoves(n, regions, cols, alt, sizes, profile);
      if (moves.length) {
        const [r, c, g] = pickBalanced(n, regions, moves, sizes, profile, rnd);
        regions[r][c] = g;
      } else if (!randomNudge(n, regions, cols, profile, rnd)) break;
    }
  }
  return null;
}

// ---------------------------------------------------------------- 8) 풀 생성
// 5x5 는 레벨 커브 앞부분을 채우려고 넉넉히 뽑는다 (curate 단계에서 쉬운 것부터 고른다).
const PLAN = [
  [5, 14], [6, 5], [7, 5],
  [8, 4], [9, 4], [10, 4],
  [11, 3], [12, 3], [13, 3], [14, 3],
];

// 영역 크기 상한만 단계적으로 완화한다. 하한(난이도 정의)은 절대 완화하지 않는다.
const RELAX = [
  { maxFactor: 2.4, budgetMs: 20000 },
  { maxFactor: 3.0, budgetMs: 30000 },
  { maxFactor: 4.0, budgetMs: 60000 },
  { maxFactor: 99, budgetMs: 180000 },
];
const budgetFor = (relax, n) => relax.budgetMs * (n >= 13 ? 3 : n >= 11 ? 1.5 : 1);

const OUT = process.argv[2] || 'puzzles-pool.json';
const SIZES_ONLY = process.argv[3] ? process.argv[3].split(',').map(Number) : null;
const APPEND = process.argv[4] === '--append';   // 기존 풀에 이어붙이기
const rnd = mulberry32(APPEND ? 990113 : 20260727);
const pool = [];
if (APPEND && IS_MAIN) {
  try { pool.push(...JSON.parse(readFileSync(OUT, 'utf8')).puzzles); } catch (e) {}
}

function flush() {
  writeFileSync(OUT, JSON.stringify({
    version: 2,
    title: '토끼네 자리',
    kind: 'pool',
    rules: { perRow: 1, perCol: 1, perRegion: 1, diagonalAdjacencyForbidden: true },
    puzzles: pool,
  }) + '\n');
}

for (const [n, count] of (IS_MAIN ? PLAN : [])) {
  if (SIZES_ONLY && !SIZES_ONLY.includes(n)) continue;
  const difficulty = difficultyOf(n);
  for (let i = 0; i < count; i++) {
    const t0 = Date.now();
    let p = null;
    for (const relax of RELAX) {
      p = makePuzzle(n, difficulty, relax.maxFactor, rnd, Date.now() + budgetFor(relax, n));
      if (p) break;
      process.stderr.write(`   .. ${n}x${n} 상한 ${relax.maxFactor}N 시간 초과 -> 완화\n`);
    }
    if (!p) { process.stderr.write(`!! ${n}x${n} 생성 실패\n`); continue; }

    pool.push({
      size: n,
      difficulty,
      regions: p.regions,
      solution: p.cols,                                  // solution[r] = r행 토끼의 열
      metrics: {
        tier: p.lg.tier,
        steps: p.lg.steps,                               // 총 추론 수 (많을수록 어렵다)
        firstPlace: p.lg.firstPlace,                     // 첫 확정까지 걸린 추론 수
        minRegion: Math.min(...p.sizes),
        maxRegion: Math.max(...p.sizes),
        onesCount: p.sizes.filter((s) => s === 1).length,
      },
    });
    flush();
    const m = pool[pool.length - 1].metrics;
    process.stderr.write(
      `ok ${n}x${n} ${difficulty.padEnd(6)} 영역 ${m.minRegion}~${m.maxRegion} `
      + `1칸 ${m.onesCount}개  추론 ${m.steps}수  첫확정 ${m.firstPlace}수  ${((Date.now() - t0) / 1000).toFixed(1)}초\n`);
  }
}
if (IS_MAIN) process.stderr.write(`\n총 ${pool.length}개 퍼즐 -> ${OUT}\n`);
