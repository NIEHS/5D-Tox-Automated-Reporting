# Correctness of the report's text: notes before a concentrated effort

**Written 2026-11-19. Not a design.** The maintainer said this is to be
developed in a concentrated effort of its own; this note keeps what was said and
what is known, so that effort starts from it.

## 1. What the maintainer said (2026-11-19)

- "if any text is altered that contradicts the data should not be allowed."
- "meaning should be considered a separate class of 'correctness'. we'll need to
  develop this in a concentrated effort. it's not yet clear what the mechanism
  will be, except for what Scott said about assertions. this should include
  assertions by AI *and* human."

## 2. Two classes of correctness

| Class | The question | Who can decide it |
|---|---|---|
| **Agreement with the data** | Does the text say a value, dose, sex, species, organ, route, unit or direction that the data does not? | A rule. So it can be refused, or made impossible where the text is built from the data. |
| **Meaning** | Is what the text asserts supported: by this study's data, or by the paper it cites? | Judgment. No rule decides it. The mechanism is open. |

The first class is described in `user-system-plan.md` §10a. This note is about
the second.

## 3. What Scott Auerbach said about assertions (meeting of 2026-11-18)

- For each citation, look at the statement before it and ask whether the cited
  paper supports it; flag the ones that do not for a person.
- Possibly several AIs set against each other.
- An overall integrity check apart from the code's tests: an AI reviewer and
  hard-coded evaluations, saying what can and cannot be recapitulated from the
  data.
- Prefer the paper that observed a finding over a review that repeats it (not a
  great worry).
- Made-up DOIs and wholly unrelated citations he considers solved.

## 4. "By AI and human"

Confirmed by the maintainer (2026-11-19), both ways:

- an assertion is held to the same standard whoever **made** it: a sentence a
  model wrote and a sentence a person typed, or brought back from Word;
- a model and a person both do the **checking**.

## 5. What exists today

- **Citations:** `narrative/citation_check.py` checks that a citation in the
  text points at a source that was supplied to the model. It does not ask
  whether the source supports the sentence.
- **The knowledge base:** 4,961 papers with 9,727 extracted claims
  (`baseline-2026-05`), each claim tied to its paper. The natural thing to hold
  a sentence against.
- **What each model-written section was given:** the gene-level interpretations
  record the text and the papers offered to the model; the Background and the
  Summary record their prompts. So for model text, what an assertion could rest
  on is known.
- **Who wrote a section:** recorded per version (the program, a model, a
  person, returned from outside). Not per sentence.
- **The pre-flight checklist** already asks for it by hand: "Each interpretive
  claim: traced to a table or a cited paper" (toxicology; genomics), and
  "Statements that something is not known: checked".
- **A sentence of the report is only text today.** Take "X is metabolized by
  CYP2E1 [3]" in a Background. The software holds the section's text and its
  reference list, and knows that [3] was among the papers given to the model.
  It holds no record that says: this is a statement the report makes; it rests
  on paper [3]; someone checked whether [3] says so; the answer was yes. So
  there is nothing to list, count, flag or sign off sentence by sentence. A
  claim of the knowledge base, by contrast, is such a record (§5a).

## 5a. Claims and assertions (the maintainer, 2026-11-19; a first sketch, not a design)

The maintainer: assertions and the knowledge base's "claims" are related (from
the discussion with Scott); "perhaps we can flesh out claims and assertions as
entities that are created by a set of rules and prompts."

**What a claim is today.** A statement a model extracted from a paper, kept as
one row: the paper and the sentence (`paper_claims`; 9,727 claims over 4,080
papers of `baseline-2026-05`). It is made by one prompt of the crawl query
(`crawl_queries/baseline.yaml`: "list of key scientific findings or
conclusions, each as a concise statement"). It records nothing else: not what
the claim is about, not where in the paper it stands, not its kind. Some have
lost their subject ("The neurotoxic effects are dose-dependent").

**The sketch: three entities.**

| Entity | What it is | Made by |
|---|---|---|
| **Claim** | what a **source** says. Two kinds of source: a paper, and this study's own data ("ALT was increased at ≥250 ppm; BMD 157.8 ppm"). | from a paper: a prompt, when the knowledge base is built (exists, thin). From the data: a rule, at Process (the results sentences are already built this way, from a template and the values). |
| **Assertion** | what the **report** says: one statement of its text, written by a model or a person. | a rule finds the statements (sentences, citation marks, the places a template fills from data); a prompt says which of them assert something and of what kind (a finding of this study, a statement about the literature, an interpretation, a statement that something is not known). |
| **Support** | the link from an assertion to the claims it rests on, with a verdict (supported, not supported, not checked), who gave it (a model, a person) and when. | a rule where the link is explicit (a citation mark points at a paper's claims; a filled place points at its value); a prompt proposes links and verdicts where it is not; a person confirms or overrules. |

**How the two classes of §2 fall out of it.** Agreement with the data is an
assertion held against claims from the data: a rule decides it. Meaning is an
assertion held against claims from papers, or an interpretation that goes beyond
any one claim: a model proposes, a person decides.

**What the sketch leaves open:**

- Claims from papers are too thin today to hold an assertion against: no
  subject, no passage. The prompt that makes them would have to ask for more
  (what the claim is about, the passage it comes from), and many come from
  abstracts only.
- An assertion's identity when the text is edited: is it found again, or made
  anew and checked again?
- How fine: every sentence is many records for a long report; only sentences
  with a citation or an interpretation is fewer and needs the prompt to choose.
- An assertion that rests on nothing recorded (general knowledge).

## 6. Questions for the effort (none answered)

1. What is an assertion: every sentence, every sentence with a citation, every
   interpretive sentence? Who or what marks them?
2. What may an assertion rest on: a table or value of this study, a cited
   paper, another section of the report, general knowledge?
3. What standings can it have (supported, not supported, not checked, disputed),
   and who may set each: a model, a person with the right role, both in turn?
4. What does a standing do: hold the section from sign-off, close the publish
   gate, or only show?
5. When is it checked again: when the sentence changes, when the data changes,
   when the knowledge base changes?
6. Where does it meet the user system: who asserted, who verified, and whether
   verifying is part of signing off or a grant of its own.
7. What a model may be shown to check it (unpublished study data goes to the
   institute's gateway only).
