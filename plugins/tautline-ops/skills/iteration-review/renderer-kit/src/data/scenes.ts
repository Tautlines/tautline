import { GoalReview } from "./schema";

// Base duration (frames @30fps) for each scene id.
export const SCENE_DURATIONS = {
  intro: 210,
  shipped: 210,
  shapes: 300,
  usage: 300, // optional "system in action" scene
  quality: 240,
  next: 270,
  outro: 180,
} as const;

export type SceneId = keyof typeof SCENE_DURATIONS;

export type Scene = { id: SceneId; durationInFrames: number };

// Crossfade length between adjacent scenes (frames). Each transition overlaps
// the two scenes, so it shortens the total by this many frames.
export const TRANSITION_FRAMES = 12;

// Scene order is data-driven: the optional "usage" scene is included only when
// the GoalReview carries screenshots/clips of the system in use.
export const buildScenes = (data: GoalReview): Scene[] => {
  const ids: SceneId[] = ["intro", "shipped", "shapes"];
  if (data.usage && data.usage.length > 0) ids.push("usage");
  ids.push("quality", "next", "outro");
  return ids.map((id) => ({ id, durationInFrames: SCENE_DURATIONS[id] }));
};

export const computeTotalDuration = (
  scenes: readonly { durationInFrames: number }[],
  transitionFrames: number,
): number =>
  scenes.reduce((sum, s) => sum + s.durationInFrames, 0) -
  transitionFrames * Math.max(0, scenes.length - 1);
