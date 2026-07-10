import { describe, it, expect } from "vitest";
import { buildScenes, computeTotalDuration, TRANSITION_FRAMES } from "./scenes";
import { sampleGoalReview } from "./sample-goal-review";

describe("computeTotalDuration", () => {
  it("subtracts one transition overlap per gap between scenes", () => {
    const scenes = [{ durationInFrames: 100 }, { durationInFrames: 100 }, { durationInFrames: 100 }];
    expect(computeTotalDuration(scenes, 15)).toBe(100 * 3 - 15 * 2);
  });

  it("never goes negative for a single scene", () => {
    expect(computeTotalDuration([{ durationInFrames: 50 }], 15)).toBe(50);
  });
});

describe("buildScenes", () => {
  it("omits the usage scene when there is no media", () => {
    const ids = buildScenes({ ...sampleGoalReview, usage: undefined }).map((s) => s.id);
    expect(ids).toEqual(["intro", "shipped", "shapes", "quality", "next", "outro"]);
  });

  it("includes the usage scene right after the hero when media is present", () => {
    const ids = buildScenes({
      ...sampleGoalReview,
      usage: [{ src: "shot.png", caption: "Customer placing an order" }],
    }).map((s) => s.id);
    expect(ids).toContain("usage");
    expect(ids.indexOf("usage")).toBe(ids.indexOf("shapes") + 1);
  });

  it("text-only review runs ~45s at 30fps", () => {
    const total = computeTotalDuration(
      buildScenes({ ...sampleGoalReview, usage: undefined }),
      TRANSITION_FRAMES,
    );
    expect(total / 30).toBeGreaterThan(40);
    expect(total / 30).toBeLessThan(50);
  });
});
