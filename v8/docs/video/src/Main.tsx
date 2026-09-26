import React from "react";
import { AbsoluteFill, Audio, Sequence, staticFile, interpolate, useVideoConfig } from "remotion";
import { C } from "./theme";
import { Ch1Pool } from "./chapters/Ch1Pool";
import { Ch2Broker } from "./chapters/Ch2Broker";
import { Ch3Wake } from "./chapters/Ch3Wake";
import { Ch4Context } from "./chapters/Ch4Context";
import { Ch5Memory } from "./chapters/Ch5Memory";
import { Ch6Board } from "./chapters/Ch6Board";
import { Ch7Close } from "./chapters/Ch7Close";
import { MUSIC } from "./music";

/** The seven chapters, in the owner's order (design §4.17), with their lengths in frames at 30 fps. */
export const CHAPTERS = [
  { id: "ch1", C: Ch1Pool, frames: 360 },
  { id: "ch2", C: Ch2Broker, frames: 330 },
  { id: "ch3", C: Ch3Wake, frames: 345 },
  { id: "ch4", C: Ch4Context, frames: 375 },
  { id: "ch5", C: Ch5Memory, frames: 360 },
  { id: "ch6", C: Ch6Board, frames: 405 },
  { id: "ch7", C: Ch7Close, frames: 210 },
] as const;

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
