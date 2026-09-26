import React from "react";
import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  Easing,
} from "remotion";
import { C, FONT, H, MONO, ROLE } from "../theme";
import { ART_READY } from "../art";

export type Role = keyof typeof ROLE;

/** 0→1 spring that starts at `at` frames. */
export const useAppear = (at: number, damping = 16) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - at, fps, config: { damping, mass: 0.7 } });
};

/** Linear 0→1 between two frames, clamped, eased. */
export const useProgress = (from: number, to: number) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [from, to], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.inOut(Easing.cubic),
  });
};

// ---------------------------------------------------------------------------------------------
// The board's agent avatar (web/src/components/agentAvatars.ts), drawn as the same person.
const HAIR: Record<Role, string> = {
  architect: "M10 17V13c1-8 14-9 17-3-6-1-8 5-17 7",
  engineer: "M10 15c2-8 13-9 17-2l-6-2-4 4-7 2",
  qa: "M9 16c2-9 8-10 10-5 4-5 9-1 8 5l-6-3-3 3-4-2-5 4",
  adversary: "M9 15c2-7 5-8 8-7l2 4 8-2v6l-4-2-4 3-5-3-5 3",
  sme: "M10 14c1-7 4-8 6-5 2-4 5-2 5 1 3-3 6 0 5 5",
};
const TORSO: Record<Role, string> = {
  architect: "#4B252B", engineer: "#2E9C64", qa: "#8B4A32", adversary: "#17191E", sme: "#633A68",
};
const HAIRC: Record<Role, string> = {
  architect: "#2B2B33", engineer: "#6B3F2A", qa: "#3A2B29", adversary: "#7A1F2B", sme: "#8C8C94",
};

export const Avatar: React.FC<{ role: Role; size: number; asleep?: boolean }> = ({ role, size, asleep }) => (
  <svg width={size} height={size} viewBox="0 0 36 36">
    <rect width="36" height="36" rx="8" fill={ROLE[role]} />
    <path d="M4 36c1-9 7-13 14-13s13 4 14 13" fill={TORSO[role]} />
    <path d="M11 14c0-9 14-9 14 0v5c0 6-4 8-7 8s-7-2-7-8z" fill="#D9A07D" />
    <path d={HAIR[role]} fill={HAIRC[role]} />
    {asleep ? (
      <>
        <path d="M13.5 18.5q1.5 1 3 0M20.5 18.5q1.5 1 3 0" stroke="#3A2B29" strokeWidth="1" fill="none" strokeLinecap="round" />
        <path d="M17 22.5h2" stroke="#7D4B42" strokeWidth="1.2" strokeLinecap="round" />
      </>
    ) : (
      <>
        <circle cx="15" cy="18" r="1" fill="#3A2B29" />
        <circle cx="22" cy="18" r="1" fill="#3A2B29" />
        <path d="M16 22q2 2 4 0" fill="none" stroke="#7D4B42" strokeWidth="1.2" strokeLinecap="round" />
      </>
    )}
    {role === "architect" && (
      <g stroke="#5865F2" strokeWidth="1.1" fill="none">
        <circle cx="15" cy="18" r="2.8" /><circle cx="22" cy="18" r="2.8" /><path d="M17.8 18h1.4" />
      </g>
    )}
    {role === "engineer" && (
      <>
        <path d="M11 12c0-6 14-6 14 0v1H11z" fill="#EABF3B" />
        <rect x="9" y="12.5" width="18" height="2" rx="1" fill="#D9A441" />
      </>
    )}
    {role === "qa" && (
      <>
        <circle cx="27" cy="27" r="4.2" fill="#F2EDE4" stroke="#168B82" strokeWidth="1.6" />
        <path d="M30 30l3.5 3.5" stroke="#168B82" strokeWidth="2" strokeLinecap="round" />
      </>
    )}
    {role === "adversary" && (
      <path d="M12.5 15l4 1.2M24.5 15l-4 1.2" stroke="#C84455" strokeWidth="1.3" strokeLinecap="round" />
    )}
    {role === "sme" && (
      <>
        <path d="M8 11l10-4 10 4-10 4z" fill="#24212B" />
        <path d="M13 13v3c0 2.5 10 2.5 10 0v-3" fill="none" stroke="#24212B" strokeWidth="1.6" />
      </>
    )}
  </svg>
);

// ---------------------------------------------------------------------------------------------
export const Pill: React.FC<{ color: string; children: React.ReactNode; solid?: boolean; size?: number; style?: React.CSSProperties }> = ({
  color, children, solid, size = 22, style,
}) => (
  <div
    style={{
      display: "inline-flex", alignItems: "center", gap: 8, padding: `${size * 0.28}px ${size * 0.7}px`,
      borderRadius: 999, fontFamily: FONT, fontWeight: 700, fontSize: size,
      color: solid ? C.buttonText : color, background: solid ? color : `${color}22`,
      border: `2px solid ${color}`, whiteSpace: "nowrap", ...style,
    }}
  >
    {children}
  </div>
);

export const Card: React.FC<{ style?: React.CSSProperties; children: React.ReactNode; glow?: string }> = ({ style, children, glow }) => (
  <div
    style={{
      background: C.surface, borderRadius: 22, border: `2px solid ${glow ?? "#4A3C35"}`,
      boxShadow: glow ? `0 0 0 6px ${glow}33, 0 18px 40px #0008` : "0 18px 40px #0006",
      ...style,
    }}
  >
    {children}
  </div>
);

export const Mono: React.FC<{ children: React.ReactNode; color?: string; size?: number; style?: React.CSSProperties }> = ({
  children, color = C.muted, size = 22, style,
}) => <span style={{ fontFamily: MONO, fontSize: size, color, ...style }}>{children}</span>;

/** The heron from the brand logo, as a small mark. */
export const Logo: React.FC<{ size: number }> = ({ size }) => (
  <Img src={staticFile("brand/heronry-logo.png")} style={{ width: size, height: size, borderRadius: size * 0.22 }} />
);

// ---------------------------------------------------------------------------------------------
/**
 * One chapter: the caption column on the left (number, title, captions revealed in turn), the
 * diagram on the right, the chapter's illustration (when the codex art has landed) behind the
 * diagram, and a soft fade in and out.
 */
export const Chapter: React.FC<{
  num: number;
  title: string;
  captions: { at: number; text: React.ReactNode }[];
  art?: string;
  children: React.ReactNode;
}> = ({ num, title, captions, art, children }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const fade = interpolate(frame, [0, 12, durationInFrames - 12, durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const head = useAppear(4);
  const hasArt = Boolean(art && ART_READY);
  // with art: the illustration opens the chapter at full strength (an establishing shot), then
  // dims behind the diagram as it fades in; without art the diagram shows at once
  const artO = interpolate(frame, [0, 10, 40, 64], [0, 1, 1, 0.14], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const zoom = interpolate(frame, [0, 64], [1.06, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const diagram = hasArt ? interpolate(frame, [44, 66], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) : 1;
  return (
    <AbsoluteFill style={{ background: C.bg, opacity: fade, fontFamily: FONT, color: C.text }}>
      {hasArt && (
        <Img
          src={staticFile(`art/${art}`)}
          style={{
            position: "absolute", right: 0, bottom: 0, height: H, opacity: artO,
            transform: `scale(${zoom})`, transformOrigin: "bottom right",
          }}
        />
      )}
      <div style={{ position: "absolute", left: 110, top: 150, width: 640 }}>
        <div
          style={{
            opacity: head, transform: `translateY(${(1 - head) * 24}px)`, color: C.accent,
            fontWeight: 800, fontSize: 26, letterSpacing: 4, textTransform: "uppercase",
          }}
        >
          {String(num).padStart(2, "0")} · Heronry
        </div>
        <div
          style={{
            opacity: head, transform: `translateY(${(1 - head) * 30}px)`, fontSize: 76,
            fontWeight: 800, lineHeight: 1.05, marginTop: 18, letterSpacing: -1,
          }}
        >
          {title}
        </div>
        <div style={{ width: 70, height: 6, borderRadius: 3, background: C.accent, marginTop: 34, opacity: head }} />
        <div style={{ marginTop: 40, display: "flex", flexDirection: "column", gap: 26 }}>
          {captions.map((c, i) => (
            <Caption key={i} at={c.at}>{c.text}</Caption>
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", left: 800, top: 0, right: 0, bottom: 0, opacity: diagram }}>{children}</div>
      <div style={{ position: "absolute", left: 110, bottom: 70, display: "flex", alignItems: "center", gap: 16, opacity: 0.8 }}>
        <Logo size={44} />
        <span style={{ fontWeight: 800, fontSize: 26 }}>Heronry</span>
      </div>
    </AbsoluteFill>
  );
};

const Caption: React.FC<{ at: number; children: React.ReactNode }> = ({ at, children }) => {
  const p = useAppear(at, 20);
  return (
    <div
      style={{
        opacity: p, transform: `translateX(${(1 - p) * -30}px)`, fontSize: 33, lineHeight: 1.35,
        color: C.text, fontWeight: 500,
      }}
    >
      {children}
    </div>
  );
};

/** A highlighted inline term inside a caption. */
export const T: React.FC<{ children: React.ReactNode; c?: string }> = ({ children, c = C.accent }) => (
  <span style={{ color: c, fontWeight: 800 }}>{children}</span>
);
