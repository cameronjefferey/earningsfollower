import { ImageResponse } from "next/og";

export const alt =
  "earningsfollower - priced-in earnings calendar and Drift/Waves trading boards";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px",
          background:
            "radial-gradient(ellipse 90% 60% at 20% -10%, #0c2b22, #05070c 55%)",
          color: "#e8edf7",
          fontFamily: "sans-serif",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 40,
            fontWeight: 700,
            letterSpacing: "-0.02em",
          }}
        >
          <span style={{ color: "#ffffff" }}>earnings</span>
          <span style={{ color: "#5bffc5" }}>follower</span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div
            style={{
              display: "flex",
              fontSize: 62,
              fontWeight: 700,
              lineHeight: 1.05,
              letterSpacing: "-0.03em",
              maxWidth: 900,
              color: "#ffffff",
            }}
          >
            What&apos;s priced in - and what happens after it reports.
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 30,
              color: "#7d8aa3",
              maxWidth: 820,
            }}
          >
            Earnings calendar, peer waves &amp; drift, one morning lean.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            gap: 16,
            fontSize: 24,
            color: "#5bffc5",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          <span>www.earningsfollower.com</span>
        </div>
      </div>
    ),
    { ...size }
  );
}
