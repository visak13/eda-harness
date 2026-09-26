// Chapter 7 — the close: the Heronry logo, the tagline and where to download it.
import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";
import { Logo, Pill, useAppear } from "../components/kit";
import { ART_READY } from "../art";

// Tagline from edp8.brand (TAGLINE); kept equal by hand, the brand test covers the app surfaces.
export const TAGLINE = "your agent team, built on decisions, checked before delivery";
// Where to download. The repo URL is settled at the storyboard gate; until then the close card
// names GitHub Releases without a slug.
export const DOWNLOAD = "Download · GitHub Releases";

export const Ch7Close: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const logo = useAppear(8, 12);
  const name = useAppear(22);
  const tag = useAppear(40);
  const dl = useAppear(62);
  const fade = interpolate(frame, [0, 12, durationInFrames - 20, durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT, color: C.text, opacity: fade }}>
      {ART_READY && (
        <Img
          src={staticFile("art/ch1-pool.png")}
          style={{ position: "absolute", right: 0, bottom: 0, width: 1100, opacity: 0.16 * tag }}
        />
      )}
      <div style={{ position: "absolute", left: 0, right: 0, top: 230, display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ transform: `scale(${logo})` }}>
          <Logo size={190} />
        </div>
        <div style={{ fontSize: 150, fontWeight: 800, letterSpacing: -2, marginTop: 20, opacity: name, transform: `translateY(${(1 - name) * 30}px)` }}>
          Heronry
        </div>
        <div style={{ fontSize: 44, color: C.muted, marginTop: 6, opacity: tag, transform: `translateY(${(1 - tag) * 20}px)` }}>
          {TAGLINE}
        </div>
        <div style={{ marginTop: 60, opacity: dl, transform: `scale(${0.8 + 0.2 * dl})` }}>
          <Pill color={C.accent} solid size={34}>{DOWNLOAD}</Pill>
        </div>
        <div style={{ marginTop: 26, fontSize: 24, color: C.muted, letterSpacing: 3, opacity: dl }}>
          OPEN SOURCE · WINDOWS / macOS / LINUX
        </div>
      </div>
    </AbsoluteFill>
  );
};
