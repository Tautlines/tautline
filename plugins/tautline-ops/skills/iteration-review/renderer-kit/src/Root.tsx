import React from "react";
import { Composition } from "remotion";
import { IterationReview } from "./IterationReview";
import { GoalReviewSchema } from "./data/schema";
import { sampleGoalReview } from "./data/sample-goal-review";
import { buildScenes, computeTotalDuration, TRANSITION_FRAMES } from "./data/scenes";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="IterationReview"
      component={IterationReview}
      schema={GoalReviewSchema}
      // Default = bundled sample; real renders override via `--props=<file>.json`.
      defaultProps={sampleGoalReview}
      fps={30}
      width={1920}
      height={1080}
      // Duration tracks the data: the optional "usage" scene adds time only when
      // the GoalReview carries screenshots/clips.
      calculateMetadata={async ({ props }) => ({
        durationInFrames: computeTotalDuration(buildScenes(props), TRANSITION_FRAMES),
      })}
    />
  );
};
