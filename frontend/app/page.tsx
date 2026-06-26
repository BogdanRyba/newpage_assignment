import { C, mono, sans } from "./theme";

// Phase 0 landing. The full three-screen workspace (ingest → indexing →
// split-view chat + source) is built in Phase 3.
export default function Page() {
  return (
    <div
      style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
        fontFamily: sans,
        background: C.bg,
        color: C.ink,
      }}
    >
      <div style={{ maxWidth: 540 }}>
        <div
          style={{
            fontFamily: mono,
            fontSize: 11,
            letterSpacing: ".22em",
            textTransform: "uppercase",
            color: C.faint,
          }}
        >
          Code documentation assistant
        </div>
        <div style={{ fontSize: 44, fontWeight: 600, letterSpacing: "-0.025em", marginTop: 18 }}>
          Ariadne
        </div>
        <div style={{ fontSize: 16, lineHeight: 1.6, color: C.muted, marginTop: 16 }}>
          Ask questions about a codebase. Every answer cites the exact lines it came from.
        </div>
        <div style={{ fontFamily: mono, fontSize: 12.5, color: C.faint2, marginTop: 28 }}>
          Scaffold up. Workspace lands in Phase 3 — guided by{" "}
          <span style={{ color: C.accent }}>Daedalus</span>.
        </div>
      </div>
    </div>
  );
}
