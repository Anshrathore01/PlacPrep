import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PlacoMessage } from "./placo-message";

describe("Placo markdown rendering", () => {
  it("renders headings, emphasis, paragraphs, and ordered and unordered lists", () => {
    const html = renderToStaticMarkup(createElement(PlacoMessage, { content: "## Normalization\n\n**Redundancy** and *integrity*.\n\n- First\n- Second\n\n1. Step one\n2. Step two" }));
    expect(html).toContain("<h2");
    expect(html).toContain("<strong>Redundancy</strong>");
    expect(html).toContain("<em>integrity</em>");
    expect(html).toContain("<ul");
    expect(html).toContain("<ol");
  });

  it("renders GFM tables, code blocks, and math without losing content", () => {
    const html = renderToStaticMarkup(createElement(PlacoMessage, { content: "| A | B |\n| - | - |\n| 1 | 2 |\n\n```python\n  print(1)\n```\n\nInline $x^2$" }));
    expect(html).toContain("<table");
    expect(html).toContain("print(1)");
    expect(html).toContain("katex");
    expect(html).toContain("overflow-x-auto");
  });

  it("keeps ordinary text and does not render raw HTML or unsafe links", () => {
    const html = renderToStaticMarkup(createElement(PlacoMessage, { content: "Plain text stays readable.\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert%281%29)" }));
    expect(html).toContain("Plain text stays readable.");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("href=\"javascript:");
  });
});
