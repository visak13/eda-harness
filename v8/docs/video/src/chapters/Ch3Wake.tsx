// Chapter 3 — reactive subscriptions: seats sleep on their feed and wake only on what concerns them.
// True to: edp8 board.Board._reason_for (who wakes, and the one-line "why"), service.feed (the
// server filters the board feed per seat) and feed_driver._stream_board_once (the seat's stream).
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Chapter, Mono, Pill, Role, T, useAppear } from "../components/kit";

const SEATS: Role[] = ["architect", "engineer", "qa", "adversary", "sme"];

// events on the board feed; `wakes` is the one seat the filter lets through, with its reason
const EVENTS = [
  { at: 60, label: "message → qa", wakes: 2, why: "addressed to you" },
  { at: 125, label: "story → in_review", wakes: 1, why: "on your ticket" },
  { at: 190, label: "@sme can you check this?", wakes: 4, why: "@mention" },
  { at: 255, label: "design_signoff gate opened", wakes: 0, why: "a gate you answer" },
];

const X0 = 40;
const STEP = 200;

export const Ch3Wake: React.FC = () => {
  const frame = useCurrentFrame();
  const feed = useAppear(10);
  return (
    <Chapter
      num={3}
      title="Seats sleep until it matters"
      art="ch3-wake.png"
      captions={[
        { at: 30, text: <>Each seat sleeps on <T>one feed</T>: board events plus its own inbox.</> },
        { at: 110, text: <>The board decides who wakes — <T>addressed to you</T>, your ticket, a gate you answer, an @mention.</> },
        { at: 230, text: <>Everyone else keeps sleeping. Every wake carries a <T>one-line why</T>.</> },
      ]}
    >
      {/* the feed rail */}
      <div style={{ position: "absolute", left: X0, top: 150, width: 1040, height: 90, borderRadius: 45, background: "#2A221F", border: `2px solid #4A3C35`, opacity: feed }}>
        <div style={{ position: "absolute", left: 30, top: -38, fontWeight: 800, letterSpacing: 3, color: C.accent, fontSize: 20 }}>BOARD FEED</div>
      </div>
      {EVENTS.map((e, i) => {
        const t = frame - e.at;
        if (t < -5 || t > 90) return null;
        const x = interpolate(t, [0, 25], [X0 + 1200, X0 + 20 + e.wakes * STEP + 85], { extrapolateRight: "clamp" });
        const drop = interpolate(t, [30, 45], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        const o = interpolate(t, [0, 6, 80, 90], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        return (
          <div key={i} style={{ position: "absolute", left: x, top: 172 + drop * 150, opacity: o, transform: "translateX(-50%)" }}>
            <Pill color={C.warning} solid size={20}>{e.label}</Pill>
          </div>
        );
      })}
      {SEATS.map((r, i) => {
        const active = EVENTS.find((e) => e.wakes === i && frame > e.at + 45 && frame < e.at + 125);
        const p = active ? interpolate(frame - active.at - 45, [0, 8], [0, 1], { extrapolateRight: "clamp" }) : 0;
        const zz = (frame / 20 + i) % 3;
        return (
          <div key={r} style={{ position: "absolute", left: X0 + 20 + i * STEP, top: 460, width: 170, textAlign: "center", fontFamily: FONT }}>
            <div style={{ height: 50, fontSize: 30, fontWeight: 800, color: C.muted, opacity: active ? 0 : 0.8 }}>
              {"z".repeat(1 + Math.floor(zz))}
            </div>
            <div style={{ display: "inline-block", borderRadius: 18, transform: `translateY(${-p * 16}px)`, boxShadow: active ? `0 0 0 ${6 + 4 * p}px ${C.success}66` : "none", opacity: active ? 1 : 0.6 }}>
              <Avatar role={r} size={120} asleep={!active} />
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, marginTop: 10, color: active ? C.text : C.muted }}>{r}</div>
            <div style={{ height: 70, marginTop: 14, opacity: p }}>
              {active && <Mono size={19} color={C.success}>why: {active.why}</Mono>}
            </div>
          </div>
        );
      })}
    </Chapter>
  );
};
