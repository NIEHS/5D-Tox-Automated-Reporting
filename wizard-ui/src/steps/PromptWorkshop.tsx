import { useEffect, useMemo, useRef, useState } from "react";
import { diffLines, diffWords } from "diff";
import {
  api,
  PromptRun,
  PromptTemplateInfo,
  RenderedPrompt,
  WorkshopMessage,
  WorkshopThreadSummary,
} from "../api";
import { ErrorBox, Spinner, StepProps, WarningBox } from "./shared";

// Prompt workshop: tune how a model-written section is generated. The section's
// prompt is a versioned template (one for every report); the session supplies
// the example. Run it, compare the output with the previous run (and, for a
// published study, with what NIEHS printed), critique it in the chat, take or
// adjust the template change the assistant proposes, and save it as a new
// version. Nothing is saved for you: a version is saved only when you save it.
const SECTION = "summary";

type EditorTab = "edit" | "changes" | "prompt" | "variables";

export function PromptWorkshop({ dtxsid, state }: StepProps) {
  const [info, setInfo] = useState<PromptTemplateInfo | null>(null);
  const [editor, setEditor] = useState("");
  const [base, setBase] = useState<{ version: number; text: string } | null>(null);
  const [tab, setTab] = useState<EditorTab>("edit");
  const [rendered, setRendered] = useState<{ prompt?: RenderedPrompt; error?: string } | null>(null);
  const [runs, setRuns] = useState<PromptRun[]>([]);
  const [runIndex, setRunIndex] = useState(0);
  const [published, setPublished] = useState<{ report: string; paragraphs: string[] } | null>(null);
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);

  const dirty = base !== null && editor !== base.text;
  const run = runs[runIndex] ?? null;
  const previous = runs[runIndex + 1] ?? null;
  const processed = state?.artifacts?.hasProcessed !== false;

  async function loadTemplate(keepEditor = false) {
    const t = await api.getPrompt(SECTION);
    setInfo(t);
    setBase({ version: t.current_version, text: t.template });
    if (!keepEditor) setEditor(t.template);
  }

  async function loadRuns() {
    if (!dtxsid) return;
    const { runs } = await api.listPromptRuns(SECTION, dtxsid);
    setRuns(runs);
    setRunIndex(0);
  }

  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  useEffect(() => {
    setError(null);
    loadTemplate().catch(fail);
    if (dtxsid) {
      loadRuns().catch(fail);
      api.getPublishedSection(SECTION, dtxsid).then(setPublished).catch(() => setPublished(null));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtxsid]);

  // The exact prompt the editor's text would send, refreshed as you type.
  useEffect(() => {
    if (!dtxsid || !editor) return;
    const t = setTimeout(() => {
      api.renderPrompt(SECTION, dtxsid, editor)
        .then((r) => setRendered(r.ok ? { prompt: r.prompt } : { error: r.error }))
        .catch((e) => setRendered({ error: e instanceof Error ? e.message : String(e) }));
    }, 500);
    return () => clearTimeout(t);
  }, [dtxsid, editor]);

  async function doRun() {
    if (!dtxsid) return;
    setBusy("Generating…");
    setError(null);
    try {
      await api.runPrompt(SECTION, dtxsid, dirty ? editor : undefined);
      await loadRuns();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function useRun() {
    if (!dtxsid || !run) return;
    try {
      await api.usePromptRun(SECTION, dtxsid, run.run_id);
      setNotice("Saved as the report's Summary (unapproved). Review and approve it in Sections.");
    } catch (e) {
      fail(e);
    }
  }

  async function saveVersion() {
    if (!dtxsid) return;
    setBusy("Saving…");
    setError(null);
    try {
      const { version } = await api.savePromptVersion(SECTION, editor, rationale, dtxsid, threadId);
      setRationale("");
      await loadTemplate();
      setNotice(`Saved as version ${version}; it is now used for every report.`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function makeCurrent(version: number) {
    try {
      await api.makePromptCurrent(SECTION, version);
      await loadTemplate(dirty);
      setNotice(`Version ${version} is now current.`);
    } catch (e) {
      fail(e);
    }
  }

  async function loadIntoEditor(version: number) {
    try {
      const v = await api.getPromptVersion(SECTION, version);
      setEditor(v.template);
      setTab("edit");
    } catch (e) {
      fail(e);
    }
  }

  if (!dtxsid) return <p className="muted">Select a session first.</p>;

  return (
    <div className="workshop">
      <h2>Prompts — {info?.label ?? "Summary"}</h2>
      <p className="muted">
        The {info?.label ?? "Summary"} is written by a model from the facts the data supports. Its
        prompt is a template used for <strong>every</strong> report; this study is the example. Run
        it, critique the output in the chat, edit the template (or take the assistant's proposal),
        and save a new version. Every run keeps the exact prompt that was sent.
      </p>
      {!processed && <WarningBox warning="Process this session first: the Summary's facts come from its results." />}
      <ErrorBox error={error} />
      {notice && (
        <div className="workshop-notice" onClick={() => setNotice(null)}>
          {notice}
        </div>
      )}

      <OutputPane
        run={run}
        previous={previous}
        published={published}
        runs={runs}
        runIndex={runIndex}
        setRunIndex={setRunIndex}
        busy={busy}
        dirty={dirty}
        onRun={doRun}
        onUse={useRun}
      />

      <div className="workshop-lower">
        <section className="workshop-panel">
          <div className="workshop-tabs">
            {(["edit", "changes", "prompt", "variables"] as EditorTab[]).map((t) => (
              <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                {{ edit: "Template", changes: "Changes", prompt: "Prompt sent", variables: "Variables" }[t]}
              </button>
            ))}
            <span className="muted workshop-base">
              {base ? `editing from version ${base.version}${dirty ? " — unsaved changes" : ""}` : ""}
            </span>
          </div>
          {tab === "edit" && (
            <textarea
              className="workshop-editor"
              value={editor}
              onChange={(e) => setEditor(e.target.value)}
              spellCheck={false}
            />
          )}
          {tab === "changes" && <LineDiff before={base?.text ?? ""} after={editor} />}
          {tab === "prompt" && <PromptView rendered={rendered} />}
          {tab === "variables" && (
            <dl className="workshop-vars">
              {Object.entries(info?.variables ?? {}).map(([k, v]) => (
                <div key={k}>
                  <dt><code>{`{{ ${k} }}`}</code></dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          )}
          {rendered?.error && tab === "edit" && <div className="error-box">{rendered.error}</div>}
          <div className="workshop-save">
            <input
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              placeholder="What this change does, in general terms (no study facts)"
            />
            <button className="primary" onClick={saveVersion} disabled={!dirty || !!busy || !!rendered?.error}>
              Save as new version
            </button>
            <button onClick={() => base && setEditor(base.text)} disabled={!dirty}>
              Discard edits
            </button>
          </div>
          <VersionList info={info} onCurrent={makeCurrent} onLoad={loadIntoEditor} />
        </section>

        <WorkshopChat
          dtxsid={dtxsid}
          editor={editor}
          run={run}
          threadId={threadId}
          setThreadId={setThreadId}
          onAccept={(t, why) => {
            setEditor(t);
            if (why && !rationale) setRationale(why);
            setTab("changes");
          }}
          onError={fail}
        />
      </div>
    </div>
  );
}

function OutputPane(props: {
  run: PromptRun | null;
  previous: PromptRun | null;
  published: { report: string; paragraphs: string[] } | null;
  runs: PromptRun[];
  runIndex: number;
  setRunIndex: (i: number) => void;
  busy: string | null;
  dirty: boolean;
  onRun: () => void;
  onUse: () => void;
}) {
  const { run, previous, published, runs, runIndex, setRunIndex, busy, dirty } = props;
  const [showDiff, setShowDiff] = useState(true);
  const label = (r: PromptRun) =>
    `${r.at.replace("T", " ").slice(0, 16)} · ${r.template_version === null ? "unsaved edit" : `v${r.template_version}`}`;
  return (
    <section className="workshop-panel">
      <div className="workshop-toolbar">
        <button className="primary" onClick={props.onRun} disabled={!!busy}>
          {dirty ? "Run the edited template" : "Run"}
        </button>
        {busy && <Spinner label={busy} />}
        {runs.length > 0 && (
          <select value={runIndex} onChange={(e) => setRunIndex(Number(e.target.value))}>
            {runs.map((r, i) => (
              <option key={r.run_id} value={i}>{label(r)}</option>
            ))}
          </select>
        )}
        {previous && (
          <label className="muted">
            <input type="checkbox" checked={showDiff} onChange={(e) => setShowDiff(e.target.checked)} /> show
            changes from the run before
          </label>
        )}
        <span style={{ flex: 1 }} />
        <button onClick={props.onUse} disabled={!run}>Use this as the Summary</button>
      </div>
      {!run && <p className="muted">No runs yet for this study. Press Run.</p>}
      {run && run.unmatched_numbers.length > 0 && (
        <WarningBox
          warning={`Numbers the model was not given: ${run.unmatched_numbers.join(", ")}. The facts must come from the data — check these.`}
        />
      )}
      {run && (
        <div className={"workshop-columns" + (published ? " three" : "")}>
          <div>
            <h4>This run · {label(run)}</h4>
            <Paragraphs
              paragraphs={run.paragraphs}
              before={showDiff ? previous?.paragraphs : undefined}
              flagged={run.unmatched_numbers}
            />
          </div>
          <div>
            <h4>{previous ? `The run before · ${label(previous)}` : "Facts given to the model"}</h4>
            <Paragraphs paragraphs={previous ? previous.paragraphs : run.draft_paragraphs} />
          </div>
          {published && (
            <div>
              <h4>Published · {published.report}</h4>
              <Paragraphs paragraphs={published.paragraphs} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// Paragraphs, optionally as a word diff against `before`, with flagged numbers marked.
function Paragraphs({ paragraphs, before, flagged = [] }: {
  paragraphs: string[]; before?: string[]; flagged?: string[];
}) {
  if (before) {
    const parts = diffWords(before.join("\n\n"), paragraphs.join("\n\n"));
    return (
      <div className="workshop-text">
        {parts.map((p, i) =>
          p.added ? <ins key={i}>{p.value}</ins> : p.removed ? <del key={i}>{p.value}</del> : <span key={i}>{p.value}</span>
        )}
      </div>
    );
  }
  return (
    <div className="workshop-text">
      {paragraphs.map((p, i) => (
        <p key={i}>{markNumbers(p, flagged)}</p>
      ))}
    </div>
  );
}

function markNumbers(text: string, flagged: string[]) {
  if (!flagged.length) return text;
  const re = new RegExp(`(${flagged.map((n) => n.replace(/[.]/g, "\\.")).join("|")})`, "g");
  return text.split(re).map((s, i) => (flagged.includes(s.replace(/,/g, "")) ? <mark key={i}>{s}</mark> : s));
}

function LineDiff({ before, after, same = "No changes from the version you started from." }: {
  before: string; after: string; same?: string;
}) {
  if (before === after) return <p className="muted workshop-pre">{same}</p>;
  return (
    <pre className="workshop-pre">
      {diffLines(before, after).map((p, i) =>
        p.added ? <ins key={i}>{p.value}</ins> : p.removed ? <del key={i}>{p.value}</del> : <span key={i}>{p.value}</span>
      )}
    </pre>
  );
}

function PromptView({ rendered }: { rendered: { prompt?: RenderedPrompt; error?: string } | null }) {
  if (!rendered) return <p className="muted">Rendering…</p>;
  if (rendered.error) return <div className="error-box">{rendered.error}</div>;
  const p = rendered.prompt!;
  return (
    <div className="workshop-pre">
      <div className="muted">
        model {p.model} · temperature {p.temperature} · max tokens {p.max_tokens}
      </div>
      <h4>System</h4>
      <pre>{p.system}</pre>
      <h4>User</h4>
      <pre>{p.user}</pre>
    </div>
  );
}

function VersionList({ info, onCurrent, onLoad }: {
  info: PromptTemplateInfo | null; onCurrent: (v: number) => void; onLoad: (v: number) => void;
}) {
  if (!info) return null;
  return (
    <details className="workshop-versions" open={info.versions.length > 1}>
      <summary>History ({info.versions.length} version{info.versions.length === 1 ? "" : "s"})</summary>
      <ol reversed>
        {[...info.versions].reverse().map((v) => (
          <li key={v.version}>
            <strong>v{v.version}</strong>
            {v.version === info.current_version && <span className="workshop-current"> current</span>}
            <span className="muted"> {v.at ? v.at.slice(0, 16).replace("T", " ") : ""}</span>
            {v.parent !== null && <span className="muted"> · from v{v.parent}</span>}
            <div>{v.rationale || <span className="muted">(no note)</span>}</div>
            <button className="small" onClick={() => onLoad(v.version)}>Open in editor</button>{" "}
            {v.version !== info.current_version && (
              <button className="small" onClick={() => onCurrent(v.version)}>Make current</button>
            )}
          </li>
        ))}
      </ol>
    </details>
  );
}

function WorkshopChat(props: {
  dtxsid: string;
  editor: string;
  run: PromptRun | null;
  threadId: string | null;
  setThreadId: (id: string | null) => void;
  onAccept: (template: string, rationale: string) => void;
  onError: (e: unknown) => void;
}) {
  const { dtxsid, editor, run, threadId, setThreadId } = props;
  const [threads, setThreads] = useState<WorkshopThreadSummary[]>([]);
  const [messages, setMessages] = useState<WorkshopMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement | null>(null);

  async function loadThreads() {
    const { threads } = await api.listWorkshopThreads(SECTION);
    setThreads(threads);
    return threads;
  }

  async function open(id: string) {
    const t = await api.getWorkshopThread(SECTION, id);
    setThreadId(id);
    setMessages(t.messages);
  }

  useEffect(() => {
    loadThreads()
      .then((ts) => (ts.length && !threadId ? open(ts[0].id) : undefined))
      .catch(props.onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    try {
      let tid = threadId;
      if (!tid) {
        tid = (await api.createWorkshopThread(SECTION)).id;
        setThreadId(tid);
      }
      setBusy(true);
      setInput("");
      setMessages((m) => [...m, { role: "user", content: text }]);
      const turn = await api.sendWorkshopMessage(SECTION, tid, {
        dtxsid, message: text, template: editor, run_id: run?.run_id ?? null,
      });
      setMessages(turn.thread.messages);
      await loadThreads();
    } catch (e) {
      props.onError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="workshop-panel workshop-chat">
      <div className="workshop-toolbar">
        <strong>Critique</strong>
        <select value={threadId ?? ""} onChange={(e) => (e.target.value ? open(e.target.value) : undefined)}>
          {!threadId && <option value="">(new conversation)</option>}
          {threads.map((t) => (
            <option key={t.id} value={t.id}>{t.title || "(untitled)"} · {t.message_count}</option>
          ))}
        </select>
        <button className="small" onClick={() => { setThreadId(null); setMessages([]); }} disabled={busy}>
          + New
        </button>
      </div>
      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="muted">
            Say what is wrong with the output, e.g. "The opening repeats the dose groups" or "Too many
            sentences start with 'The'". The assistant proposes a template change; it is not saved
            until you save it.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={"chat-msg " + m.role}>
            <div className="chat-role muted">{m.role === "user" ? "You" : "Assistant"}</div>
            <div className="chat-content">{m.content}</div>
            {m.proposed_template && (
              <Proposal message={m} editor={editor} onAccept={props.onAccept} />
            )}
          </div>
        ))}
        {busy && <Spinner label="Thinking…" />}
        <div ref={bottom} />
      </div>
      <div className="chat-input">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void send();
          }}
          placeholder="Critique the output… (Ctrl/⌘+Enter to send)"
          rows={3}
          disabled={busy}
        />
        <button className="primary" onClick={() => void send()} disabled={busy || !input.trim()}>
          Send
        </button>
      </div>
    </section>
  );
}

function Proposal({ message, editor, onAccept }: {
  message: WorkshopMessage; editor: string; onAccept: (t: string, rationale: string) => void;
}) {
  const [show, setShow] = useState(true);
  const proposed = message.proposed_template!;
  const same = useMemo(() => proposed === editor, [proposed, editor]);
  return (
    <div className="workshop-proposal">
      <div className="workshop-toolbar">
        <strong>Proposed template change</strong>
        {message.rationale && <span className="muted">— {message.rationale}</span>}
        <span style={{ flex: 1 }} />
        <button className="small" onClick={() => setShow((s) => !s)}>{show ? "Hide" : "Show"}</button>
        <button className="small primary" onClick={() => onAccept(proposed, message.rationale ?? "")} disabled={same}>
          {same ? "In the editor" : "Put in editor"}
        </button>
      </div>
      {message.render_error && <div className="error-box">Does not render: {message.render_error}</div>}
      {show && <LineDiff before={editor} after={proposed} same="The editor already holds this template." />}
    </div>
  );
}
