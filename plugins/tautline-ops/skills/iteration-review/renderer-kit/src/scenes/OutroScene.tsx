import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT } from "../theme";
import { Chip, Rise } from "../ui";

export const OutroScene: React.FC<{
  outro: { headline: string; subhead: string };
  kicker: string;
}> = ({ outro, kicker }) => (
  <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", padding: 140 }}>
    <Rise delay={2}>
      <div style={{ fontFamily: FONT, fontSize: 96, fontWeight: 800, color: C.ink, textAlign: "center" }}>
        {outro.headline}
      </div>
    </Rise>
    <Rise delay={14} style={{ marginTop: 26 }}>
      <div
        style={{
          fontFamily: FONT,
          fontSize: 36,
          lineHeight: 1.4,
          color: C.inkMuted,
          textAlign: "center",
          maxWidth: 1300,
        }}
      >
        {outro.subhead}
      </div>
    </Rise>
    <Rise delay={28} style={{ marginTop: 44 }}>
      <Chip label={kicker} color={C.accent} />
    </Rise>
  </AbsoluteFill>
);
