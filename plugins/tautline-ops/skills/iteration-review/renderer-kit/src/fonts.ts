// Deterministic, type-safe font loading (Remotion best-practices: never rely on
// bare system-font strings, they render inconsistently).
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadJetBrains } from "@remotion/google-fonts/JetBrainsMono";

export const { fontFamily: FONT } = loadInter("normal", {
  weights: ["400", "600", "700", "800"],
  subsets: ["latin"],
});

export const { fontFamily: MONO } = loadJetBrains("normal", {
  weights: ["400", "700"],
  subsets: ["latin"],
});
