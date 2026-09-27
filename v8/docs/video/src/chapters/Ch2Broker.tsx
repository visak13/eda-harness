// Chapter 2 — the broker carries messages between seats.
// True to: edp-broker service.publish (resolve alias, strictly increasing timestamp, append to the
// recipient's append-only JSONL inbox, wake its live stream), store.InboxStore.append, and the
// refusal of a recipient it cannot route (store._safe → BadRecipient → service logs publish_no_route and
// answers BROKER_NO_ROUTE). A well-formed unknown handle is the board's refusal, not the broker's.
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Card, Chapter, Mono, Pill, Role, T, useAppear } from "../components/kit";

const CX = 560;
const CY = 470;
const NODES: { role: Role; x: number; y: number }[] = [
  { role: "architect", x: 160, y: 190 },
  { role: "engineer", x: 960, y: 190 },
  { role: "qa", x: 960, y: 750 },
  { role: "sme", x: 160, y: 750 },
];

// a message: from → to, leaves the sender at `at`, reaches the broker, then the recipient
const MSGS = [
  { from: 0, to: 1, at: 50, text: "steer: use the plan" },
  { from: 1, to: 2, at: 140, text: "ready for review" },
  { from: 2, to: 1, at: 215, text: "question: evidence?" },
];

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

const Envelope: React.FC<{ m: (typeof MSGS)[number] }> = ({ m }) => {
  const frame = useCurrentFrame();
  const t = frame - m.at;
  if (t < 0 || t > 70) return null;
  const a = NODES[m.from];
  const b = NODES[m.to];
  const leg1 = interpolate(t, [0, 28], [0, 1], { extrapolateRight: "clamp" });
  const leg2 = interpolate(t, [34, 62], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const x = t < 31 ? lerp(a.x, CX, leg1) : lerp(CX, b.x, leg2);
  const y = t < 31 ? lerp(a.y, CY, leg1) : lerp(CY, b.y, leg2);
  const fade = interpolate(t, [60, 70], [1, 0], { extrapolateLeft: "clamp" });
  return (
    <div style={{ position: "absolute", left: x - 34, top: y - 24, opacity: fade }}>
      <svg width={68} height={48} viewBox="0 0 68 48">
        <rect x="2" y="2" width="64" height="44" rx="8" fill={C.cream} />
        <path d="M4 6l30 22 30-22" stroke={C.beak} strokeWidth="4" fill="none" />
      </svg>
    </div>
  );
};

const Inbox: React.FC<{ n: number; idx: number }> = ({ n, idx }) => {
  const frame = useCurrentFrame();
  const count = MSGS.filter((m) => m.to === idx && frame > m.at + 62).length;
  return (
    <div style={{ display: "flex", gap: 6, marginTop: 10, justifyContent: "center", minHeight: 22 }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} style={{ width: 30, height: 20, borderRadius: 4, background: C.cream, opacity: 0.9 }} />
      ))}
      {count === 0 && <Mono size={17}>inbox · {n}</Mono>}
    </div>
  );
};

export const Ch2Broker: React.FC = () => {
  const frame = useCurrentFrame();
  const hub = useAppear(10);
  const lastWake = MSGS.filter((m) => frame > m.at + 62).pop();
  const dead = useAppear(265);
  return (
    <Chapter
      num={2}
      title="The broker carries the mail"
      art="ch2-broker.png"
      captions={[
        { at: 30, text: <>Every seat has a <T>mailbox</T> — an append-only log the broker keeps.</> },
        { at: 120, text: <>Publishing stamps the message, appends it and <T>wakes</T> the recipient's stream at once. No polling.</> },
        { at: 255, text: <>A recipient it cannot route is <T c={C.danger}>refused loudly</T> — never silently dropped.</> },
      ]}
    >
      <svg width={1120} height={1080} style={{ position: "absolute", left: 0, top: 0 }}>
        {NODES.map((n, i) => (
          <line key={i} x1={CX} y1={CY} x2={n.x} y2={n.y} stroke={C.border} strokeWidth={3} strokeDasharray="6 12" opacity={hub * 0.6} />
        ))}
      </svg>
      <div style={{ position: "absolute", left: CX - 170, top: CY - 80, width: 340, transform: `scale(${hub})` }}>
        <Card glow={C.accent} style={{ padding: "22px 20px", textAlign: "center" }}>
          <div style={{ fontSize: 22, color: C.accent, fontWeight: 800, letterSpacing: 3 }}>BROKER</div>
          <div style={{ fontSize: 26, fontWeight: 800, marginTop: 6 }}>publish → append → wake</div>
        </Card>
      </div>
      {NODES.map((n, i) => {
        const woke = lastWake && lastWake.to === i && frame - lastWake.at < 100;
        return (
          <div key={n.role} style={{ position: "absolute", left: n.x - 90, top: n.y - 70, width: 180, textAlign: "center", fontFamily: FONT }}>
            <div style={{ display: "inline-block", borderRadius: 16, boxShadow: woke ? `0 0 0 8px ${C.success}55` : "none" }}>
              <Avatar role={n.role} size={96} />
            </div>
            <div style={{ fontSize: 24, fontWeight: 800 }}>{n.role}</div>
            <Inbox n={0} idx={i} />
          </div>
        );
      })}
      {MSGS.map((m, i) => <Envelope key={i} m={m} />)}
      {MSGS.map((m, i) => {
        const t = frame - m.at;
        const o = interpolate(t, [0, 8, 70, 80], [0, 1, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
        return (
          <div key={`l${i}`} style={{ position: "absolute", left: CX - 200, top: CY + 90, width: 400, textAlign: "center", opacity: o }}>
            <Mono size={20} color={C.text}>{NODES[m.from].role} → {NODES[m.to].role}: “{m.text}”</Mono>
          </div>
        );
      })}
      <div style={{ position: "absolute", left: CX - 210, top: CY + 150, width: 420, display: "flex", justifyContent: "center", opacity: dead, transform: `scale(${0.8 + 0.2 * dead})` }}>
        <Pill color={C.danger} size={20}>to: “qa lead” → refused · no route logged</Pill>
      </div>
    </Chapter>
  );
};
