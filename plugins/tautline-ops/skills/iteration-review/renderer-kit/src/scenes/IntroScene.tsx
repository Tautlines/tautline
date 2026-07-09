import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT } from "../theme";
import { Chip, Kicker, Rise } from "../ui";

export const IntroScene: React.FC<{
  kicker: string;
  product: string;
  goalTitle: string;
  why: string;
}> = ({ kicker, goalTitle, why }) => (
  <AbsoluteFill style={{ justifyContent: "center", padding: 140 }}>
    <Rise delay={2}>
      <Kicker>{kicker}</Kicker>
    </Rise>
    <Rise delay={10} style={{ marginTop: 26 }}>
      <div
        style={{
          fontFamily: FONT,
          fontSize: 104,
          fontWeight: 800,
          color: C.ink,
          lineHeight: 1.02,
          letterSpacing: 0,
        }}
      >
        {goalTitle}
      </div>
    </Rise>
    <Rise delay={24} style={{ marginTop: 36, maxWidth: 1400 }}>
      <div style={{ fontFamily: FONT, fontSize: 38, lineHeight: 1.4, color: C.inkMuted }}>{why}</div>
    </Rise>
    <Rise delay={40} style={{ marginTop: 44, display: "flex", gap: 16 }}>
      <Chip label="Goal complete" color={C.green} />
      <Chip label="2 milestones" color={C.accent} />
    </Rise>
  </AbsoluteFill>
);
