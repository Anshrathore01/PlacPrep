import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

export function PlacoMessage({ content }: { content: string }) {
  return (
    <div className="placo-markdown min-w-0 break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: ({ children }) => <h1 className="mb-3 mt-4 text-lg font-bold leading-snug first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mb-2 mt-4 text-base font-bold leading-snug first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mb-2 mt-3 text-sm font-bold leading-snug first:mt-0">{children}</h3>,
          p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          ul: ({ children }) => <ul className="mb-3 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
          ol: ({ children }) => <ol className="mb-3 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
          blockquote: ({ children }) => <blockquote className="my-3 border-l-2 border-indigo-300 pl-3 text-slate-600">{children}</blockquote>,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer" className="text-indigo-700 underline underline-offset-2">{children}</a>,
          pre: ({ children }) => <pre className="my-3 max-w-full overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs leading-5 text-slate-100">{children}</pre>,
          code: ({ className, children, ...props }) => <code className={`${className || "rounded bg-slate-200/70 px-1 py-0.5 text-[0.92em]"}`} {...props}>{children}</code>,
          table: ({ children }) => <div className="my-3 max-w-full overflow-x-auto"><table className="w-full border-collapse text-left text-xs">{children}</table></div>,
          th: ({ children }) => <th className="border border-slate-300 bg-slate-200 px-2 py-1.5 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border border-slate-200 px-2 py-1.5 align-top">{children}</td>,
          hr: () => <hr className="my-3 border-slate-300" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
