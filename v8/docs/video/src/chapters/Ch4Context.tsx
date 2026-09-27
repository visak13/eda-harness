// Chapter 4 — context engineering.
// True to: edp8 bundles._context (the byte-budgeted snapshot; default bundles._CONTEXT_BUDGET_B, read
// into src/code-facts.json by scripts/code-facts.mjs; env EDP8_CONTEXT_BUDGET_B),
// context_delta.ContextReader.delta (signed cursor, only what changed), records.recall (up to 8
// one-line decisions/claims/lessons) and ruleset.assemble_ruleset (layered strategy docs, enforced
// lines inlined, each doc one index line).
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Card, Chapter, Mono, Pill, T, useAppear } from "../components/kit";
import FACTS from "../code-facts.json";

// the default budget, from the code (8_000 B → "8 KB"); the pack rows are sized to fit under it
const BUDGET_KB = FACTS.contextBudgetBytes / 1000;
const kb = (n: number) => (Number.isInteger(n) ? `${n}` : n.toFixed(1));

const PACK = [
  { label: "ticket + chain", kb: 1.6, at: 40, c: C.accent },
  { label: "criteria", kb: 0.6, at: 55, c: C.success },
  { label: "design summary", kb: 1.2, at: 70, c: C.warning },
  { label: "thread (newest)", kb: 1.4, at: 85, c: C.muted },
  { label: "recall: 3 lessons", kb: 1.0, at: 100, c: "#B9A3E0" },
];

const LAYERS = [
  { label: "base: how strategies compose", at: 250 },
  { label: "hl-craft: shipping", at: 265 },
  { label: "ll-craft: process control", at: 280 },
];

export const Ch4Context: React.FC = () => {
  const frame = useCurrentFrame();
  const pack = useAppear(20);
  const used = PACK.filter((p) => frame > p.at).reduce((n, p) => n + p.kb, 0);
  const delta = useAppear(160);
  const cursor = Math.min(3, Math.max(0, Math.floor((frame - 175) / 18)));
  return (
    <Chapter
      num={5}
      title="Context, engineered"
      art="ch4-context.png"
      captions={[
        { at: 30, text: <>A seat boots from one <T>bounded context pack</T> — {kb(BUDGET_KB)} KB by default, newest first.</> },
        { at: 150, text: <>After that, <T>context_delta</T> returns only what changed since its cursor.</> },
        { at: 245, text: <><T>Recall</T> brings past decisions and lessons; linked <T>strategy docs</T> layer the rules.</> },
      ]}
    >
      {/* the pack */}
      <div style={{ position: "absolute", left: 40, top: 150, width: 500, opacity: pack, transform: `translateY(${(1 - pack) * 40}px)` }}>
        <Card style={{ padding: 26 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 3, color: C.accent }}>context()</div>
            <Mono size={20} color={C.text}>{kb(used)} KB / {kb(BUDGET_KB)} KB</Mono>
          </div>
          <div style={{ height: 12, borderRadius: 6, background: "#4A3C35", marginTop: 14, overflow: "hidden" }}>
            <div style={{ width: `${(used / BUDGET_KB) * 100}%`, height: "100%", background: C.success }} />
          </div>
          <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 12 }}>
            {PACK.map((p) => {
              const a = interpolate(frame, [p.at, p.at + 12], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              return (
                <div key={p.label} style={{ opacity: a, transform: `translateX(${(1 - a) * 60}px)`, display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", borderRadius: 12, background: C.surface2, borderLeft: `6px solid ${p.c}` }}>
                  <span style={{ fontFamily: FONT, fontSize: 24, fontWeight: 700, flex: 1 }}>{p.label}</span>
                  <Mono size={18}>{p.kb.toFixed(1)} KB</Mono>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
      {/* the delta */}
      <div style={{ position: "absolute", left: 590, top: 150, width: 460, opacity: delta, transform: `translateX(${(1 - delta) * 40}px)` }}>
        <Card style={{ padding: 26 }}>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 3, color: C.accent }}>context_delta(cursor)</div>
          <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 10 }}>
            {["+ steer from the architect", "~ criterion 2 → evidence", "+ answer from qa"].slice(0, cursor).map((l) => (
              <Mono key={l} size={21} color={C.text}>{l}</Mono>
            ))}
          </div>
          <div style={{ marginTop: 18, display: "flex", gap: 10 }}>
            <Pill color={C.success} size={18}>{cursor} changes</Pill>
            <Pill color={C.muted} size={18}>next_cursor ▸</Pill>
          </div>
        </Card>
      </div>
      {/* the strategy layers */}
      <div style={{ position: "absolute", left: 590, top: 520, width: 460 }}>
        {LAYERS.map((l, i) => {
          const a = interpolate(frame, [l.at, l.at + 14], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
          return (
            <div key={l.label} style={{ opacity: a, transform: `translateY(${(1 - a) * -30}px)`, marginLeft: i * 26, marginTop: 12, padding: "14px 18px", borderRadius: 14, background: C.surface, border: `2px solid ${i === 2 ? C.accent : "#4A3C35"}`, fontSize: 22, fontWeight: 700 }}>
              {l.label}
            </div>
          );
        })}
        <div style={{ marginTop: 18, marginLeft: 52, opacity: interpolate(frame, [300, 315], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
          <Pill color={C.accent} size={18}>assemble_ruleset → enforced lines + index</Pill>
        </div>
      </div>
    </Chapter>
  );
};
