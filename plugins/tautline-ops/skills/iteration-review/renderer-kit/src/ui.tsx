import React from "react";
import { Easing, interpolate, useCurrentFrame } from "remotion";
import { C, FONT } from "./theme";

// Fade + rise on enter, relative to a scene-local frame. One normalized 0→1
// progress (crisp ease-out) drives both opacity and translateY.
export const Rise: React.FC<{
  children: React.ReactNode;
  delay?: number;
  dur?: number;
  y?: number;
  style?: React.CSSProperties;
}> = ({ children, delay = 0, dur = 18, y = 28, style }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame - delay, [0, dur], [0, 1], {
    easing: Easing.bezier(0.16, 1, 0.3, 1),
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div
      style={{
        opacity: progress,
        transform: `translateY(${interpolate(progress, [0, 1], [y, 0])}px)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

export const Chip: React.FC<{ label: string; color: string }> = ({ label, color }) => (
  <span
    style={{
      fontFamily: FONT,
      fontSize: 26,
      fontWeight: 600,
      color,
      border: `2px solid ${color}`,
      borderRadius: 8,
      padding: "8px 22px",
      letterSpacing: 0,
    }}
  >
    {label}
  </span>
);

export const Panel: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({
  children,
  style,
}) => (
  <div
    style={{
      background: C.panel,
      border: `1px solid ${C.panelBorder}`,
      borderRadius: 8,
      boxShadow: "0 24px 60px rgba(22,34,51,0.14)",
      ...style,
    }}
  >
    {children}
  </div>
);

export const Kicker: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div
    style={{
      fontFamily: FONT,
      fontSize: 26,
      fontWeight: 700,
      letterSpacing: 0,
      textTransform: "uppercase",
      color: C.accent,
    }}
  >
    {children}
  </div>
);
