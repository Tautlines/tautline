import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { GoalReviewSchema } from "./schema";
import { sampleGoalReview } from "./sample-goal-review";

const testDir = dirname(fileURLToPath(import.meta.url));

describe("sampleGoalReview", () => {
  it("satisfies GoalReviewSchema", () => {
    expect(() => GoalReviewSchema.parse(sampleGoalReview)).not.toThrow();
  });

  it("has between 1 and 8 highlight items (fits the hero grid)", () => {
    const n = sampleGoalReview.highlight.items.length;
    expect(n).toBeGreaterThanOrEqual(1);
    expect(n).toBeLessThanOrEqual(8);
  });

  it("every milestone is complete", () => {
    expect(sampleGoalReview.milestones.every((m) => m.status === "complete")).toBe(true);
  });

  it("keeps the release-notes page fixture on the same GoalReview contract", () => {
    const fixturePath = resolve(
      testDir,
      "../../../release-notes-page/data/counter-product-taxonomy.json",
    );
    const pageFixture = JSON.parse(readFileSync(fixturePath, "utf8"));

    expect(() => GoalReviewSchema.parse(pageFixture)).not.toThrow();
  });
});
