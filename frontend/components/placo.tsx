"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bot, Send, X, Sparkles, AlertCircle } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { usePlaco } from "./providers";
import { PlacoMessage } from "./placo-message";

export function PlacoPanel() {
  const { context } = usePlaco();
  const sessionKey = context.requestKey ?? `${context.mode || "default"}:${context.attemptId ?? ""}:${context.questionId ?? ""}`;
  return <PlacoPanelSession key={sessionKey} />;
}

function PlacoPanelSession() {
  const { open, closePanel, context } = usePlaco();
  const { questionId, attemptId, mode } = context;

  const [message, setMessage] = useState(context.request || "");
  const [conversationId, setConversationId] = useState<number>();
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; content: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [retryText, setRetryText] = useState("");
  const sentRequestRef = useRef("");

  const isActiveAssessment = mode === "ACTIVE_ASSESSMENT";

  const send = useCallback(async (textToSend?: string) => {
    const text = (textToSend ?? message).trim();
    if (!text || busy) return;

    setBusy(true);
    setError("");
    setRetryText(text);

    // Only append user message if it is not already the last pending message in the thread
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "user" && last.content === text) {
        return prev;
      }
      return [...prev, { role: "user", content: text }];
    });
    setMessage("");

    try {
      const result = await api.placo({
        message: text,
        question_id: questionId,
        attempt_id: attemptId,
        conversation_id: conversationId,
      });
      setConversationId(result.conversation_id);
      setMessages((prev) => [...prev, { role: "assistant", content: result.message }]);
      setRetryText("");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setError("Please sign in to chat with Placo.");
      } else {
        setError(cause instanceof Error ? cause.message : "Placo is temporarily unavailable.");
      }
    } finally {
      setBusy(false);
    }
  }, [attemptId, busy, conversationId, message, questionId]);

  useEffect(() => {
    if (!open || !context.request) return;
    const requestKey = `${context.requestKey ?? ""}:${attemptId ?? ""}:${questionId ?? ""}:${context.request}`;
    if (sentRequestRef.current === requestKey) return;
    sentRequestRef.current = requestKey;
    void send(context.request);
  }, [open, context.request, context.requestKey, attemptId, questionId, send]);

  const starterSuggestions = isActiveAssessment
    ? [
        "Give me a hint for this question.",
        "Explain the underlying concept.",
        "What strategy should I use here?",
      ]
    : mode === "RESULT"
    ? [
        "Explain why this was the correct answer.",
        "What mistake is common in this type of question?",
        "How can I prepare better for this concept?",
      ]
    : [
        "Explain database normalization with an example.",
        "How should I prepare for technical campus interviews?",
        "What are the top DSA patterns I should master?",
      ];

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-sm transition-opacity"
      onClick={closePanel}
    >
      <section
        onClick={(e) => e.stopPropagation()}
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-slate-200 bg-white shadow-2xl max-sm:bottom-0 max-sm:top-auto max-sm:h-[85vh] max-sm:max-w-none max-sm:rounded-t-3xl max-sm:border-t"
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-indigo-600 text-white shadow-sm">
              <Bot size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-900">Placo</h2>
                <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold text-indigo-700">
                  AI Assistant
                </span>
              </div>
              <p className="text-xs text-slate-500">Placement doubt & concept companion</p>
            </div>
          </div>
          <button
            onClick={closePanel}
            aria-label="Close Placo"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            <X size={18} />
          </button>
        </header>

        {/* Active Assessment Notice */}
        {isActiveAssessment && (
          <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-5 py-3 text-xs leading-5 text-amber-900">
            <AlertCircle size={16} className="shrink-0 mt-0.5 text-amber-600" />
            <p>
              Placo can provide conceptual guidance during an active assessment, but cannot reveal the answer.
            </p>
          </div>
        )}

        {/* Chat Messages */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {messages.length === 0 && (
            <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-5 text-sm text-slate-600">
              <div className="flex items-center gap-2 font-semibold text-slate-900">
                <Sparkles size={16} className="text-indigo-600" />
                How can I help you today?
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {isActiveAssessment
                  ? "Ask for problem-solving hints or foundational formulas."
                  : mode === "RESULT"
                  ? "Ask for explanations of questions from this completed assessment."
                  : "Ask conceptual questions, aptitude formulas, or interview strategy."}
              </p>
              <div className="mt-4 flex flex-col gap-2">
                {starterSuggestions.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => send(prompt)}
                    className="rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-left text-xs font-medium text-slate-700 hover:border-indigo-300 hover:bg-indigo-50/40 hover:text-indigo-900 transition"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((item, idx) => (
            <div
              key={idx}
              className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 shadow-sm ${
                item.role === "user"
                  ? "ml-auto bg-indigo-600 text-white"
                  : "bg-slate-100 text-slate-800"
              }`}
            >
              <PlacoMessage content={item.content} />
            </div>
          ))}

          {busy && (
            <div className="flex items-center gap-2 text-xs font-medium text-slate-400">
              <span className="h-2 w-2 animate-ping rounded-full bg-indigo-600" />
              Placo is thinking…
            </div>
          )}

          {error && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              <p>{error}</p>
              {retryText && <button type="button" disabled={busy} onClick={() => void send(retryText)} className="mt-2 font-semibold underline disabled:opacity-50">Try again</button>}
            </div>
          )}
        </div>

        {/* Input */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="border-t border-slate-200 bg-white p-4"
        >
          <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-2 focus-within:border-indigo-500 focus-within:bg-white focus-within:ring-1 focus-within:ring-indigo-500">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              maxLength={2000}
              rows={2}
              placeholder="Ask a doubt or concept…"
              className="min-h-10 flex-1 resize-none bg-transparent p-2 text-sm outline-none text-slate-900 placeholder:text-slate-400"
            />
            <button
              type="submit"
              disabled={busy || !message.trim()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-indigo-600 text-white shadow-sm disabled:opacity-40 hover:bg-indigo-700 transition"
              aria-label="Send message"
            >
              <Send size={16} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
