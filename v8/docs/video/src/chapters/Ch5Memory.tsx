// Chapter 5 — the self-improving memory loop: pain → lesson → harvest → recall.
// True to: the /pain, /learn and /harvest skills (v8/.claude/skills), board.Board.record_lesson
// (a lesson filed by domain and topic, linked to its evidence, indexed), records.recall and
// board.Board._context_snapshot (recall rides inside the next seat's context()).
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Card, Chapter, Mono, T, useAppear } from "../components/kit";
import FACTS from "../code-facts.json"; // the harvest cap, from the /harvest skill

const R = 290;
const CX = 520;
const CY = 520;
const NODES = [
  { label: "pain", sub: "a tool or guide was wrong", c: C.danger, ang: -90, at: 40 },
  { label: "lesson", sub: "/learn · one sentence", c: C.warning, ang: 0, at: 90 },
  { label: "harvest", sub: `qa · epic end · ≤${FACTS.harvestMaxLessons} lessons`, c: C.success, ang: 90, at: 140 },
  { label: "recall", sub: "into the next context()", c: "#B9A3E0", ang: 180, at: 190 },
];

const pos = (ang: number, r = R) => ({ x: CX + r * Math.cos((ang * Math.PI) / 180), y: CY + r * Math.sin((ang * Math.PI) / 180) });

export const Ch5Memory: React.FC = () => {
  const frame = useCurrentFrame();
  const ring = useAppear(15);
  // a token travels the loop once the four stages are up, then hands the lesson to a new seat
  const t = interpolate(frame, [200, 300], [-90, 270], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const tok = pos(t);
  const next = useAppear(290);
  return (
    <Chapter
      num={6}
      title="Memory that improves itself"
      art="ch5-memory.png"
      captions={[
        { at: 30, text: <><T c={C.danger}>/pain</T>: any seat flags where a tool or guide was wrong.</> },
        { at: 100, text: <><T c={C.warning}>/learn</T> keeps a lesson; at epic end qa's <T c={C.success}>/harvest</T> turns rework into lessons and doc revisions.</> },
        { at: 210, text: <><T c="#B9A3E0">Recall</T> hands them to the next seat — even on another epic.</> },
      ]}
    >
      <svg width={1120} height={1080} style={{ position: "absolute", left: 0, top: 0 }}>
        <circle cx={CX} cy={CY} r={R} fill="none" stroke={C.border} strokeWidth={4} strokeDasharray="4 14"
          strokeDashoffset={-frame} opacity={ring * 0.7} />
      </svg>
      {NODES.map((n) => {
        const a = useAppearAt(n.at);
        const p = pos(n.ang);
        return (
          <div key={n.label} style={{ position: "absolute", left: p.x - 150, top: p.y - 60, width: 300, opacity: a, transform: `scale(${0.6 + 0.4 * a})` }}>
            <Card glow={n.c} style={{ padding: "16px 18px", textAlign: "center" }}>
              <div style={{ fontFamily: FONT, fontSize: 32, fontWeight: 800, color: n.c }}>{n.label}</div>
              <div style={{ fontSize: 19, color: C.muted, marginTop: 4 }}>{n.sub}</div>
            </Card>
          </div>
        );
      })}
      {frame > 200 && frame < 305 && (
        <div style={{ position: "absolute", left: tok.x - 18, top: tok.y - 18, width: 36, height: 36, borderRadius: 18, background: C.cream, boxShadow: `0 0 24px ${C.warning}` }} />
      )}
      <div style={{ position: "absolute", left: CX - 170, top: CY - 70, width: 340, textAlign: "center", opacity: next, transform: `scale(${0.7 + 0.3 * next})` }}>
        <Avatar role="engineer" size={96} />
        <div style={{ marginTop: 8 }}>
          <Mono size={19} color={C.text}>recall: 1 lesson</Mono>
        </div>
      </div>
    </Chapter>
  );
};

// hooks must not be called conditionally; a tiny wrapper keeps the map readable
function useAppearAt(at: number) {
  return useAppear(at);
}
