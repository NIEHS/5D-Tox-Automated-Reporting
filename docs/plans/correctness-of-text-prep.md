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

Read as: an assertion is held to the same standard whoever made it. A sentence
a model wrote and a sentence a person typed, or brought back from Word, are both
assertions to be checked. (If it also means that both a model and a person do
the checking, the note of Scott's words already implies it: the model flags, a
person decides.) To be confirmed when the effort starts.

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
- **Nothing** records an assertion as a thing of its own, what it rests on, or
  whether anyone found it supported.

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
