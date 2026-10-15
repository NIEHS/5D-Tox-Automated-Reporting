/**
 * The one piece of memory the mocks share about runs: which studies are being
 * processed, and since when. The Process mock writes it; the state and M1's
 * delete mocks read it (a delete is refused while a run is in flight).
 */
export const running = new Map<string, string>()
