// Minimal single-line syntax highlighter, ported from the Ariadne design prototype.
// Returns an HTML string (rendered via dangerouslySetInnerHTML). Self-contained — no deps.

const PY_KW = new Set(
  ("def class return if elif else for while in not and or import from as with try except finally " +
    "raise None True False async await yield lambda pass continue break is del global nonlocal assert")
    .split(" "),
);
const TS_KW = new Set(
  ("const let var function return if else for while import from export default interface type new " +
    "extends implements public private async await class enum void null undefined true false this " +
    "typeof keyof readonly")
    .split(" "),
);

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function highlight(line: string, lang: string): string {
  const isPy = lang.startsWith("py");
  const kw = isPy ? PY_KW : TS_KW;
  const cmt = isPy ? "#" : "//";
  const span = (c: string, t: string, it = false) =>
    `<span style="color:${c};${it ? "font-style:italic;" : ""}">${t}</span>`;

  let out = "";
  let i = 0;
  const n = line.length;
  while (i < n) {
    const ch = line[i];
    if (line.startsWith(cmt, i)) {
      out += span("#A8A195", esc(line.slice(i)), true);
      break;
    }
    if (ch === '"' || ch === "'" || ch === "`") {
      let j = i + 1;
      while (j < n) {
        if (line[j] === "\\") {
          j += 2;
          continue;
        }
        if (line[j] === ch) {
          j++;
          break;
        }
        j++;
      }
      out += span("#5E7A52", esc(line.slice(i, j)));
      i = j;
      continue;
    }
    if (/[A-Za-z_$]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[A-Za-z0-9_$]/.test(line[j])) j++;
      const w = line.slice(i, j);
      out += kw.has(w) ? span("#5B6E8C", esc(w)) : esc(w);
      i = j;
      continue;
    }
    if (/[0-9]/.test(ch)) {
      let j = i + 1;
      while (j < n && /[0-9._a-fxA-FX]/.test(line[j])) j++;
      out += span("#9A6B33", esc(line.slice(i, j)));
      i = j;
      continue;
    }
    out += esc(ch);
    i++;
  }
  return out;
}
