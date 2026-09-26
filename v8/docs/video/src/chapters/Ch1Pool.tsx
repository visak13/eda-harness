// Chapter 1 — the pool spawns seats as live shells.
// True to: edp-pool pty_launcher.PtyLaunch.spawn (claude in a pseudo-terminal, then one activation
// line), composite_spawner.CompositeSpawner.launch (codex / pi seats as their own processes),
// service.PoolService.liveness (alive · parked · resuming · dead · unknown) and the shell caps.
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Card, Chapter, Mono, Pill, Role, T, useAppear } from "../components/kit";

const SEATS: { harness: string; role: Role; how: string; lines: string[]; x: number; at: number }[] = [
  { harness: "claude", role: "architect", how: "pseudo-terminal", lines: ["> whoami()", "> subscribe()", "> context()"], x: 40, at: 60 },
  { harness: "codex", role: "engineer", how: "own process", lines: ["> context()", "> doc_read(plan)", "> build…"], x: 395, at: 95 },
  { harness: "pi", role: "qa", how: "own process", lines: ["> context()", "> criterion_query()", "> verify…"], x: 750, at: 130 },
];

const Shell: React.FC<(typeof SEATS)[number]> = ({ harness, role, how, lines, x, at }) => {
  const frame = useCurrentFrame();
  const p = useAppear(at);
  const typed = Math.max(0, Math.floor((frame - at - 20) / 14));
  // liveness chip: alive; the pi seat parks then resumes later in the chapter
  let state: [string, string] = ["alive", C.success];
  if (harness === "pi" && frame > 250 && frame < 290) state = ["parked", C.warning];
  if (harness === "pi" && frame >= 290 && frame < 315) state = ["resuming", C.accent];
  return (
    <div style={{ position: "absolute", left: x, top: 420, width: 330, opacity: p, transform: `translateY(${(1 - p) * -120}px) scale(${0.7 + 0.3 * p})` }}>
      <Card style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "16px 18px", background: C.surface2 }}>
          <Avatar role={role} size={54} />
          <div style={{ fontFamily: FONT }}>
            <div style={{ fontSize: 26, fontWeight: 800 }}>{role}</div>
            <div style={{ fontSize: 19, color: C.muted }}>{harness} · {how}</div>
          </div>
        </div>
        <div style={{ padding: "18px 20px", height: 150, display: "flex", flexDirection: "column", gap: 10 }}>
          {lines.slice(0, typed).map((l, i) => (
            <Mono key={i} size={21} color={i === Math.min(typed, lines.length) - 1 ? C.text : C.muted}>{l}</Mono>
          ))}
          {typed < lines.length + 2 && frame % 30 < 15 && <div style={{ width: 12, height: 22, background: C.accent }} />}
        </div>
      </Card>
      <div style={{ marginTop: 18, display: "flex", justifyContent: "center", opacity: interpolate(frame, [at + 30, at + 45], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
        <Pill color={state[1]}>● {state[0]}</Pill>
      </div>
    </div>
  );
};

export const Ch1Pool: React.FC = () => {
  const frame = useCurrentFrame();
  const pool = useAppear(8);
  const pulse = 1 + 0.03 * Math.sin(frame / 6);
  const cap = useAppear(200);
  return (
    <Chapter
      num={1}
      title="The pool spawns seats"
      art="ch1-pool.png"
      captions={[
        { at: 30, text: <>Every agent is a <T>seat</T>: a live shell with a role, spawned by the pool.</> },
        { at: 120, text: <>Claude, codex or pi. Claude runs in a real <T>pseudo-terminal</T>; codex and pi run as their own processes.</> },
        { at: 220, text: <>The pool watches each one — <T c={C.success}>alive</T>, <T c={C.warning}>parked</T>, <T>resuming</T> — and caps how many run at once.</> },
      ]}
    >
      {/* the pool */}
      <div style={{ position: "absolute", left: 250, top: 150, width: 600, opacity: pool, transform: `scale(${pool * pulse})` }}>
        <Card glow={C.accent} style={{ padding: "26px 30px", textAlign: "center" }}>
          <div style={{ fontSize: 22, color: C.accent, fontWeight: 800, letterSpacing: 3 }}>POOL</div>
          <div style={{ fontSize: 30, fontWeight: 800, marginTop: 6 }}>spawn · watch · park · reap</div>
        </Card>
      </div>
      {/* spawn lines */}
      <svg width={1120} height={1080} style={{ position: "absolute", left: 0, top: 0 }}>
        {SEATS.map((s, i) => {
          const len = interpolate(frame, [s.at - 25, s.at], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          const x2 = s.x + 165;
          return (
            <line key={i} x1={550} y1={300} x2={550 + (x2 - 550) * len} y2={300 + (420 - 300) * len}
              stroke={C.accent} strokeWidth={4} strokeDasharray="10 10" strokeDashoffset={-frame * 2} opacity={0.8} />
          );
        })}
      </svg>
      {SEATS.map((s) => <Shell key={s.role} {...s} />)}
      <div style={{ position: "absolute", left: 330, top: 860, width: 440, display: "flex", justifyContent: "center", opacity: cap }}>
        <Pill color={C.muted} size={20}>shells 3 / cap · workers · planners</Pill>
      </div>
    </Chapter>
  );
};
