import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Citation } from "./api";
import { renderMarkdown } from "./markdown";

function draw(text: string, opts?: Parameters<typeof renderMarkdown>[1]) {
  return render(<div data-testid="md">{renderMarkdown(text, opts)}</div>);
}

const CITATION: Citation = {
  n: 1,
  path: "app/main.py",
  start: 10,
  end: 12,
  symbol: null,
  label: "app/main.py:10-12",
};

describe("renderMarkdown — blocks and inline", () => {
  it("renders headings, bold, bullet lists, and fenced code (positive)", () => {
    draw("# Title\n\nIntro **bold** word.\n\n- one\n- two\n\n```\ncode line\n```");
    const md = screen.getByTestId("md");

    // Heading text is wrapped in a <span> inside the heading <div> block.
    expect(within(md).getByText("Title").parentElement?.tagName).toBe("DIV");
    expect(within(md).getByText("bold").tagName).toBe("STRONG");
    expect(within(md).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["one", "two"]);
    // Fenced code preserves its content verbatim inside a <pre>.
    const pre = md.querySelector("pre");
    expect(pre?.textContent).toBe("code line");
    // No raw markdown markers leak into the rendered text.
    expect(md.textContent).not.toMatch(/\*\*|```|(^|\s)# /);
  });

  it("turns [n] tokens into clickable file:line citation buttons that call onCite", () => {
    const onCite = vi.fn();
    draw("See the entrypoint [1].", { citations: [CITATION], onCite });
    const btn = screen.getByRole("button", { name: "main.py:10" });
    btn.click();
    expect(onCite).toHaveBeenCalledWith(CITATION);
  });

  it("leaves a [1] token as plain text when no citation matches (negative)", () => {
    draw("Footnote [1] with no source.", { citations: [], onCite: vi.fn() });
    const md = screen.getByTestId("md");
    expect(md.textContent).toContain("[1]");
    expect(within(md).queryByRole("button")).toBeNull();
  });

  it("renders markdown links; docMode additionally strips benign HTML tags", () => {
    const text = "<p>Follow us on [LinkedIn](https://example.com/x) <br> today.</p>";

    const doc = draw(text, { docMode: true });
    expect(screen.getByRole("link", { name: "LinkedIn" })).toHaveAttribute(
      "href",
      "https://example.com/x",
    );
    // In docMode the <p>/<br> layout tags are stripped, not shown literally.
    expect(screen.getByTestId("md").textContent).not.toMatch(/<\/?p>|<br>/);
    doc.unmount();

    // Outside docMode the link still renders, but raw HTML is left as literal (escaped) text.
    draw(text);
    expect(screen.getByRole("link", { name: "LinkedIn" })).toBeInTheDocument();
    expect(screen.getByTestId("md").textContent).toContain("<p>");
  });

  it("handles empty input without crashing (edge)", () => {
    draw("");
    expect(screen.getByTestId("md").textContent).toBe("");
  });
});
