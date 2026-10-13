/**
 * MathText — lightweight LaTeX-to-readable-text converter for TCS NQT questions.
 *
 * Converts:
 *  • [latex]/[late]/[/latex] wrapper tags → stripped
 *  • \frac{a}{b}, \tfrac{a}{b} → (a)/(b)
 *  • a^{expr} → <sup> element for short exponents
 *  • \times → ×, \div → ÷, \pm → ±, \leq → ≤, \geq → ≥ etc.
 *  • $math_expr$ inline math delimiters → content only (when content has \cmd or ^)
 *  • Preserves legitimate $ (currency, code-language operators like "A $ B means…")
 */

"use client";

import React, { Fragment } from "react";

const UNICODE_REPLACEMENTS: [RegExp, string][] = [
  [/\\times/g, "×"],
  [/\\div/g, "÷"],
  [/\\cdot/g, "·"],
  [/\\pm/g, "±"],
  [/\\mp/g, "∓"],
  [/\\leq/g, "≤"],
  [/\\geq/g, "≥"],
  [/\\neq/g, "≠"],
  [/\\approx/g, "≈"],
  [/\\infty/g, "∞"],
  [/\\sqrt\{([^}]+)\}/g, "√($1)"],
  [/\\sqrt/g, "√"],
];

const STRIPPED_COMMANDS = /\\(?:left|right|big[lr]?|Big[lr]?|quad|qquad|,|;|!|\s)/g;

function stripLatexTags(s: string): string {
  return s
    .replace(/\[late\]\s*/gi, "")
    .replace(/\[latex\]\s*/gi, "")
    .replace(/\[\/latex\]/gi, "")
    .replace(/\[\\latex\]/gi, "")
    .replace(/\[\\\/latex\]/gi, "");
}

function convertFracs(s: string): string {
  let prev = "";
  let pass = 0;
  while (s !== prev && pass < 5) {
    prev = s;
    s = s.replace(/\\t?frac\{([^{}]*)\}\{([^{}]*)\}/g, "($1)/($2)");
    pass++;
  }
  return s;
}

function convertExponents(s: string): string {
  return s.replace(/\^\{([^}]*)\}/g, (_m: string, exp: string) => {
    const cleaned = exp.trim();
    if (/^[a-zA-Z0-9+\-*/\s]{1,6}$/.test(cleaned)) {
      return `\x02SUP\x03${cleaned}\x04`;
    }
    return `^(${cleaned})`;
  });
}

function convertSubscripts(s: string): string {
  return s.replace(/_{([^}]*)}/g, (_m: string, sub: string) => `_${sub.trim()}`);
}

function stripInlineMathDelimiters(s: string): string {
  return s.replace(/\$([^$\n]{1,120}?)\$/g, (_m: string, inner: string) => {
    const looksLikeMath = /\\[a-zA-Z]/.test(inner) || /\^|_|\{|\}/.test(inner);
    if (looksLikeMath) return inner;
    return _m;
  });
}

function applyUnicodeReplacements(s: string): string {
  s = s.replace(STRIPPED_COMMANDS, " ");
  for (const [pat, rep] of UNICODE_REPLACEMENTS) {
    s = s.replace(pat, rep);
  }
  s = s.replace(/\\[a-zA-Z]+\b/g, "");
  s = s.replace(/[ \t]{2,}/g, " ");
  return s;
}

export function cleanMathText(raw: string | null | undefined): string {
  if (!raw) return "";
  let s = raw;
  s = stripLatexTags(s);
  s = stripInlineMathDelimiters(s);
  s = convertFracs(s);
  s = convertExponents(s);
  s = convertSubscripts(s);
  s = applyUnicodeReplacements(s);
  return s;
}

interface MathTextProps {
  children: string | null | undefined;
  className?: string;
  inline?: boolean;
}

export function MathText({ children, className = "", inline = false }: MathTextProps) {
  const cleaned = cleanMathText(children);
  const paragraphs = cleaned.split(/\n\n+/);
  const Tag = (inline ? "span" : "div") as React.ElementType;

  return (
    <Tag className={className}>
      {paragraphs.map((para, pIdx) => {
        const lines = para.split("\n");
        return (
          <Fragment key={pIdx}>
            {pIdx > 0 && <span className="block mt-3" />}
            {lines.map((line, lIdx) => (
              <Fragment key={lIdx}>
                {lIdx > 0 && <br />}
                {renderWithSups(line)}
              </Fragment>
            ))}
          </Fragment>
        );
      })}
    </Tag>
  );
}

function renderWithSups(line: string): React.ReactNode {
  const parts = line.split("\x02SUP\x03");
  if (parts.length === 1) return line;
  return parts.map((part, i) => {
    if (i === 0) return part;
    const endIdx = part.indexOf("\x04");
    if (endIdx === -1) return part;
    const supContent = part.slice(0, endIdx);
    const rest = part.slice(endIdx + 1);
    return (
      <Fragment key={i}>
        <sup className="text-[0.75em] font-normal">{supContent}</sup>
        {rest}
      </Fragment>
    );
  });
}
