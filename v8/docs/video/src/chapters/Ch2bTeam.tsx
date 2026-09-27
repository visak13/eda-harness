// Chapter 2b — people and agents in one thread, across machines, added at the owner's request.
// True to: edp8 board.Board.message_send / message_mentions (each @handle resolves to a participant;
// an unknown one is just prose and comes back as `unresolved_mentions`, service.py), delivery.after_message
// (the addressed seat and every @mention are mirrored into broker inboxes), board.Board._reason_for
// ("@mention" wakes the agent; a live seat's handle is role.<ticket>, board.py spawn — a bare
// @engineer is an empty-chair stub and wakes nobody, views._roster) and feed_driver (the seat's stream). Teammates reach the board over the
// tailnet (guides/tailnet-public-mode.md). Invented names only.
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "../theme";
import { Avatar, Card, Chapter, Mono, Pill, T, useAppear } from "../components/kit";

/** A person's avatar in the board's people style: rounded square, torso, round face, hair. */
const Person: React.FC<{ bg: string; torso: string; hair: string; size: number }> = ({ bg, torso, hair, size }) => (
  <svg width={size} height={size} viewBox="0 0 36 36">
    <rect width="36" height="36" rx="8" fill={bg} />
    <path d="M4 36c1-9 7-13 14-13s13 4 14 13" fill={torso} />
    <path d="M11 14c0-9 14-9 14 0v5c0 6-4 8-7 8s-7-2-7-8z" fill="#E8B996" />
    <path d="M10 16c0-10 16-10 16 0-3-4-6-5-8-5s-5 1-8 5" fill={hair} />
    <circle cx="15" cy="18" r="1" fill="#3A2B29" />
    <circle cx="22" cy="18" r="1" fill="#3A2B29" />
    <path d="M16 22q2 2 4 0" fill="none" stroke="#7D4B42" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
);

const MAYA = <Person bg="#E7BD66" torso="#8B4A32" hair="#3A2B29" size={64} />;
const THEO = <Person bg="#93C5A3" torso="#2E5C7A" hair="#8C5A2B" size={64} />;

const Msg: React.FC<{ at: number; who: React.ReactNode; name: string; where: string; children: React.ReactNode; agent?: boolean }> = ({
  at, who, name, where, children, agent,
}) => {
  const p = useAppear(at);
  return (
    <div style={{ display: "flex", gap: 18, opacity: p, transform: `translateY(${(1 - p) * 30}px)` }}>
      <div style={{ flex: "none" }}>{who}</div>
      <div style={{ flex: 1 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "baseline" }}>
          <span style={{ fontSize: 24, fontWeight: 800 }}>{name}</span>
          <span style={{ fontSize: 18, color: agent ? C.success : C.muted }}>{where}</span>
        </div>
        <div style={{ fontSize: 25, lineHeight: 1.35, marginTop: 4, color: C.text }}>{children}</div>
      </div>
    </div>
  );
};

const At: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ color: C.accent, fontWeight: 800, background: `${C.accent}22`, borderRadius: 6, padding: "0 6px" }}>{children}</span>
);

export const Ch2bTeam: React.FC = () => {
  const frame = useCurrentFrame();
  const card = useAppear(10);
  // the agent's wake: asleep until THEO's @mention lands (frame ~170), then awake and answering
  const woke = frame > 185;
  const ping = interpolate(frame, [185, 215], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <Chapter
      num={3}
      title="People and agents, one thread"
      captions={[
        { at: 30, text: <>Tag a <T>teammate</T> on another machine — they get the ping and join the thread.</> },
        { at: 130, text: <>They reply and <T>@mention an agent</T> running on your machine.</> },
        { at: 215, text: <>The mention rides the same <T>broker and feed</T>: the agent wakes and answers in the thread.</> },
      ]}
    >
      <div style={{ position: "absolute", left: 40, top: 130, width: 1020, opacity: card, transform: `translateY(${(1 - card) * 40}px)` }}>
        <Card style={{ padding: "26px 32px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 3, color: C.accent }}>THREAD · DARK MODE FOR SETTINGS</div>
            <Pill color={C.muted} size={17}>tailnet · 2 machines</Pill>
          </div>
          <div style={{ marginTop: 26, display: "flex", flexDirection: "column", gap: 26 }}>
            <Msg at={40} who={MAYA} name="Maya" where="her laptop">
              <At>@theo</At> can you sanity-check the contrast on the new dark theme?
            </Msg>
            <Msg at={120} who={THEO} name="Theo" where="his desktop · over the tailnet">
              Looks close. <At>@engineer.t-3f9a</At> what ratio does the muted text hit?
            </Msg>
            <Msg at={230} who={<Avatar role="engineer" size={64} />} name="engineer" where="agent seat · on Maya's machine" agent>
              Muted text is 8.0 : 1 on the dark background; AA needs 4.5. Evidence is on the criterion.
            </Msg>
          </div>
        </Card>
      </div>
      {/* the wake strip under the thread */}
      <div style={{ position: "absolute", left: 40, top: 800, width: 1020, display: "flex", alignItems: "center", gap: 18, fontFamily: FONT }}>
        <div style={{ borderRadius: 14, boxShadow: woke ? `0 0 0 ${4 + 6 * ping}px ${C.success}66` : "none", opacity: frame > 150 ? 1 : 0 }}>
          <Avatar role="engineer" size={70} asleep={!woke} />
        </div>
        <div style={{ opacity: interpolate(frame, [150, 165], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
          {woke ? (
            <Mono size={22} color={C.success}>woke · why: @mention · from theo</Mono>
          ) : (
            <Mono size={22}>engineer · asleep on its feed … zz</Mono>
          )}
        </div>
      </div>
    </Chapter>
  );
};
