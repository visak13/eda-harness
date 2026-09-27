// Chapter 6 — one epic walking the board on its own.
// True to: edp8 board.Board.gate_open → auto_carry(trigger="design_signoff opened") (opening design_signoff
// moves the epic to designed; _design_gate_open then holds stories back while the gate is open),
// board.Board._record_gate_answer (the owner's approval → signed_off; stories released to ready)
// and board.Board._auto_advance (every verdict passed → done, "auto: all verdicts passed").
// Invented demo data only.
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Chapter, Mono, Pill, T, useAppear } from "../components/kit";

const COLS = ["drafted", "designed", "signed_off", "in_progress", "in_review", "done"];
// frame at which the card enters each column
const STEPS = [30, 75, 125, 170, 215, 300];

const COL_W = 170;
const X0 = 20;

export const Ch6Board: React.FC = () => {
  const frame = useCurrentFrame();
  const board = useAppear(8);
  let col = 0;
  STEPS.forEach((s, i) => { if (frame >= s) col = i; });
  const prev = Math.max(0, col - 1);
  const k = interpolate(frame, [STEPS[col], STEPS[col] + 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const x = X0 + (prev + (col - prev) * k) * COL_W + 8;
  const verdicts = [240, 256, 272].map((at) => frame >= at);
  const done = col === 5;
  const gate = frame >= 95 && frame < 150;
  return (
    <Chapter
      num={7}
      title="The board walks the epic"
      art="ch6-board.png"
      captions={[
        { at: 30, text: <>The board moves work on <T>facts</T>, not on anyone's memory.</> },
        { at: 105, text: <>The owner approves the design → <T>signed_off</T>, and its stories are released.</> },
        { at: 250, text: <>Every checker's verdict passes → <T c={C.success}>done, automatically</T>.</> },
      ]}
    >
      <div style={{ position: "absolute", left: X0, top: 170, opacity: board, display: "flex" }}>
        {COLS.map((c, i) => (
          <div key={c} style={{ width: COL_W - 10, marginRight: 10, height: 560, borderRadius: 16, background: i === col ? "#3A2F2A" : "#2A221F", border: `2px solid ${i === col ? C.accent : "#3F332E"}` }}>
            <div style={{ padding: "14px 12px", fontFamily: FONT, fontWeight: 800, fontSize: 19, color: i === col ? C.accent : C.muted }}>{c}</div>
          </div>
        ))}
      </div>
      {/* the epic card */}
      <div style={{ position: "absolute", left: x, top: 240, width: COL_W - 26, opacity: board }}>
        <div style={{ background: C.cream, color: C.buttonText, borderRadius: 14, padding: "14px 12px", boxShadow: done ? `0 0 0 6px ${C.success}88` : "0 10px 24px #0008" }}>
          <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: 2, color: C.beak }}>EPIC</div>
          <div style={{ fontSize: 19, fontWeight: 800, lineHeight: 1.2, marginTop: 4 }}>Dark mode for settings</div>
          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            {verdicts.map((v, i) => (
              <div key={i} style={{ width: 22, height: 22, borderRadius: 11, background: v ? "#3E8B5A" : "#D8C8B5", color: "#fff", fontSize: 14, textAlign: "center", lineHeight: "22px", fontWeight: 900 }}>{v ? "✓" : ""}</div>
            ))}
          </div>
        </div>
      </div>
      {/* the stories released at signed_off */}
      {[0, 1].map((i) => {
        const a = interpolate(frame, [150 + i * 10, 165 + i * 10], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        return (
          <div key={i} style={{ position: "absolute", left: X0 + 2 * COL_W + 8, top: 420 + i * 80, width: COL_W - 26, opacity: frame < 215 ? a : 0.35 }}>
            <div style={{ background: C.surface2, borderRadius: 12, padding: "10px 12px", fontSize: 16, fontWeight: 700, borderLeft: `5px solid ${C.success}` }}>
              story {i + 1} · ready
            </div>
          </div>
        );
      })}
      {/* the gate */}
      <div style={{ position: "absolute", left: X0 + COL_W, top: 780, opacity: gate ? 1 : 0, display: "flex", alignItems: "center", gap: 14 }}>
        <Pill color={C.warning} solid size={22}>design_signoff · owner: Approve</Pill>
      </div>
      {/* the checkers */}
      <div style={{ position: "absolute", left: X0 + 3 * COL_W, top: 780, display: "flex", gap: 14, opacity: frame >= 230 && !done ? 1 : 0 }}>
        <Avatar role="qa" size={60} />
        <Mono size={20} color={C.text} style={{ alignSelf: "center" }}>verdicts {verdicts.filter(Boolean).length}/3 pass</Mono>
      </div>
      <div style={{ position: "absolute", left: X0 + 3 * COL_W - 40, top: 780, opacity: done ? interpolate(frame, [300, 312], [0, 1], { extrapolateRight: "clamp" }) : 0 }}>
        <Pill color={C.success} solid size={24}>done · auto: all verdicts passed</Pill>
      </div>
    </Chapter>
  );
};
