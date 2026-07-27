#!/usr/bin/env node
/**
 * "토끼네 자리" 퍼즐 생성기
 *
 * 규칙(Queens / Star-Battle 계열):
 *   - N x N 보드, N개의 색 영역
 *   - 각 행 / 각 열 / 각 영역에 토끼가 정확히 한 마리
 *   - 토끼끼리 상하좌우 + 대각선으로 인접 불가
 *
 * 생성 절차:
 *   1) 조건을 만족하는 토끼 배치(해답)를 무작위로 만든다
 *   2) 해답 칸들을 씨앗으로 삼아 영역을 무작위로 키운다 (영역은 항상 연결됨)
 *   3) 해가 유일한지 확인한다
 *   4) 논리 추론만으로(찍기 없이) 풀리는지 확인한다  -> 힌트 기능이 항상 동작하도록 보장
 *
 * 사용: node tools/generate-puzzles.mjs [출력경로]   (기본 puzzles.json)
 */

import { writeFileSync } from 'node:fs';

// ---------------------------------------------------------------- RNG (재현 가능)
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------- 1) 해답 배치
function randomSolution(n, rnd) {
  // cols[r] = r행에 놓인 토끼의 열. 행/열 유일 + 인접 행끼리 열 차이 >= 2
  const cols = new Array(n).fill(-1);
  const used = new Array(n).fill(false);
  function rec(r) {
    if (r === n) return true;
    const order = shuffle([...Array(n).keys()], rnd);
    for (const c of order) {
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

function shuffle(arr, rnd) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

// ---------------------------------------------------------------- 2) 영역 성장
function growRegions(n, cols, rnd) {
  const regions = Array.from({ length: n }, () => new Array(n).fill(-1));
  const sizes = new Array(n).fill(1);
  // 영역 i 의 씨앗 = i행의 토끼 칸
  for (let r = 0; r < n; r++) regions[r][cols[r]] = r;

  // 영역마다 목표 크기를 조금씩 다르게 -> 모양이 단조롭지 않게
  const targets = new Array(n).fill(0).map(() => 1 + rnd() * 1.2);

  let remaining = n * n - n;
  const D = [[-1, 0], [1, 0], [0, -1], [0, 1]];

  const frontierOf = (g) => {
    const out = [];
    for (let r = 0; r < n; r++) {
      for (let c = 0; c < n; c++) {
        if (regions[r][c] !== g) continue;
        for (const [dr, dc] of D) {
          const nr = r + dr, nc = c + dc;
          if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
          if (regions[nr][nc] === -1) out.push([nr, nc]);
        }
      }
    }
    return out;
  };

  // 1단계: 모든 영역을 최소 크기까지 먼저 키운다 (1칸짜리 공짜 영역 방지)
  for (let pass = 0; pass < BOUNDS.min && remaining > 0; pass++) {
    for (const g of shuffle([...Array(n).keys()], rnd)) {
      if (sizes[g] >= BOUNDS.min || remaining <= 0) continue;
      const f = frontierOf(g);
      if (!f.length) continue;
      const [fr, fc] = f[Math.floor(rnd() * f.length)];
      regions[fr][fc] = g; sizes[g]++; remaining--;
    }
  }

  // 2단계: 나머지는 가중 랜덤으로 채운다
  let guard = 0;
  while (remaining > 0 && guard++ < n * n * 40) {
    // 작은 영역일수록 뽑힐 확률이 높게 (가중 랜덤). 상한에 닿은 영역은 제외
    const cap = maxRegionOf(n);
    const weights = [];
    let total = 0;
    for (let i = 0; i < n; i++) {
      const w = sizes[i] >= cap ? 0 : targets[i] / (sizes[i] * sizes[i]);
      weights.push(w); total += w;
    }
    if (total <= 0) break;                  // 모든 영역이 상한 -> 이 배치는 포기
    let pick = rnd() * total, g = 0;
    for (; g < n; g++) { pick -= weights[g]; if (pick <= 0 && weights[g] > 0) break; }
    if (g >= n) g = weights.findIndex((w) => w > 0);

    const frontier = frontierOf(g);
    if (!frontier.length) continue;
    const [fr, fc] = frontier[Math.floor(rnd() * frontier.length)];
    regions[fr][fc] = g;
    sizes[g]++; remaining--;
  }
  if (remaining > 0) return null;
  return regions;
}

// ---------------------------------------------------------------- 3) 해 찾기
/**
 * 행 단위 백트래킹 + 비트마스크 가지치기.
 * 아직 토끼를 못 받은 영역이 "남은 행" 또는 "남은 열"에 전혀 없으면 즉시 중단한다.
 * 유일성 증명(= 끝까지 다 뒤져야 하는 경우)에서 속도가 크게 갈린다.
 */
function findSolutions(n, regions, limit = 2) {
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
    const rowsLeft = full & ~((1 << r) - 1);       // r행 이후
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

// ---------------------------------------------------------------- 3-b) 영역 수선
// 한 칸의 소속 영역을 바꿔서 "가짜 해"를 깨뜨린다.
// 정답 S 는 항상 유효하게 유지된다: S 에 속한 칸은 절대 옮기지 않으므로
// 모든 영역은 여전히 S 의 토끼를 정확히 한 개씩 품는다.
const D4 = [[-1, 0], [1, 0], [0, -1], [0, 1]];

function regionStaysConnected(n, regions, cell, gid) {
  const [er, ec] = cell;
  const cells = [];
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (regions[r][c] === gid && !(r === er && c === ec)) cells.push([r, c]);
    }
  }
  if (cells.length === 0) return false;
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

/** 영역별 칸 수 */
function regionSizes(n, regions) {
  const s = new Array(n).fill(0);
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) s[regions[r][c]]++;
  return s;
}
/**
 * 영역 크기 제한. 너무 작은 영역은 공짜로 확정돼서 재미가 없고,
 * 너무 큰 영역은 제약이 약해서 보드가 밋밋해진다.
 * 큰 판에서 제한이 빡세면 수렴이 오래 걸리므로 BOUNDS 는 단계적으로 완화된다.
 */
const BOUNDS = { min: 3, maxFactor: 2.2 };
const maxRegionOf = (n) => Math.max(8, Math.ceil(BOUNDS.maxFactor * n));
// 채택 기준: T0(유일 후보) + T1(갇힘)만으로 풀리는 퍼즐.
// 사람이 따라가기 쉬운 추론만 요구하고, 게임의 힌트 엔진은 T2/T3 까지 갖춘 상위 집합이다.
const ACCEPT_TIER = 1;

/** (r,c) 를 gid 영역으로 옮길 수 있는가? (정답 칸 제외, 연결성·크기 유지) */
function canRecolor(n, regions, sol, r, c, gid, sizes) {
  const src = regions[r][c];
  if (src === gid) return false;
  if (sol[r] === c) return false;                       // 정답 칸은 고정
  if (sizes) {
    if (sizes[src] <= BOUNDS.min) return false;         // 너무 작아지지 않게
    if (sizes[gid] >= maxRegionOf(n)) return false;      // 너무 커지지 않게
  }
  if (!touchesRegion(n, regions, r, c, gid)) return false;
  return regionStaysConnected(n, regions, [r, c], src);
}

/** 가짜 해 alt 를 무효로 만드는 재색칠 후보들 */
function breakingMoves(n, regions, sol, alt, sizes) {
  const moves = [];
  for (let r1 = 0; r1 < n; r1++) {
    for (let r2 = 0; r2 < n; r2++) {
      if (r1 === r2) continue;
      const a = [r1, alt[r1]], b = [r2, alt[r2]];
      const gb = regions[b[0]][b[1]];
      if (regions[a[0]][a[1]] === gb) continue;
      // a 를 b 의 영역으로 옮기면 alt 는 한 영역에 토끼 2마리가 되어 무효
      if (canRecolor(n, regions, sol, a[0], a[1], gb, sizes)) moves.push([a[0], a[1], gb]);
    }
  }
  return moves;
}

/** 큰 영역 -> 작은 영역 방향의 수를 선호해서 고른다 (영역 크기 균형 유지) */
function pickBalanced(n, regions, moves, sizes, rnd) {
  const scored = moves.map((m) => ({ m, v: sizes[regions[m[0]][m[1]]] - sizes[m[2]] }));
  scored.sort((a, b) => b.v - a.v);
  const top = scored.slice(0, Math.max(1, Math.ceil(scored.length / 2)));
  return top[Math.floor(rnd() * top.length)].m;
}

/** 무작위 미세 변형 (막혔을 때 탈출용) */
function randomNudge(n, regions, sol, rnd) {
  const sizes = regionSizes(n, regions);
  const cells = shuffle([...Array(n * n).keys()], rnd);
  for (const k of cells) {
    const r = Math.floor(k / n), c = k % n;
    const neigh = shuffle([...D4], rnd);
    for (const [dr, dc] of neigh) {
      const nr = r + dr, nc = c + dc;
      if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
      const gid = regions[nr][nc];
      if (canRecolor(n, regions, sol, r, c, gid, sizes)) { regions[r][c] = gid; return true; }
    }
  }
  return false;
}

// ---------------------------------------------------------------- 4) 논리 솔버
// index.html 의 힌트 엔진과 동일한 규칙 집합(등급 판정용 축약 버전).
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

function logicSolve(n, regions, maxTier = 3) {
  const state = Array.from({ length: n }, () => new Array(n).fill(EMPTY));
  const groups = buildGroups(n, regions);
  let usedTier = 0;

  const place = (r, c) => {
    state[r][c] = RABBIT;
    for (let i = 0; i < n; i++) {
      if (state[r][i] === EMPTY) state[r][i] = BLOCKED;
      if (state[i][c] === EMPTY) state[i][c] = BLOCKED;
    }
    for (let rr = 0; rr < n; rr++) {
      for (let cc = 0; cc < n; cc++) {
        if (regions[rr][cc] === regions[r][c] && state[rr][cc] === EMPTY) state[rr][cc] = BLOCKED;
      }
    }
    for (let dr = -1; dr <= 1; dr++) {
      for (let dc = -1; dc <= 1; dc++) {
        const nr = r + dr, nc = c + dc;
        if (nr < 0 || nc < 0 || nr >= n || nc >= n) continue;
        if (state[nr][nc] === EMPTY) state[nr][nc] = BLOCKED;
      }
    }
  };

  const cands = (g) => g.cells.filter(([r, c]) => state[r][c] === EMPTY);
  const solved = (g) => g.cells.some(([r, c]) => state[r][c] === RABBIT);

  let progress = true;
  while (progress) {
    progress = false;

    // Tier 0: 그룹에 후보가 하나뿐 -> 확정
    for (const g of groups) {
      if (solved(g)) continue;
      const cs = cands(g);
      if (cs.length === 1) { place(cs[0][0], cs[0][1]); progress = true; usedTier = Math.max(usedTier, 0); break; }
      if (cs.length === 0) return { ok: false };
    }
    if (progress) continue;

    // Tier 1: 영역이 한 줄에 갇힘 / 줄이 한 영역에 갇힘
    if (maxTier >= 1) {
      for (const g of groups) {
        if (solved(g)) continue;
        const cs = cands(g);
        if (g.kind === 'region') {
          const rows = new Set(cs.map(([r]) => r));
          const cols = new Set(cs.map(([, c]) => c));
          if (rows.size === 1) {
            const r = [...rows][0];
            for (let c = 0; c < n; c++) {
              if (state[r][c] === EMPTY && regions[r][c] !== g.index) { state[r][c] = BLOCKED; progress = true; }
            }
          }
          if (cols.size === 1) {
            const c = [...cols][0];
            for (let r = 0; r < n; r++) {
              if (state[r][c] === EMPTY && regions[r][c] !== g.index) { state[r][c] = BLOCKED; progress = true; }
            }
          }
        } else {
          const regs = new Set(cs.map(([r, c]) => regions[r][c]));
          if (regs.size === 1) {
            const gi = [...regs][0];
            for (let r = 0; r < n; r++) {
              for (let c = 0; c < n; c++) {
                if (state[r][c] !== EMPTY || regions[r][c] !== gi) continue;
                if (g.kind === 'row' ? r !== g.index : c !== g.index) { state[r][c] = BLOCKED; progress = true; }
              }
            }
          }
        }
        if (progress) { usedTier = Math.max(usedTier, 1); break; }
      }
      if (progress) continue;
    }

    // Tier 2: k개 줄이 k개 영역에만 걸침 (k=2,3)
    if (maxTier >= 2 && kSetConfinement(n, regions, state, groups, cands, solved)) {
      usedTier = Math.max(usedTier, 2); continue;
    }

    // Tier 3: 한 칸 가정 -> 어떤 그룹이 자리를 잃으면 그 칸은 불가
    if (maxTier >= 3 && trialElimination(n, regions, state, groups, cands, solved)) {
      usedTier = Math.max(usedTier, 3); continue;
    }
  }

  const total = state.flat().filter((v) => v === RABBIT).length;
  return { ok: total === n, tier: usedTier, state };
}

function combinations(arr, k) {
  const out = [];
  const rec = (start, cur) => {
    if (cur.length === k) { out.push([...cur]); return; }
    for (let i = start; i < arr.length; i++) { cur.push(arr[i]); rec(i + 1, cur); cur.pop(); }
  };
  rec(0, []);
  return out;
}

function kSetConfinement(n, regions, state, groups, cands, solved) {
  for (const kind of ['row', 'col']) {
    const lines = groups.filter((g) => g.kind === kind && !solved(g));
    const regs = groups.filter((g) => g.kind === 'region' && !solved(g));
    for (let k = 2; k <= 3; k++) {
      if (lines.length <= k) break;
      for (const combo of combinations(lines, k)) {
        const set = new Set();
        for (const g of combo) for (const [r, c] of cands(g)) set.add(regions[r][c]);
        if (set.size !== k) continue;
        let changed = false;
        for (const rg of regs) {
          if (!set.has(rg.index)) continue;
          for (const [r, c] of cands(rg)) {
            const idx = kind === 'row' ? r : c;
            if (!combo.some((g) => g.index === idx)) { state[r][c] = BLOCKED; changed = true; }
          }
        }
        if (changed) return true;
      }
      // 반대 방향: k개 영역이 k개 줄에만 걸침
      if (regs.length <= k) continue;
      for (const combo of combinations(regs, k)) {
        const set = new Set();
        for (const g of combo) for (const [r, c] of cands(g)) set.add(kind === 'row' ? r : c);
        if (set.size !== k) continue;
        let changed = false;
        for (const ln of lines) {
          if (!set.has(ln.index)) continue;
          for (const [r, c] of cands(ln)) {
            if (!combo.some((g) => g.index === regions[r][c])) { state[r][c] = BLOCKED; changed = true; }
          }
        }
        if (changed) return true;
      }
    }
  }
  return false;
}

function trialElimination(n, regions, state, groups, cands, solved) {
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (state[r][c] !== EMPTY) continue;
      // r,c 에 토끼를 놓았다고 가정했을 때 후보가 0인 그룹이 생기면 모순
      const killed = new Set();
      const kill = (rr, cc) => killed.add(rr * n + cc);
      for (let i = 0; i < n; i++) { kill(r, i); kill(i, c); }
      for (let rr = 0; rr < n; rr++) for (let cc = 0; cc < n; cc++) if (regions[rr][cc] === regions[r][c]) kill(rr, cc);
      for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
        const nr = r + dr, nc = c + dc;
        if (nr >= 0 && nc >= 0 && nr < n && nc < n) kill(nr, nc);
      }
      killed.delete(r * n + c);
      for (const g of groups) {
        if (solved(g)) continue;
        if (g.cells.some(([rr, cc]) => rr === r && cc === c)) continue;
        const left = cands(g).filter(([rr, cc]) => !killed.has(rr * n + cc));
        if (left.length === 0) { state[r][c] = BLOCKED; return true; }
      }
    }
  }
  return false;
}

// ---------------------------------------------------------------- 퍼즐 1개 만들기
/**
 * 무작위 성장 -> "가짜 해 깨기" 수선 -> 유일해 확보 -> 논리 풀이 가능 확인.
 * 논리로 안 풀리면 살짝 흔들어서(nudge) 다시 수선한다.
 */
function makePuzzle(n, rnd, deadline = Infinity, outerTries = 200, repairSteps = 2500) {
  for (let t = 0; t < outerTries; t++) {
    if (Date.now() > deadline) return null;
    const cols = randomSolution(n, rnd);
    if (!cols) continue;
    const regions = growRegions(n, cols, rnd);
    if (!regions) continue;

    for (let step = 0; step < repairSteps; step++) {
      if ((step & 63) === 0 && Date.now() > deadline) return null;
      const sizes = regionSizes(n, regions);
      // 크기가 극단적인 영역은 유일성 검사(비쌈) 전에 먼저 다듬는다
      if (Math.min(...sizes) < BOUNDS.min || Math.max(...sizes) > maxRegionOf(n)) {
        if (!randomNudge(n, regions, cols, rnd)) break;
        continue;
      }
      // 논리 풀이를 먼저 돌린다. 규칙들이 모두 "확정된 수"만 만들기 때문에
      // 논리만으로 끝까지 풀렸다는 것은 곧 해가 유일하다는 뜻이기도 하다.
      // (그래도 tools/build.mjs 가 최종 결과의 유일성을 독립적으로 다시 검증한다)
      const lg = logicSolve(n, regions, ACCEPT_TIER);
      if (lg.ok) return { regions, cols, tier: lg.tier, steps: step + 1, sizes };

      const sols = findSolutions(n, regions, 2);
      if (sols.length === 0) break;             // 있을 수 없음 (정답이 항상 유효)
      if (sols.length === 1) {
        if (!randomNudge(n, regions, cols, rnd)) break;   // 유일하지만 논리로 안 풀림 -> 흔들기
        continue;
      }
      const alt = sols.find((s) => s.some((c, r) => c !== cols[r])) || sols[1];
      const moves = breakingMoves(n, regions, cols, alt, sizes);
      if (moves.length) {
        const [r, c, g] = pickBalanced(n, regions, moves, sizes, rnd);
        regions[r][c] = g;
      } else if (!randomNudge(n, regions, cols, rnd)) {
        break;
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------- 레벨 구성
const PLAN = [
  // [크기, 개수]
  [5, 3], [6, 3], [7, 3],       // 쉬움
  [8, 3], [9, 3], [10, 3],      // 보통
  [11, 2], [12, 2], [13, 2], [14, 2], // 어려움
];

function difficultyOf(n) {
  if (n <= 7) return 'easy';
  if (n <= 10) return 'normal';
  return 'hard';
}

const OUT = process.argv[2] || 'puzzles.json';
const rnd = mulberry32(20260727);
const levels = [];

function flush() {
  levels.forEach((lv, i) => { lv.id = `L${String(i + 1).padStart(2, '0')}`; lv.index = i + 1; });
  writeFileSync(OUT, JSON.stringify({
    version: 1,
    title: '토끼네 자리',
    rules: { perRow: 1, perCol: 1, perRegion: 1, diagonalAdjacencyForbidden: true },
    levels,
  }) + '\n');
}

// 크기 제한을 빡세게 잡을수록 큰 판에서 수렴이 느려진다.
// 제한 단계를 순서대로 시도하고, 각 단계마다 시간 예산을 준다.
const RELAX = [
  { min: 3, maxFactor: 2.2, budgetMs: 20000 },
  { min: 3, maxFactor: 2.6, budgetMs: 20000 },
  { min: 2, maxFactor: 3.0, budgetMs: 40000 },
  { min: 1, maxFactor: 99,  budgetMs: 240000 },  // 최후: 크기 제한 해제 + 넉넉한 시간
];
// 큰 판일수록 수렴이 오래 걸린다
const budgetFor = (relax, n) => relax.budgetMs * (n >= 13 ? 3 : n >= 11 ? 1.5 : 1);

for (const [n, count] of PLAN) {
  for (let i = 0; i < count; i++) {
    const t0 = Date.now();
    let p = null, used = null;
    for (const relax of RELAX) {
      BOUNDS.min = relax.min; BOUNDS.maxFactor = relax.maxFactor;
      p = makePuzzle(n, rnd, Date.now() + budgetFor(relax, n));
      if (p) { used = relax; break; }
      process.stderr.write(`   .. ${n}x${n} 제한(min ${relax.min}, max ${relax.maxFactor}N) 시간 초과 -> 완화\n`);
    }
    if (!p) { process.stderr.write(`!! ${n}x${n} 생성 실패\n`); continue; }
    if (used !== RELAX[0]) process.stderr.write(`   .. ${n}x${n} 완화된 제한으로 생성 (min ${used.min}, max ${used.maxFactor}N)\n`);
    levels.push({
      id: '', index: 0,
      size: n,
      difficulty: difficultyOf(n),
      tier: p.tier,
      regions: p.regions,
      solution: p.cols, // solution[r] = r행 토끼의 열
    });
    flush();   // 한 레벨 만들 때마다 저장 (중간에 끊겨도 결과 보존)
    process.stderr.write(`ok ${String(p.steps).padStart(4)}수선  ${n}x${n}  tier=${p.tier}  영역크기 ${Math.min(...p.sizes)}~${Math.max(...p.sizes)}  ${((Date.now() - t0) / 1000).toFixed(1)}초\n`);
  }
}
process.stderr.write(`\n총 ${levels.length}개 레벨 -> ${OUT}\n`);
