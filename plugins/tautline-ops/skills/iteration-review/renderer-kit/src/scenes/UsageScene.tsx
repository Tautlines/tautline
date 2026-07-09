import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { Video } from "@remotion/media";
import { C, FONT } from "../theme";
import { Kicker, Panel, Rise } from "../ui";
import { MediaShot } from "../data/schema";

const isVideo = (src: string) => /\.(mp4|webm|mov)$/i.test(src);
const isRemote = (src: string) => /^https?:\/\//i.test(src);
const resolve = (src: string) => (isRemote(src) ? src : staticFile(src));

// One screenshot or short clip of the real system in use.
const Shot: React.FC<{ shot: MediaShot; delay: number }> = ({ shot, delay }) => {
  const src = resolve(shot.src);
  return (
    <Rise delay={delay} style={{ flex: 1 }}>
      <Panel style={{ overflow: "hidden", padding: 0 }}>
        <div style={{ width: "100%", aspectRatio: "16 / 9", background: C.bg2 }}>
          {isVideo(shot.src) ? (
            <Video
              src={src}
              muted
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          ) : (
            <Img src={src} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          )}
        </div>
        {shot.caption ? (
          <div style={{ fontFamily: FONT, fontSize: 24, color: C.inkMuted, padding: "18px 22px" }}>
            {shot.caption}
          </div>
        ) : null}
      </Panel>
    </Rise>
  );
};

// "See it in action" — real screenshots/clips of the system. Rendered only when
// the GoalReview supplies `usage` (see buildScenes in data/scenes.ts).
export const UsageScene: React.FC<{ usage: MediaShot[] }> = ({ usage }) => (
  <AbsoluteFill style={{ padding: 100, justifyContent: "center" }}>
    <Rise delay={2}>
      <Kicker>See it in action</Kicker>
    </Rise>
    <div style={{ display: "flex", gap: 28, marginTop: 38, alignItems: "flex-start" }}>
      {usage.map((shot, i) => (
        <Shot key={shot.src} shot={shot} delay={12 + i * 8} />
      ))}
    </div>
  </AbsoluteFill>
);
