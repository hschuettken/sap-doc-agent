# CDP Automation Playbook for SAP Datasphere

## Golden Rules

1. **Never cdp_navigate on an unsaved tab.** Datasphere does not auto-save
   open editors. Navigating away without saving silently discards all
   pending changes. Always call the save action (Ctrl+S or the toolbar
   button) and wait for the "Saved" toast before issuing any navigation.

2. **Use Playwright-style selectors, not XPath.** SAP UI5 renders dynamic
   IDs on every page load. Stable selectors are CSS class-based
   (`.sapMButton`, `[data-sap-ui-type]`) or aria-label attributes.

3. **Wait for the busy indicator to clear.** After any save or deploy
   action, poll for the absence of `.sapUiLocalBusyIndicator` before
   proceeding. A 500 ms interval with a 30 s timeout is sufficient for
   most operations.

4. **Tab identity is URL-path based.** Each open object in Datasphere
   occupies a hash-routed URL. Parse `window.location.hash` to determine
   which object is currently focused before issuing key presses.

5. **Deployment vs. Save.** Saving a view persists it in draft state.
   Deployment compiles and activates it for consumers. These are separate
   actions — a saved but undeployed view is invisible to dependent objects.

## Common Failure Modes

- **Stale session**: Datasphere sessions expire after ~2 h of inactivity.
  Detect via a redirect to the login page (`/login?reason=SESSION_EXPIRED`).
- **Conflict on deploy**: Two agents deploying the same object concurrently
  cause a lock error. Serialise deployments with a Redis-backed mutex.
