import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT } from "../theme";
import { Kicker, Panel, Rise } from "../ui";

export const NextScene: React.FC<{
  next: { title: string; blurb: string }[];
  nextWhy: string;
}> = ({ next, nextWhy }) => (
  <AbsoluteFill style={{ padding: 110, justifyContent: "center" }}>
    <Rise delay={2}>
      <Kicker>What's next</Kicker>
    </Rise>
    <div style={{ display: "flex", gap: 28, marginTop: 38 }}>
      {next.map((n, i) => (
        <Rise key={n.title} delay={12 + i * 10} style={{ flex: 1 }}>
          <Panel style={{ padding: "30px 34px", height: "100%", borderColor: C.yellow }}>
            <div style={{ fontFamily: FONT, fontSize: 36, fontWeight: 800, color: C.ink }}>
              {n.title}
            </div>
            <div style={{ fontFamily: FONT, fontSize: 28, lineHeight: 1.4, color: C.inkMuted, marginTop: 14 }}>
              {n.blurb}
            </div>
          </Panel>
        </Rise>
      ))}
    </div>
    <Rise delay={40} style={{ marginTop: 40, maxWidth: 1600 }}>
      <div style={{ fontFamily: FONT, fontSize: 30, color: C.inkFaint }}>{nextWhy}</div>
    </Rise>
  </AbsoluteFill>
);
