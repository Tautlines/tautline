import React from "react";
import { AbsoluteFill, Audio, useVideoConfig } from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { C } from "./theme";
import { GoalReview } from "./data/schema";
import { buildScenes, SceneId, TRANSITION_FRAMES } from "./data/scenes";
import { IntroScene } from "./scenes/IntroScene";
import { ShippedScene } from "./scenes/ShippedScene";
import { ShapesScene } from "./scenes/ShapesScene";
import { UsageScene } from "./scenes/UsageScene";
import { QualityScene } from "./scenes/QualityScene";
import { NextScene } from "./scenes/NextScene";
import { OutroScene } from "./scenes/OutroScene";
import { resolveMusicSrc } from "./builtinMusic";

const Bg: React.FC = () => (
  <AbsoluteFill
    style={{ background: `linear-gradient(135deg, ${C.bg2} 0%, ${C.bg} 46%, #fff7e8 100%)` }}
  />
);

const renderScene = (id: SceneId, data: GoalReview): React.ReactNode => {
  switch (id) {
    case "intro":
      return (
        <IntroScene kicker={data.kicker} product={data.product} goalTitle={data.goalTitle} why={data.why} />
      );
    case "shipped":
      return <ShippedScene milestones={data.milestones} />;
    case "shapes":
      return (
        <ShapesScene heading={data.highlight.heading} items={data.highlight.items} image={data.highlight.image} />
      );
    case "usage":
      return <UsageScene usage={data.usage ?? []} />;
    case "quality":
      return <QualityScene quality={data.quality} />;
    case "next":
      return <NextScene next={data.next} nextWhy={data.nextWhy} />;
    case "outro":
      return <OutroScene outro={data.outro} kicker={data.kicker} />;
  }
};

export const IterationReview: React.FC<GoalReview> = (data) => {
  const scenes = buildScenes(data);
  const { durationInFrames, fps } = useVideoConfig();
  const musicSrc = data.musicUrl ? resolveMusicSrc(data.musicUrl, durationInFrames, fps) : null;
  return (
    <AbsoluteFill style={{ background: C.bg }}>
      <Bg />
      {musicSrc ? <Audio src={musicSrc} volume={data.musicVolume ?? 0.18} /> : null}
      <TransitionSeries>
        {scenes.flatMap((scene, i) => {
          const seq = (
            <TransitionSeries.Sequence key={scene.id} durationInFrames={scene.durationInFrames}>
              {renderScene(scene.id, data)}
            </TransitionSeries.Sequence>
          );
          if (i === 0) return [seq];
          const transition = (
            <TransitionSeries.Transition
              key={`t-${scene.id}`}
              presentation={fade()}
              timing={linearTiming({ durationInFrames: TRANSITION_FRAMES })}
            />
          );
          return [transition, seq];
        })}
      </TransitionSeries>
    </AbsoluteFill>
  );
};
