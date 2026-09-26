// The live player (S15 embeds it): the same Main and Hero compositions as the MP4, played in the
// browser through @remotion/player — no video file. Built by scripts/player-build.mjs into player/dist/.
import React from "react";
import { createRoot } from "react-dom/client";
import { Player } from "@remotion/player";
import { staticFile } from "remotion";
import { Main, MAIN_FRAMES } from "../src/Main";
import { Hero, HERO_FRAMES } from "../src/Hero";
import { C, FONT, FPS, H, W } from "../src/theme";

// ?hero plays the 7 s README loop (muted, looping, no controls); the default is the full cut.
const hero = new URLSearchParams(window.location.search).has("hero");

// frame 0 is the fade-in (black), so the unplayed player shows the opening illustration instead
const Poster = () => (
  <img src={staticFile("art/ch1-pool.png")} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
);

const App: React.FC = () => (
  <div style={{ minHeight: "100vh", background: C.bg, color: C.text, fontFamily: FONT, display: "grid", placeItems: "center" }}>
    <div style={{ width: "min(100vw - 32px, 1280px)" }}>
      {hero ? (
        <Player component={Hero} durationInFrames={HERO_FRAMES} fps={FPS} compositionWidth={1200} compositionHeight={630}
          style={{ width: "100%" }} autoPlay loop initiallyMuted />
      ) : (
        <Player component={Main} durationInFrames={MAIN_FRAMES} fps={FPS} compositionWidth={W} compositionHeight={H}
          style={{ width: "100%", borderRadius: 12, overflow: "hidden" }} controls clickToPlay
          acknowledgeRemotionLicense showPosterWhenUnplayed renderPoster={Poster} />
      )}
    </div>
  </div>
);

createRoot(document.getElementById("root")!).render(<App />);
