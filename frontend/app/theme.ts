// Shared design tokens for the Ariadne UI (warm-paper palette from the prototype).
// Inline styles keep components self-contained and faithful to the design file.

export const C = {
  bg: "#FAF8F4",
  ink: "#26221E",
  muted: "#6B655C",
  faint: "#A39C90",
  faint2: "#B7B0A4",
  line: "#ECE8E1",
  line2: "#E2DDD4",
  accent: "#A4471F",
  panel: "#FFFFFF",
  panelAlt: "#FBF9F5",
} as const;

export const mono = "'IBM Plex Mono', monospace";
export const sans = "'IBM Plex Sans', system-ui, sans-serif";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
