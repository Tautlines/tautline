import React from "react";
import { AbsoluteFill, Img, spring, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, FONT } from "../theme";
import { Kicker, Panel, Rise } from "../ui";

const resolve = (src: string) => (/^https?:\/\//i.test(src) ? src : staticFile(src));

const ShapeCard: React.FC<{ label: string; index: number; delay: number }> = ({
  label,
  index,
  delay,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - delay, fps, config: { damping: 14, mass: 0.6 } });
  return (
    <Panel
      style={{
        opacity: s,
        transform: `scale(${0.85 + s * 0.15})`,
        padding: "22px 24px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        width: 480,
      }}
    >
      <div
        style={{
          fontFamily: FONT,
          fontSize: 22,
          fontWeight: 800,
          color: C.bg,
          background: C.accent,
          borderRadius: 10,
          width: 40,
          height: 40,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {index + 1}
      </div>
      <div style={{ fontFamily: FONT, fontSize: 28, fontWeight: 600, color: C.ink }}>{label}</div>
    </Panel>
  );
};

// The hero: the user-facing capability this goal enables. Shows an optional
// screenshot of the system alongside the value points.
export const ShapesScene: React.FC<{ heading: string; items: string[]; image?: string }> = ({
  heading,
  items,
  image,
}) => (
  <AbsoluteFill style={{ padding: 90, justifyContent: "center" }}>
    <Rise delay={2}>
      <Kicker>What this enables</Kicker>
    </Rise>
    <Rise delay={8} style={{ marginTop: 14, maxWidth: 1640 }}>
      <div style={{ fontFamily: FONT, fontSize: 34, color: C.inkMuted }}>{heading}</div>
    </Rise>
    {image ? (
      <div style={{ display: "flex", gap: 36, marginTop: 38, alignItems: "center" }}>
        <Rise delay={14} style={{ flex: 1.3 }}>
          <Panel style={{ overflow: "hidden", padding: 0 }}>
            <Img
              src={resolve(image)}
              style={{ width: "100%", aspectRatio: "16 / 9", objectFit: "cover", display: "block" }}
            />
          </Panel>
        </Rise>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14 }}>
          {items.map((label, i) => (
            <ShapeCard key={label} label={label} index={i} delay={18 + i * 6} />
          ))}
        </div>
      </div>
    ) : (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 22, marginTop: 44, maxWidth: 1680 }}>
        {items.map((label, i) => (
          <ShapeCard key={label} label={label} index={i} delay={18 + i * 8} />
        ))}
      </div>
    )}
  </AbsoluteFill>
);
