# The new interface (`ui/`)

React 19 + TypeScript (strict) + antd 6, served by FastAPI at `/app`
(MODULES.md §5). Read `docs/ui-redesign/MODULES.md` §4 first.

| Command | What it does |
|---|---|
| `npm run dev` | dev server on 127.0.0.1:9511 under `/app/`; `/api` answered by the MSW mocks |
| `VITE_MOCK=0 npm run dev` | same, with `/api` proxied to `VITE_BACKEND` (default `http://127.0.0.1:9510`) |
| `npm test` | Vitest + Testing Library; MSW in Node; an unmocked request fails the test |
| `npm run typecheck` / `npm run lint` / `npm run build` | `tsc`, ESLint (no warnings allowed), production build to `dist/` (no mocks in it) |

## Layout

- `src/api/`: the shared contracts as types (`types.ts`), `ApiError` (`errors.ts`), the typed client
  and the NDJSON reader (`client.ts`). Owned by the orchestrator.
- `src/api/mocks/`: MSW handlers (`handlers.ts`, `browser.ts`, `node.ts`) and **all** fixtures
  (`fixtures/`). Reconcile with `docs/ui-redesign/contracts/state.*.json` here and only here.
- `src/kit/`: the shared kit. `useStudyState` (the only reader of workflow state),
  `useStudyMutation`/`invalidateStudy`, `<Refusal>`, `<ConfirmAct>`, `<Wait>`/`<RunInFlight>`,
  `<VocabField>`, `<IdField>`, `<Pending>`, `<Provenance>`, `<SectionStatus>`, `<ItemList>`,
  `modules.ts` (module ids → routes, titles), `words.ts` (phase and action words).
- `src/shell/`: the frame, the routes, the study frame and overview, module placeholders.
- `src/modules/<m>/`: one per module, owned by it.

## Rules a module follows

- Workflow state only through `useStudyState`; mutations through `useStudyMutation` (re-reads the state).
- Every error is an `ApiError`; render it with `<Refusal>`, never its `message`.
- Destructive acts through `<ConfirmAct>`; long acts through `<Wait>`.
- Facts with a vocabulary through `<VocabField>`; ids through `<IdField>`; missing facts as `<Pending>`.
- Never the word "wizard" in user-facing text (ESLint enforces it).
