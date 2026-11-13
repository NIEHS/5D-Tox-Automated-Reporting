import { FrontMatterPerson } from "../api";

// One roster of the report's front matter (Authors, Contributors,
// Collaborators): an ordered list of people.  The report lists a roster as the
// published books do — affiliation by affiliation, and within one by
// contribution (what a group of people did, shared by everyone listed under
// it), in the order first entered — so the order here is the order printed.

interface Props {
  title: string;
  addLabel: string;
  help?: string;
  people: FrontMatterPerson[];
  onChange: (people: FrontMatterPerson[]) => void;
  numbered?: boolean;
  rolePlaceholder?: string;
}

const EMPTY: FrontMatterPerson = { name: "", role: "", affiliation: "", contribution: "" };

export function RosterSection({
  title, addLabel, help, people, onChange, numbered = false,
  rolePlaceholder = "Role (e.g. Study Scientist)",
}: Props) {
  function set(i: number, patch: Partial<FrontMatterPerson>) {
    onChange(people.map((p, k) => (k === i ? { ...p, ...patch } : p)));
  }
  function move(i: number, dir: -1 | 1) {
    const j = i + dir;
    if (j < 0 || j >= people.length) return;
    const next = [...people];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }

  return (
    <section className="config-group">
      <div className="group-heading-row">
        <h3 className="group-heading">{title}</h3>
        <button onClick={() => onChange([...people, { ...EMPTY }])}>{addLabel}</button>
      </div>
      {help && <p className="help" style={{ marginTop: 0 }}>{help}</p>}
      {people.length === 0 && <p className="muted">None yet.</p>}
      {people.map((p, i) => (
        <div key={i} className="roster-row">
          {numbered && <span className="roster-pos">{i + 1}</span>}
          <input placeholder="Full name" value={p.name ?? ""}
                 onChange={(e) => set(i, { name: e.target.value })} />
          <input placeholder={rolePlaceholder} value={p.role ?? ""}
                 onChange={(e) => set(i, { role: e.target.value })} />
          <input placeholder="Affiliation" value={p.affiliation ?? ""}
                 onChange={(e) => set(i, { affiliation: e.target.value })} />
          <input placeholder="Contribution (e.g. Critically reviewed report and results)"
                 value={p.contribution ?? ""}
                 onChange={(e) => set(i, { contribution: e.target.value })} />
          <div className="roster-actions">
            <button onClick={() => move(i, -1)} disabled={i === 0} title="Move up">↑</button>
            <button onClick={() => move(i, 1)} disabled={i === people.length - 1}
                    title="Move down">↓</button>
            <button onClick={() => onChange(people.filter((_, k) => k !== i))}
                    title="Remove">✕</button>
          </div>
        </div>
      ))}
    </section>
  );
}
