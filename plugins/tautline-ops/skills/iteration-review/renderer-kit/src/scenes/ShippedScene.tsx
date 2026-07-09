import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT, MONO } from "../theme";
import { Kicker, Panel, Rise } from "../ui";
import { Milestone } from "../data/schema";

const Row: React.FC<{ m: Milestone; delay: number }> = ({ m, delay }) => (
  <Rise delay={delay}>
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 24,
        padding: "22px 28px",
        borderBottom: `1px solid ${C.panelBorder}`,
      }}
    >
      <div style={{ fontFamily: MONO, fontSize: 28, fontWeight: 700, color: C.accent, width: 86 }}>
        {m.id}
      </div>
      <div style={{ fontFamily: FONT, fontSize: 30, color: C.ink, flex: 1 }}>{m.title}</div>
      <div style={{ fontFamily: MONO, fontSize: 22, color: C.inkMuted, width: 120 }}>{m.pr}</div>
      <div
        style={{
          fontFamily: FONT,
          fontSize: 20,
          fontWeight: 700,
          color: C.green,
          border: `2px solid ${C.green}`,
          borderRadius: 8,
          padding: "4px 14px",
          letterSpacing: 0,
        }}
      >
        SHIPPED
      </div>
    </div>
  </Rise>
);

export const ShippedScene: React.FC<{ milestones: Milestone[] }> = ({ milestones }) => (
  <AbsoluteFill style={{ padding: 110, justifyContent: "center" }}>
    <Rise delay={2}>
      <Kicker>What we shipped</Kicker>
    </Rise>
    <Panel style={{ marginTop: 34, padding: "8px 8px" }}>
      {milestones.map((m, i) => (
        <Row key={m.id} m={m} delay={12 + i * 10} />
      ))}
    </Panel>
  </AbsoluteFill>
);
