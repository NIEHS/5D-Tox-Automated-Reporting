/**
 * app_store.js — Minimal reactive state store for 5dToxReport.
 *
 * Centralizes all UI state into a single object organized by "slices"
 * (pool, sections, genomics, export).  Replaces 20+ global booleans,
 * 14 Alpine ready flags, and scattered DOM manipulations with a single
 * dispatch/subscribe pattern.
 *
 * Architecture:
 *   - State tree: plain JS object, one key per slice
 *   - Reducers: pure functions (oldState, verb, payload) -> newState
 *   - Subscribers: callbacks notified when their slice changes
 *   - dispatch(action, payload): triggers reducer + notifies subscribers
 *
 * Usage:
 *   AppStore.registerReducer('pool', poolReducer);
 *   AppStore.subscribe('pool', renderPoolControls);
 *   AppStore.dispatch('pool.transition', 'VALIDATED');
 *
 * This file must be loaded before any slice definitions (pool_state.js)
 * and before any code that calls dispatch/subscribe.
 *
 * Fits into the project as: the foundation layer that pool_state.js,
 * section_state.js (Phase 2), visibility_state.js (Phase 3), and
 * lifecycle_state.js (Phase 4) build on top of.
 */

// eslint-disable-next-line no-unused-vars
const AppStore = (() => {
    // ---------------------------------------------------------------
    // State tree — each top-level key is a "slice."
    // Slices are populated by registerReducer(); initial values come
    // from the reducer's handling of an 'init' verb.
    // ---------------------------------------------------------------
    const state = {};

    // ---------------------------------------------------------------
    // Subscribers: slice name -> Set of callbacks.
    // Each callback receives the slice state as its only argument.
    // ---------------------------------------------------------------
    const subs = {};

    /**
     * Subscribe to changes on a slice.
     *
     * The callback fires immediately with the current slice state
     * (so the subscriber doesn't need a separate "read initial state"
     * path), and again on every subsequent dispatch that changes
     * the slice.
     *
     * Returns an unsubscribe function.
     *
     * @param {string} slice — Slice name (e.g., 'pool')
     * @param {Function} fn  — Callback receiving the slice state
     * @returns {Function} Unsubscribe function
     */
    function subscribe(slice, fn) {
        if (!subs[slice]) subs[slice] = new Set();
        subs[slice].add(fn);
        // Fire immediately so subscriber gets current state without
        // needing a separate initialization path.
        if (state[slice] !== undefined) fn(state[slice]);
        return () => subs[slice].delete(fn);
    }

    /**
     * Notify all subscribers of a slice.
     * Called internally after a reducer produces new state.
     *
     * @param {string} slice — Which slice changed
     */
    function notify(slice) {
        for (const fn of (subs[slice] || [])) {
            try {
                fn(state[slice]);
            } catch (e) {
                console.error(`[AppStore] subscriber error on ${slice}:`, e);
            }
        }
    }

    /**
     * Dispatch an action to the store.
     *
     * Action format: 'slice.verb' (e.g., 'pool.transition').
     * The reducer for the slice receives (currentState, verb, payload)
     * and returns new state.  If state changed, subscribers are notified.
     *
     * @param {string} action  — 'slice.verb' format
     * @param {*}      payload — Data for the reducer
     */
    function dispatch(action, payload) {
        const dot = action.indexOf('.');
        if (dot === -1) {
            console.warn(`[AppStore] invalid action format: ${action} (expected 'slice.verb')`);
            return;
        }
        const slice = action.substring(0, dot);
        const verb = action.substring(dot + 1);

        if (!reducers[slice]) {
            console.warn(`[AppStore] no reducer for slice: ${slice}`);
            return;
        }

        const prev = state[slice];
        state[slice] = reducers[slice](prev, verb, payload);
        // Always notify — let subscribers decide if they need to re-render.
        // This is simpler than deep-equality checks and the renderers are
        // cheap (just setting a few DOM properties).
        notify(slice);
    }

    /**
     * Read current state of a slice (or the whole tree).
     *
     * @param {string} [slice] — Slice name, or omit for the full tree
     * @returns {*} The slice state, or the entire state tree
     */
    function getState(slice) {
        return slice ? state[slice] : state;
    }

    // ---------------------------------------------------------------
    // Reducers: slice name -> reducer function.
    // A reducer is: (currentState, verb, payload) -> newState
    // ---------------------------------------------------------------
    const reducers = {};

    /**
     * Register a reducer for a slice and set its initial state.
     *
     * The reducer is called immediately with (undefined, 'init', undefined)
     * to produce the initial state.  This mirrors Redux's convention
     * where reducers define their own defaults.
     *
     * @param {string}   slice — Slice name (e.g., 'pool')
     * @param {Function} fn    — Reducer: (state, verb, payload) -> newState
     */
    function registerReducer(slice, fn) {
        reducers[slice] = fn;
        // Produce initial state by calling the reducer with undefined.
        // The reducer should return a default state when it sees undefined.
        state[slice] = fn(undefined, 'init', undefined);
    }

    return { subscribe, dispatch, getState, registerReducer };
})();
