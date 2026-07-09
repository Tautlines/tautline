import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT } from "../theme";
import { Kicker, Panel, Rise } from "../ui";

const Stat: React.FC<{ value: string; delay: number; color: string }> = ({ value, delay, color }) => (
  <Rise delay={delay}>
    <Panel style={{ padding: "26px 30px", width: 760 }}>
      <div style={{ fontFamily: FONT, fontSize: 38, fontWeight: 700, color }}>{value}</div>
    </Panel>
  </Rise>
);

export const QualityScene: React.FC<{
  quality: { tests: string; types: string; review: string; discipline: string };
}> = ({ quality }) => (
  <AbsoluteFill style={{ padding: 110, justifyContent: "center" }}>
    <Rise delay={2}>
      <Kicker>Delivered with quality</Kicker>
    </Rise>
    <Rise delay={8} style={{ marginTop: 12 }}>
      <div style={{ fontFamily: FONT, fontSize: 32, color: C.inkMuted }}>
        Every change proven and independently reviewed before it shipped.
      </div>
    </Rise>
    <div style={{ display: "flex", flexDirection: "column", gap: 18, marginTop: 40 }}>
      <Stat value={`✓ ${quality.tests}`} delay={16} color={C.green} />
      <Stat value={`✓ ${quality.types}`} delay={24} color={C.green} />
      <Stat value={`✓ ${quality.review}`} delay={32} color={C.green} />
      <Stat value={`✓ ${quality.discipline}`} delay={40} color={C.yellow} />
    </div>
  </AbsoluteFill>
);
