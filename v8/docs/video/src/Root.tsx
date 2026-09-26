import React from "react";
import { Composition } from "remotion";
import { FPS, H, W } from "./theme";
import { Main, MAIN_FRAMES } from "./Main";
import { Hero, HERO_FRAMES } from "./Hero";

export const Root: React.FC = () => (
  <>
    <Composition id="Main" component={Main} durationInFrames={MAIN_FRAMES} fps={FPS} width={W} height={H} />
    <Composition id="Hero" component={Hero} durationInFrames={HERO_FRAMES} fps={FPS} width={1200} height={630} />
  </>
);
