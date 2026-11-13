import { useEffect, useRef, useState } from "react";
import { api, ChatEvent, ChatMessage, ChatThreadSummary } from "../api";
import { ErrorBox, Spinner, StepProps, WarningBox } from "./shared";

// Session interpretation chat (ADR-0022). A per-session, tool-using assistant:
// the model queries the session database, the generated report and the
// knowledge graph through tools, and every literature claim it makes carries a
// [Sn] token that the server resolves to a real paper — or flags as unresolved.
// Exploratory only: nothing written here becomes report content (ADR-0018).
export function Chat({ dtxsid, state }: StepProps) {
  const [threads, setThreads] = useState<ChatThreadSummary[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  const processed = state?.artifacts?.hasProcessed !== false;

  async function loadThreads(selectFirst = false) {
    if (!dtxsid) return;
    const { threads } = await api.listChatThreads(dtxsid);
    setThreads(threads);
    if (selectFirst && threads.length && !threadId) await openThread(threads[0].id);
  }

  async function openThread(id: string) {
    if (!dtxsid) return;
    const t = await api.getChatThread(dtxsid, id);
    setThreadId(id);
    setMessages(t.messages);
    setProgress([]);
  }

  async function newThread() {
    if (!dtxsid) return;
    const t = await api.createChatThread(dtxsid);
    await loadThreads();
    setThreadId(t.id);
    setMessages([]);
    setProgress([]);
  }

  async function removeThread(id: string) {
    if (!dtxsid) return;
    await api.deleteChatThread(dtxsid, id);
    if (id === threadId) {
      setThreadId(null);
      setMessages([]);
    }
    await loadThreads();
  }

  useEffect(() => {
    setThreadId(null);
    setMessages([]);
    loadThreads(true).catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, progress]);

  async function send() {
    if (!dtxsid || busy) return;
    const text = input.trim();
    if (!text) return;
    let tid = threadId;
    try {
      setError(null);
      if (!tid) {
        const t = await api.createChatThread(dtxsid);
        tid = t.id;
        setThreadId(tid);
      }
      setBusy(true);
      setInput("");
      setMessages((m) => [...m, { role: "user", content: text }]);
      setProgress([]);
      const onEvent = (ev: ChatEvent) => {
        if (ev.event === "thinking") setProgress((p) => [...p, `Thinking (round ${ev.data.round ?? "?"})…`]);
        else if (ev.event === "tool_call") setProgress((p) => [...p, `Calling ${ev.data.tool}: ${summarizeInput(ev.data.input)}`]);
        else if (ev.event === "tool_result") setProgress((p) => [...p, `${ev.data.tool} → ${ev.data.chars} chars`]);
      };
      const result = await api.sendChatMessage(dtxsid, tid, text, onEvent);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: result.answer,
          references: result.references,
          unresolved_citations: result.unresolved_citations,
          tool_trace: result.tool_trace,
          model_used: result.model_used,
        },
      ]);
      setProgress([]);
      await loadThreads();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!dtxsid) return <p className="muted">Select a session first.</p>;

  return (
    <div>
      <h2>Chat</h2>
      <p className="muted">
        Ask about this study's data and its generated report. The assistant answers
        from the session database, the report sections and the knowledge graph via
        tools; literature claims carry [S#] citations resolved to real papers.
        Exploratory only — nothing here becomes report text.
      </p>
      {!processed && (
        <WarningBox warning="This session has not been processed yet: data questions need the query database that Process builds. Report and knowledge-graph questions may still work." />
      )}
      <ErrorBox error={error} />

      <div className="chat-layout">
        <aside className="chat-threads">
          <div className="chat-threads-head">
            <strong>Threads</strong>
            <button className="small" onClick={newThread} disabled={busy}>+ New</button>
          </div>
          {threads.length === 0 && <p className="muted">No threads yet.</p>}
          {threads.map((t) => (
            <div key={t.id} className={"chat-thread" + (t.id === threadId ? " active" : "")}>
              <button className="link" onClick={() => openThread(t.id)} title={t.updated_at}>
                {t.title || "(untitled)"} <span className="muted">· {t.message_count}</span>
              </button>
              <button className="small danger" onClick={() => removeThread(t.id)} title="Delete thread">×</button>
            </div>
          ))}
        </aside>

        <section className="chat-main">
          <div className="chat-messages">
            {messages.length === 0 && !busy && (
              <p className="muted">
                Try: "Which apical endpoints were responsive in males, ordered by BMD?" or
                "What do the most sensitive liver gene sets suggest mechanistically?"
              </p>
            )}
            {messages.map((m, i) => (
              <MessageView key={i} m={m} />
            ))}
            {busy && (
              <div className="chat-progress">
                <Spinner label="Working…" />
                {progress.map((p, i) => (
                  <div key={i} className="muted">{p}</div>
                ))}
              </div>
            )}
            <div ref={bottom} />
          </div>
          <div className="chat-input">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
              }}
              placeholder="Ask a question about this study… (Ctrl/⌘+Enter to send)"
              rows={3}
              disabled={busy}
            />
            <button className="primary" onClick={() => void send()} disabled={busy || !input.trim()}>
              Send
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function summarizeInput(input: unknown): string {
  try {
    const s = JSON.stringify(input ?? {});
    return s.length > 120 ? s.slice(0, 117) + "…" : s;
  } catch {
    return "";
  }
}

function MessageView({ m }: { m: ChatMessage }) {
  const [showTools, setShowTools] = useState(false);
  const unresolved = m.unresolved_citations ?? [];
  return (
    <div className={"chat-msg " + m.role}>
      <div className="chat-role muted">{m.role === "user" ? "You" : "Assistant"}</div>
      <div className="chat-content">{m.content}</div>
      {m.role === "assistant" && (
        <div className="chat-meta">
          {(m.references?.length ?? 0) > 0 && (
            <div className="chat-refs">
              <strong>References</strong>
              <ul>
                {m.references!.map((r) => (
                  <li key={r.token}>
                    [{r.token}] {r.title}
                    {r.venue ? `. ${r.venue}` : ""}
                    {r.year ? `. ${r.year}` : ""}
                    {r.doi ? (
                      <>
                        {" "}
                        <a href={`https://doi.org/${r.doi}`} target="_blank" rel="noreferrer">doi</a>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {unresolved.length > 0 && (
            <WarningBox
              warning={
                `${unresolved.length} citation(s) in this answer do not match any source a tool returned — treat those claims as unsupported:\n` +
                unresolved.map((u) => `${u.token}: ${u.sentence}`).join("\n")
              }
            />
          )}
          {(m.tool_trace?.length ?? 0) > 0 && (
            <div className="chat-tools">
              <button className="link" onClick={() => setShowTools((s) => !s)}>
                {showTools ? "Hide" : "Show"} tool calls ({m.tool_trace!.length})
              </button>
              {showTools && (
                <ol>
                  {m.tool_trace!.map((t, i) => (
                    <li key={i}>
                      <code>{t.tool}</code> {summarizeInput(t.input)}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
