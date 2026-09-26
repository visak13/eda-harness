// The README hero: a ≤8 s seamless loop (1200x630) — seats wake on the feed, a card walks the
// board to done, the logo holds. The last frame equals the first, so the loop has no seam.
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "./theme";
import { Avatar, Logo, Pill, Role } from "./components/kit";

export const HERO_FRAMES = 210; // 7 s at 30 fps

const ROLES: Role[] = ["architect", "engineer", "qa", "adversary", "sme"];
const COLS = ["designed", "in_progress", "in_review", "done"];

export const Hero: React.FC = () => {
  const frame = useCurrentFrame();
  // one wake per seat, spaced through the loop
  const wakeOf = (i: number) => {
    const at = 15 + i * 36;
    return interpolate(frame, [at, at + 8, at + 30, at + 40], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  };
  // the card walks designed → done and fades back to the start
  const pos = interpolate(frame, [20, 50, 80, 110, 140, 170], [0, 1, 1, 2, 2, 3], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const cardO = interpolate(frame, [0, 10, 185, 205], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const done = frame >= 170 && frame < 200;
  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT, color: C.text }}>
      <div style={{ position: "absolute", left: 60, top: 54, display: "flex", alignItems: "center", gap: 20 }}>
        <Logo size={84} />
        <div>
          <div style={{ fontSize: 56, fontWeight: 800, lineHeight: 1 }}>Heronry</div>
          <div style={{ fontSize: 22, color: C.muted, marginTop: 6 }}>your agent team, built on decisions, checked before delivery</div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 60, top: 220, display: "flex", gap: 22 }}>
        {ROLES.map((r, i) => {
          const w = wakeOf(i);
          return (
            <div key={r} style={{ textAlign: "center", width: 96 }}>
              <div style={{ display: "inline-block", borderRadius: 14, transform: `translateY(${-w * 10}px)`, boxShadow: w > 0.1 ? `0 0 0 ${4 + 4 * w}px ${C.success}66` : "none", opacity: 0.6 + 0.4 * w }}>
                <Avatar role={r} size={80} asleep={w < 0.5} />
              </div>
              <div style={{ fontSize: 17, fontWeight: 700, color: w > 0.5 ? C.text : C.muted, marginTop: 6 }}>{r}</div>
            </div>
          );
        })}
      </div>
      <div style={{ position: "absolute", left: 640, top: 200, display: "flex", gap: 10 }}>
        {COLS.map((c, i) => (
          <div key={c} style={{ width: 118, height: 330, borderRadius: 12, background: Math.round(pos) === i ? "#3A2F2A" : "#2A221F", border: `2px solid ${Math.round(pos) === i ? C.accent : "#3F332E"}` }}>
            <div style={{ padding: "10px 10px", fontWeight: 800, fontSize: 15, color: C.muted }}>{c}</div>
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: 640 + 8 + pos * 128, top: 250, width: 102, opacity: cardO }}>
        <div style={{ background: C.cream, color: C.buttonText, borderRadius: 10, padding: "10px 8px", fontSize: 15, fontWeight: 800, boxShadow: done ? `0 0 0 5px ${C.success}88` : "none" }}>
          Dark mode for settings
        </div>
      </div>
      <div style={{ position: "absolute", left: 640, top: 548, opacity: done ? 1 : 0 }}>
        <Pill color={C.success} solid size={18}>auto: all verdicts passed</Pill>
      </div>
    </AbsoluteFill>
  );
};
