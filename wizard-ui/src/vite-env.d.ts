/// <reference types="vite/client" />

// Vite's `?url` suffix import: returns the emitted asset's URL as a string.
// Needed for the duckdb-wasm .wasm / worker bundles we self-host (offline).
declare module "*?url" {
  const src: string;
  export default src;
}
