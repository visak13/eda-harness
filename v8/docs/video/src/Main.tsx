import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, interpolate, useVideoConfig } from "remotion";
import { C } from "./theme";
import { Ch1Pool } from "./chapters/Ch1Pool";
import { Ch2Broker } from "./chapters/Ch2Broker";
import { Ch2bTeam } from "./chapters/Ch2bTeam";
import { Ch3Wake } from "./chapters/Ch3Wake";
import { Ch4Context } from "./chapters/Ch4Context";
import { Ch5Memory } from "./chapters/Ch5Memory";
import { Ch6Board } from "./chapters/Ch6Board";
import { Ch7Close } from "./chapters/Ch7Close";
import { MUSIC } from "./music";
import TABLE from "./chapters.json";

const COMPONENTS: Record<string, React.FC> = {
  ch1: Ch1Pool, ch2: Ch2Broker, ch2b: Ch2bTeam, ch3: Ch3Wake, ch4: Ch4Context, ch5: Ch5Memory, ch6: Ch6Board, ch7: Ch7Close,
};

/** The chapters in the owner's order (design §4.17, 2b per m-b42de746e3); lengths in src/chapters.json. */
export const CHAPTERS = TABLE.map((c) => ({ ...c, C: COMPONENTS[c.id] }));

export const MAIN_FRAMES = CHAPTERS.reduce((n, c) => n + c.frames, 0);

/** The first frame of each chapter inside Main. */
export const chapterStart = (i: number) => CHAPTERS.slice(0, i).reduce((n, c) => n + c.frames, 0);

export const Main: React.FC = () => {
  const { durationInFrames } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      {CHAPTERS.map((ch, i) => (
        <Sequence key={ch.id} from={chapterStart(i)} durationInFrames={ch.frames} name={ch.id}>
          <ch.C />
        </Sequence>
      ))}
      {MUSIC && (
        <Audio
          src={staticFile(MUSIC)}
          volume={(f) => interpolate(f, [0, 30, durationInFrames - 60, durationInFrames], [0, 0.7, 0.7, 0], {
            extrapolateLeft: "clamp", extrapolateRight: "clamp",
          })}
        />
      )}
    </AbsoluteFill>
  );
};
