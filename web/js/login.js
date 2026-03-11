// login.js — User authentication gate (Cloud Run IAP / dev bypass)
//
// Extracted from main.js.  Contains the login gate IIFE and its helper
// functions (probeAccess, showApp, attemptLogin).  These rely on globals
// defined in state.js (USER_STORAGE_KEY, getStoredUser) and on DOM
// elements present in index.html.  Loaded as a plain <script> tag —
// no module imports needed.

/* ==================================================================
 * Login gate — ALWAYS shown on page load.
 *
 * The login page contains the deployment guide and a username form.
 * The user must click "Sign In" to proceed — the gate is never
 * auto-skipped, even in open mode (local dev) or when a username is
 * already stored in localStorage.  This ensures the guide is always
 * one click away from the user.
 *
 * If the stored user is still valid, the input is pre-filled so the
 * user can just hit Enter.  If the server is in open mode, any
 * non-empty username is accepted.
 * ================================================================== */

(function initLoginGate() {
    const gate         = document.getElementById('login-gate');
    const appContainer = document.getElementById('app-container');
    const input        = document.getElementById('login-username');
    const btn          = document.getElementById('login-submit');
    const errEl        = document.getElementById('login-error');

    /**
     * Try a probe request to see if the current stored user is accepted.
     * Returns true if the server is in open mode or the user is valid.
     */
    async function probeAccess() {
        try {
            const resp = await fetch('/api/admin/sessions/summary');
            return resp.ok;
        } catch {
            return false;
        }
    }

    /**
     * Show the app, hide the login gate.
     */
    function showApp() {
        gate.style.display = 'none';
        appContainer.style.display = '';
    }

    /**
     * Attempt login with the entered username.
     * Makes a probe request with the candidate user — if accepted,
     * stores the username and reveals the app.
     */
    async function attemptLogin() {
        const username = input.value.trim();
        if (!username) {
            errEl.textContent = 'Please enter a username.';
            errEl.style.display = '';
            return;
        }

        // Temporarily store the candidate so the fetch interceptor picks it up
        localStorage.setItem(USER_STORAGE_KEY, username);
        errEl.style.display = 'none';
        btn.disabled = true;
        btn.textContent = 'Checking...';

        const ok = await probeAccess();
        btn.disabled = false;
        btn.textContent = 'Sign In';

        if (ok) {
            showApp();
        } else {
            // Remove the bad username so it doesn't pollute future requests
            localStorage.removeItem(USER_STORAGE_KEY);
            errEl.textContent = 'Username not recognized.';
            errEl.style.display = '';
            input.select();
        }
    }

    btn.addEventListener('click', attemptLogin);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') attemptLogin();
    });

    // On localhost, skip the login gate entirely — no authentication
    // needed for local development.  The server-side ALLOWED_USERS env
    // var is also typically unset locally (open mode).
    const host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
        showApp();
        return;
    }

    // Pre-fill the input with the stored username (if any) so the user
    // can just hit Enter to re-enter.  But always show the gate.
    const stored = getStoredUser();
    if (stored) {
        input.value = stored;
    }

    // Gate is visible by default (no display:none in HTML).  App is
    // hidden by default (display:none in HTML).  User must click Sign In.
    input.focus();
})();
