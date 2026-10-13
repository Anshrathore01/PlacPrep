"use client";

import katex from "katex";
import "katex/dist/katex.min.css";

type Segment = { value: string; math: boolean; display?: boolean };

/**
 * Matches LaTeX/math patterns in TCS NQT question text.
 * Handles: [late]/[latex] blocks, display/inline math \[/\(, $cmd$ inline,
 * \frac, \tfrac (including incomplete trailing), \sqrt, and bare ^{expr}.
 */
const WRAPPED_MATH = /(\[(?:late|latex)\]\s*[\s\S]*?\[(?:\/latex|\\latex)\]|\\?\[[\s\S]*?\\?\]|\\?\([\s\S]*?\\?\)|\$[^$\n]*\\(?:frac|tfrac|sqrt|times|div|left|right|cdot|alpha|beta)[^$\n]*\$|\\(?:tfrac|frac)\s*\{(?:[^{}]|\{[^{}]*\})*\}\s*\{(?:[^{}]|\{[^{}]*\})*\}|\\(?:tfrac|frac)\{\d+\}\{\d+(?!\})|\\sqrt\s*\{(?:[^{}]|\{[^{}]*\})*\}|\^\{[^}]*\})/gi;

function segmentsFor(source: string): Segment[] {
  const segments: Segment[] = [];
  let cursor = 0;
  for (const match of source.matchAll(WRAPPED_MATH)) {
    const value = match[0];
    const start = match.index ?? 0;
    if (start > cursor) segments.push({ value: source.slice(cursor, start), math: false });
    const display = /^\[(?:late|latex)\]/i.test(value) || /^\\?\[/.test(value);
    const expression = value
      .replace(/^\[(?:late|latex)\]\s*/i, "")
      .replace(/\[(?:\/latex|\\latex)\]$/i, "")
      .replace(/^\\?\[|\\?\]$|^\\?\(|\\?\)$/g, "")
      .replace(/^\$|\$$/g, "")
      .trim();
    segments.push({ value: expression, math: true, display });
    cursor = start + value.length;
  }
  if (cursor < source.length) segments.push({ value: source.slice(cursor), math: false });
  return segments.length ? segments : [{ value: source, math: false }];
}

/** Strip orphan [latex]/[\latex]/[/latex] tags left in plain-text segments. */
function stripOrphanTags(s: string): string {
  return s
    .replace(/\[(?:late|latex)\]/gi, "")
    .replace(/\[\/latex\]/gi, "")
    .replace(/\[\\latex\]/gi, "");
}

function readableLatex(value: string): string {
  let text = stripOrphanTags(value);
  text = text.replace(/\\(?:left|right)\s*/g, "");
  text = text.replace(/\\(?:times|cdot)/g, "×").replace(/\\div/g, "÷");
  text = text.replace(/\\sqrt\s*\{([^{}]*)\}/g, "√($1)");
  text = text.replace(/\\(?:tfrac|frac)\s*\{([^{}]*)\}\s*\{([^{}]*)\}/g, "($1)/($2)");
  text = text.replace(/\^\{([^{}]*)\}/g, "^$1").replace(/\^([A-Za-z0-9])/g, "^$1");
  return text;
}

export function MathText({ text }: { text: string }) {
  return (
    <>
      {segmentsFor(text).map((segment, index) => {
        if (!segment.math) {
          return <span key={index}>{readableLatex(segment.value)}</span>;
        }
        try {
          const expression = segment.value
            .replace(/[–−]/g, "-")
            // Repair incomplete integer fraction missing its closing brace
            .replace(/^\\(?:tfrac|frac)\{(\d+)\}\{(\d+)$/, "\\frac{$1}{$2}");
          const html = katex.renderToString(expression, {
            displayMode: segment.display,
            throwOnError: true,
            trust: false,
            strict: "ignore",
          });
          return (
            <span
              key={index}
              className={segment.display ? "tcs-math-display" : "tcs-math-inline"}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          );
        } catch {
          return <span key={index}>{readableLatex(segment.value)}</span>;
        }
      })}
    </>
  );
}

export function TcsQuestionPrompt({
  number,
  text,
  className = "",
}: {
  number: number | string;
  text: string;
  className?: string;
}) {
  return (
    <section className={className}>
      <h3 className="mb-2 text-sm font-bold uppercase tracking-wider text-indigo-600">
        Question {number}
      </h3>
      <div className="whitespace-pre-wrap break-words text-base font-normal leading-relaxed text-slate-900 sm:text-lg">
        <MathText text={text} />
      </div>
    </section>
  );
}

export function isTcsFullLength(title?: string | null): boolean {
  return Boolean(title?.startsWith("TCS NQT Full Length Paper "));
}
