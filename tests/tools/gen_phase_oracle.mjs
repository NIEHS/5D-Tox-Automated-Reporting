/**
 * gen_phase_oracle.mjs — run the REAL web/js/pool_state.js phase logic headlessly
 * and (1) assert its output matches the hand-authored `expected` values in
 * workflow_phase_cases.json, (2) emit workflow_phase_oracle.json.
 *
 * Why a vm sandbox: pool_state.js is a browser script, not a module. At load it
 * calls AppStore.registerReducer/subscribe and touches `document`/`Alpine`. We
 * run it inside node:vm with minimal stubs for those globals, then reach into the
 * sandbox to pull out the three pure functions we care about:
 *   derivePoolPhase, computeSectionCompleteness, isNodeComplete.
 *
 * This makes the BROWSER CODE ITSELF the source of truth for the port contract:
 * if the JS disagrees with `expected`, this script exits non-zero and names the
 * case — so the human-authored table can't silently drift from the real logic.
 *
 * Usage:  node tests/tools/gen_phase_oracle.mjs
 * Output: tests/fixtures/characterization/workflow_phase_oracle.json
 */

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(__dirname, "..", "..");
const JS_PATH = resolve(REPO, "web", "js", "pool_state.js");
const CASES_PATH = resolve(
  REPO, "tests", "fixtures", "characterization", "workflow_phase_cases.json",
);
const ORACLE_PATH = resolve(
  REPO, "tests", "fixtures", "characterization", "workflow_phase_oracle.json",
);

// --- Minimal browser stubs so pool_state.js loads without a DOM. ---
// The module-load side effects (registerReducer/subscribe, an inline <style>
// injection, a debug overlay) must not throw. We stub just enough surface.
const noop = () => {};
const fakeElement = new Proxy({}, {
  get: (_t, prop) => {
    if (prop === "style") return {};
    if (prop === "classList") return { add: noop, remove: noop };
    return noop;
  },
  set: () => true,
});
const sandbox = {
  console,
  AppStore: { registerReducer: noop, subscribe: noop, dispatch: noop },
  Alpine: undefined,
  document: {
    getElementById: () => null,
    createElement: () => fakeElement,
    head: { appendChild: noop },
    body: { appendChild: noop },
  },
  window: { location: { search: "" } },
};

const src = readFileSync(JS_PATH, "utf8");
// Append an export shim: after the script body runs in the sandbox, copy the
// three pure functions onto a global we can read back out.
const shim = `
;globalThis.__extract = {
  derivePoolPhase,
  computeSectionCompleteness,
  isNodeComplete,
};
`;
const context = vm.createContext(sandbox);
vm.runInContext(src + shim, context, { filename: "pool_state.js" });
const { derivePoolPhase, computeSectionCompleteness, isNodeComplete } =
  context.__extract;

if (typeof derivePoolPhase !== "function"
  || typeof computeSectionCompleteness !== "function"
  || typeof isNodeComplete !== "function") {
  console.error("FATAL: could not extract pure functions from pool_state.js");
  process.exit(2);
}

const cases = JSON.parse(readFileSync(CASES_PATH, "utf8"));

// --- Helpers to normalize JS return types into JSON-comparable plain data. ---
// computeSectionCompleteness returns a Map<string, {..}>; flatten to a plain
// object keyed by platform, dropping nothing.
function completenessMapToObject(map) {
  const out = {};
  for (const [platform, status] of map.entries()) {
    out[platform] = {
      hasToxStudy: status.hasToxStudy,
      hasBm2: status.hasBm2,
      complete: status.complete,
      missing: status.missing,
    };
  }
  return out;
}

function deepEqual(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

const oracle = { derive_phase: [], section_completeness: [], node_complete: [] };
const mismatches = [];

// --- derive_phase ---
for (const c of cases.derive_phase) {
  const got = derivePoolPhase(c.input);
  oracle.derive_phase.push({ name: c.name, input: c.input, output: got });
  if (!deepEqual(got, c.expected)) {
    mismatches.push(`derive_phase/${c.name}: expected ${JSON.stringify(c.expected)}, real JS gave ${JSON.stringify(got)}`);
  }
}

// --- section_completeness ---
for (const c of cases.section_completeness) {
  const got = completenessMapToObject(computeSectionCompleteness(c.input));
  oracle.section_completeness.push({ name: c.name, input: c.input, output: got });
  if (!deepEqual(got, c.expected)) {
    mismatches.push(`section_completeness/${c.name}: expected ${JSON.stringify(c.expected)}, real JS gave ${JSON.stringify(got)}`);
  }
}

// --- node_complete ---
// isNodeComplete(nodeId, completenessMap, documentTree). The map values only
// need `complete` + `missing` for the node logic, but we pass what each case
// supplies. Reconstruct a Map from the case's completeness object.
const tree = cases.document_tree;
for (const c of cases.node_complete) {
  const map = new Map(Object.entries(c.input.completeness));
  const got = isNodeComplete(c.input.nodeId, map, tree);
  const norm = { complete: got.complete, missing: got.missing };
  oracle.node_complete.push({ name: c.name, input: c.input, output: norm });
  if (!deepEqual(norm, c.expected)) {
    mismatches.push(`node_complete/${c.name}: expected ${JSON.stringify(c.expected)}, real JS gave ${JSON.stringify(norm)}`);
  }
}

writeFileSync(ORACLE_PATH, JSON.stringify(oracle, null, 2) + "\n", "utf8");

const total = oracle.derive_phase.length + oracle.section_completeness.length + oracle.node_complete.length;
if (mismatches.length) {
  console.error(`\nORACLE MISMATCH — the hand-authored table disagrees with the real pool_state.js in ${mismatches.length}/${total} case(s):`);
  for (const m of mismatches) console.error("  - " + m);
  console.error("\nThe oracle file was still written (reflecting REAL JS). Fix the `expected` values in workflow_phase_cases.json to match reality, or investigate the JS.");
  process.exit(1);
}
console.log(`OK — real pool_state.js matches all ${total} hand-authored expected values.`);
console.log(`Oracle written: ${ORACLE_PATH}`);
