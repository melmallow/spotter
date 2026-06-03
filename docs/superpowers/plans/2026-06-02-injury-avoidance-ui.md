# Injury Avoidance UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface R28 (joints_loaded filter) in the web UI via a persistent "Injuries to avoid" chip strip and a per-workout override step inside the existing `askGenerate` flow. All changes frontend-only.

**Architecture:** Pure-frontend addition to `src/spotter/web/templates/index.html`. State persists in `sessionStorage['spotter.avoidJoints']` as canonical dataset values; UI displays user-friendly labels. The merged joint set is injected into the outgoing `/chat` POST body only — never shown in the user bubble. A small client-side system line above each bot reply confirms the constraint. No backend changes — the Sonnet generator system prompt already extracts `avoid_joints` from the `(avoid: …)` plain-text prefix via R28's natural-language path.

**Tech Stack:** Vanilla JS in a Flask/FastAPI Jinja template. `sessionStorage` for persistence. No build step, no framework, no frontend test runner — verification is manual UI walkthrough plus `curl | grep` static-markup smoke checks.

**Spec:** `docs/superpowers/specs/2026-06-02-injury-avoidance-ui-design.md`

**Dev server:** `uv run python -m spotter` → `http://127.0.0.1:8000`. Restart the server after every template edit (Jinja templates are loaded at app boot in this project).

**Implementation note vs spec:** The spec's §7 wiring item #8 specifies stripping the `(avoid: …)` prefix from the displayed user bubble with the regex `/^\(avoid: [^)]+\) /`. This plan implements the cleaner equivalent: the JS `text` variable never contains the prefix in the first place — the prefix is concatenated only when building the POST body. Net behavior matches the spec (user bubble shows clean text, POST carries the prefix) and the regex becomes unnecessary defense. No regex needed; nothing to strip.

---

## File Structure

Only one file is touched in this plan:

- **Modify:** `src/spotter/web/templates/index.html` — sole owner of the UI. Adds:
  - One `const JOINTS` near other top-level script constants (after `const ROUTES` at ~line 483).
  - One `<div id="injuries">` host in the right-rail chat aside, immediately above the existing `<div class="composer">` at line 438.
  - One CSS block for `.injuries`, `.injury-chip`, `.injury-add`, `.injury-menu`, `.sys-line`.
  - One JS section mirroring the `Recent logs` / `Saved workouts` pattern at lines 678+ / 734+: `loadInjuries`, `saveInjuries`, `toggleInjury`, `renderInjuries`, `openInjuryMenu`, `closeInjuryMenu`, plus helpers `buildAvoidPrefix`, `displayLabel`, `renderInjuriesLine`, and a new `proceedGenerate` callee for the askGenerate flow.

No other files are touched. No new files are created. No Python tests are added — backend R28 behavior is already covered by `tests/test_generator_empty_search.py:111` and stays unchanged.

---

## Task 1: Strip state, render, persistence

**Files:**
- Modify: `src/spotter/web/templates/index.html`
  - Add HTML host (insert above existing line 438 `<div class="composer">`)
  - Add CSS rules (in the existing `<style>` block)
  - Add `const JOINTS` and the strip's JS functions (after existing `const ROUTES` at ~line 483, and after the existing `// --- Saved workouts ---` block at ~line 734)
  - Add `renderInjuries()` call to init at line 823

This task makes the strip visible, editable, and persistent. No prefix injection yet — that's Task 2.

- [ ] **Step 1: Add `const JOINTS` (single source of truth)**

Locate `const ROUTES = {` (line 483). Immediately above it, add:

```js
  // Canonical joint values come from exercises.json `joints_loaded` field.
  // Labels are lowercase plain-English. Strip stores values; UI shows labels.
  const JOINTS = [
    { value: "shoulder",       label: "shoulder" },
    { value: "hip",            label: "hip" },
    { value: "knee",           label: "knee" },
    { value: "ankle",          label: "ankle" },
    { value: "elbow",          label: "elbow" },
    { value: "wrist",          label: "wrist" },
    { value: "cervical spine", label: "neck" },
    { value: "thoracic spine", label: "upper back" },
    { value: "lumbar spine",   label: "lower back" },
  ];
  const INJURY_KEY = 'spotter.avoidJoints';
```

- [ ] **Step 2: Add the strip's host element**

Locate the right-rail chat aside; find this exact line (currently line 438):

```html
    <div class="composer">
```

Insert this `<div>` immediately before it:

```html
    <div class="injuries" id="injuries"></div>
```

- [ ] **Step 3: Add CSS rules for the strip**

Find the existing `.composer` rule at line 242 (`.composer { padding: 14px 18px 20px; ... }`). Add the following rules immediately above it:

```css
  .injuries { padding: 8px 18px 0; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; position: relative; }
  .injuries .label { color: #5d6b7e; font-size: 12px; margin-right: 4px; }
  .injuries .empty { color: #5d6b7e; font-size: 12px; cursor: pointer; padding: 4px 8px; border-radius: 999px; }
  .injuries .empty:hover { background: rgba(120,145,185,0.10); }
  .injury-chip { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; padding: 3px 6px 3px 9px; border-radius: 999px; background: rgba(120,145,185,0.12); color: #2a3650; }
  .injury-chip .x { cursor: pointer; padding: 0 4px; border: none; background: transparent; color: #5d6b7e; font-size: 14px; line-height: 1; }
  .injury-chip .x:hover { color: #2a3650; }
  .injury-add { cursor: pointer; font-size: 12px; padding: 3px 9px; border-radius: 999px; background: transparent; border: 1px dashed rgba(120,145,185,0.45); color: #2a3650; }
  .injury-add:hover { background: rgba(120,145,185,0.08); }
  .injury-menu { position: absolute; top: 32px; right: 18px; background: #fff; border: 1px solid rgba(120,145,185,0.30); border-radius: 8px; box-shadow: 0 6px 24px rgba(0,0,0,0.08); padding: 4px; z-index: 10; min-width: 140px; }
  .injury-menu button { display: block; width: 100%; text-align: left; padding: 6px 10px; border: none; background: transparent; font-size: 13px; color: #2a3650; cursor: pointer; border-radius: 4px; }
  .injury-menu button:hover { background: rgba(120,145,185,0.10); }
  .injury-menu button:disabled { color: #aaa; cursor: default; }
```

- [ ] **Step 4: Add the strip's JS functions**

Locate the end of the `// --- Saved workouts ---` block (just before line 823's `renderLogs();` init call). Add this entire block immediately above the init calls:

```js
  // --- Injuries to avoid (session-scoped, sessionStorage) --------------------
  let _injuryMenuOpen = false;

  function loadInjuries(){
    try {
      const raw = JSON.parse(sessionStorage.getItem(INJURY_KEY) || '[]');
      const valid = new Set(JOINTS.map(j => j.value));
      const seen = new Set();
      return raw.filter(v => valid.has(v) && !seen.has(v) && seen.add(v));
    } catch { return []; }
  }
  function saveInjuries(arr){
    try { sessionStorage.setItem(INJURY_KEY, JSON.stringify(arr)); }
    catch { /* quota / disabled — fall through to in-memory only */ }
  }
  function displayLabel(value){
    const j = JOINTS.find(j => j.value === value);
    return j ? j.label : value;
  }
  function toggleInjury(value){
    const current = loadInjuries();
    const idx = current.indexOf(value);
    if (idx === -1) current.push(value);
    else current.splice(idx, 1);
    saveInjuries(current);
    renderInjuries();
  }
  function openInjuryMenu(){
    closeInjuryMenu();
    const host = document.getElementById('injuries');
    const taken = new Set(loadInjuries());
    const menu = document.createElement('div');
    menu.className = 'injury-menu';
    menu.id = 'injury-menu';
    menu.innerHTML = JOINTS.map(j => {
      const dis = taken.has(j.value) ? ' disabled' : '';
      return `<button type="button" data-add="${escAttr(j.value)}"${dis}>${esc(j.label)}</button>`;
    }).join('');
    menu.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-add]');
      if (!btn || btn.disabled) return;
      toggleInjury(btn.getAttribute('data-add'));
      closeInjuryMenu();
    });
    host.appendChild(menu);
    _injuryMenuOpen = true;
    // Document-level outside-click: defer until next tick so the opening click
    // itself doesn't close the menu we just opened.
    setTimeout(() => document.addEventListener('click', _injuryOutsideClick), 0);
  }
  function closeInjuryMenu(){
    const m = document.getElementById('injury-menu');
    if (m) m.remove();
    _injuryMenuOpen = false;
    document.removeEventListener('click', _injuryOutsideClick);
  }
  function _injuryOutsideClick(e){
    if (e.target.closest('#injury-menu')) return;
    if (e.target.closest('.injury-add')) return;
    closeInjuryMenu();
  }
  function renderInjuries(){
    const host = document.getElementById('injuries');
    if (!host) return;
    const current = loadInjuries();
    if (current.length === 0) {
      host.innerHTML = `<span class="empty" onclick="openInjuryMenu()">+ Add injuries to avoid</span>`;
      return;
    }
    const chips = current.map(v =>
      `<span class="injury-chip">${esc(displayLabel(v))}`
      + `<button class="x" type="button" data-remove="${escAttr(v)}" aria-label="remove">×</button>`
      + `</span>`).join('');
    host.innerHTML = `<span class="label">Injuries to avoid:</span>${chips}`
      + `<button class="injury-add" type="button" onclick="openInjuryMenu()">+ add</button>`;
    host.querySelectorAll('[data-remove]').forEach(b =>
      b.addEventListener('click', () => toggleInjury(b.getAttribute('data-remove'))));
  }
```

- [ ] **Step 5: Wire `renderInjuries()` into init**

Locate the init block at line 823:

```js
  renderLogs();
  renderWorkouts();
  addBot("Hey — I'm Spotter. Ask what muscles a deadlift works, ...");
```

Add `renderInjuries();` immediately before `addBot(...)`:

```js
  renderLogs();
  renderWorkouts();
  renderInjuries();
  addBot("Hey — I'm Spotter. Ask what muscles a deadlift works, ...");
```

- [ ] **Step 6: Run the dev server and verify static markup**

Start (or restart) the server:

```bash
uv run python -m spotter
```

In a second terminal, smoke-test that the new markup is present:

```bash
curl -s http://127.0.0.1:8000/ | grep -c 'id="injuries"'
curl -s http://127.0.0.1:8000/ | grep -c 'const JOINTS'
curl -s http://127.0.0.1:8000/ | grep -c 'Add injuries to avoid'
```

Expected: each command prints `1`.

- [ ] **Step 7: Manual UI verification**

Open `http://127.0.0.1:8000/` in a browser. Verify in order:

1. The strip area shows the muted text `+ Add injuries to avoid` above the chat input. No chips.
2. Click the muted text. A popover appears listing all 9 joints: `shoulder, hip, knee, ankle, elbow, wrist, neck, upper back, lower back`.
3. Click `knee`. The popover closes. The strip now reads `Injuries to avoid: [ knee × ] [ + add ]`.
4. Reload the page. The `[ knee × ]` chip is still there (sessionStorage). Strip label and `+ add` still present.
5. Click `+ add`. Popover lists 8 joints (knee disabled / grayed). Click `lower back`. Strip now shows `[ knee × ] [ lower back × ] [ + add ]`. Open DevTools Application → Session Storage → confirm `spotter.avoidJoints` = `["knee","lumbar spine"]`.
6. Click the `×` on the `knee` chip. Chip disappears. Storage updates to `["lumbar spine"]`.
7. Click the `×` on the remaining chip. Strip returns to empty state (`+ Add injuries to avoid`). Storage updates to `[]`.
8. Open the popover, click somewhere else in the page (outside the menu). The popover closes.
9. Close the tab and reopen `http://127.0.0.1:8000/`. The strip is empty (sessionStorage semantics confirmed).
10. In DevTools console run `sessionStorage.setItem('spotter.avoidJoints', JSON.stringify(["knee", "elbow joint", "knee"]))` and reload. The strip shows only `[ knee × ]` (bogus value dropped, duplicate deduped).

If any check fails, fix and re-run before committing.

- [ ] **Step 8: Commit**

```bash
git add src/spotter/web/templates/index.html
git commit -m "$(cat <<'EOF'
feat(web): injuries-to-avoid chip strip with sessionStorage

Adds the persistent 'Injuries to avoid' surface above the chat composer.
Stores canonical joint values from exercises.json (e.g., "lumbar spine")
while displaying user-friendly labels ("lower back"). Popover add menu,
per-chip remove, outside-click close, dedup + schema-drift defense on
load. Visible only — no constraint is injected yet (Task 2).
EOF
)"
```

---

## Task 2: Prefix injection on typed-message send + visible trace line

**Files:**
- Modify: `src/spotter/web/templates/index.html`
  - Add JS helpers `buildAvoidPrefix(joints)` and `renderInjuriesLine(joints)`
  - Modify the existing `send(text)` function at line 658 to accept an optional override and inject the prefix into the POST body
  - Add CSS rule for `.sys-line` (the muted trace divider rendered above the bot reply)

After this task, typed messages from the composer automatically carry the strip's joints through to the generator and the chat shows a visible `── Injuries to avoid: knee ──` line above the bot reply.

- [ ] **Step 1: Add the `.sys-line` CSS rule**

Locate the existing `.injuries .empty` rule (added in Task 1). Add this rule immediately after the strip's CSS block:

```css
  .sys-line { margin: 10px 0 6px; display: flex; align-items: center; gap: 8px; color: #5d6b7e; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; }
  .sys-line::before, .sys-line::after { content: ''; flex: 1; height: 1px; background: rgba(120,145,185,0.25); }
```

- [ ] **Step 2: Add helper functions**

Locate the end of the injuries JS block from Task 1 (just before the existing `// --- Saved workouts ---` boundary or just before the init block, whichever is your placement). Add these helpers at the end of the injuries block:

```js
  function buildAvoidPrefix(joints){
    if (!joints || joints.length === 0) return '';
    return `(avoid: ${joints.join(', ')}) `;
  }
  function renderInjuriesLine(joints){
    if (!joints || joints.length === 0) return;
    const labels = joints.map(displayLabel).join(', ');
    const el = document.createElement('div');
    el.className = 'sys-line';
    el.innerHTML = `<span>Injuries to avoid: ${esc(labels)}</span>`;
    log.appendChild(el); scroll();
  }
```

- [ ] **Step 3: Modify `send()` to accept an override and inject the prefix**

Locate the current `send` function at line 658:

```js
  async function send(text){
    addUser(text); input.value = ''; addTyping();
    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, conversation_id: CONVERSATION_ID })
      });
```

Replace with:

```js
  async function send(text, jointsOverride){
    const joints = jointsOverride !== undefined ? jointsOverride : loadInjuries();
    addUser(text); input.value = ''; renderInjuriesLine(joints); addTyping();
    const payloadText = buildAvoidPrefix(joints) + text;
    try {
      const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: payloadText, conversation_id: CONVERSATION_ID })
      });
```

Note: `addUser(text)` is called with the original (unprefixed) text — the user bubble stays clean. The prefix lives only on `payloadText`. The trace line renders after the user bubble and before the typing indicator so the order in the transcript is: user bubble → "Injuries to avoid: …" → typing → bot reply.

- [ ] **Step 4: Restart the server and run smoke checks**

```bash
uv run python -m spotter
```

```bash
curl -s http://127.0.0.1:8000/ | grep -c 'buildAvoidPrefix'
curl -s http://127.0.0.1:8000/ | grep -c 'renderInjuriesLine'
curl -s http://127.0.0.1:8000/ | grep -c 'jointsOverride'
curl -s http://127.0.0.1:8000/ | grep -c 'sys-line'
```

Expected: each prints `1` (or more).

- [ ] **Step 5: Manual UI verification — typed-message path**

1. Open the page. Strip empty. Type `lower body workout` and press Send.
   - Network tab: POST `/chat` body `message` = `"lower body workout"` (no prefix).
   - Chat: user bubble reads `lower body workout`. No `Injuries to avoid:` line. Workout returned normally.
2. Add `knee` to the strip. Type `lower body workout` and Send.
   - Network tab: POST body `message` = `"(avoid: knee) lower body workout"`.
   - Chat: user bubble reads `lower body workout` (prefix not displayed). Above the bot reply: a small muted line `Injuries to avoid: knee`. The returned workout card has no knee-loaded exercises — spot-check by clicking through the exercise names against `exercises.json` (knee should not appear in any `joints_loaded`).
3. Add `lower back` to the strip (now `["knee", "lumbar spine"]`). Type `full body workout` and Send.
   - Network tab: POST body `message` = `"(avoid: knee, lumbar spine) full body workout"`.
   - Chat: bubble reads `full body workout`. System line reads `Injuries to avoid: knee, lower back` (display labels, not canonical values).
4. Clear the strip. Type any message and Send. No prefix, no line.

If any check fails, fix and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/spotter/web/templates/index.html
git commit -m "$(cat <<'EOF'
feat(web): inject (avoid: …) prefix into /chat POSTs and render system line

Typed messages auto-include the strip's joints in the POST body as a
plain-text prefix the Sonnet generator already extracts. The user bubble
displays the original (clean) text; a small system line above the bot
reply confirms the constraint using display labels. No prefix and no
line when the strip is empty.
EOF
)"
```

---

## Task 3: askGenerate override sub-step

**Files:**
- Modify: `src/spotter/web/templates/index.html`
  - Replace the existing `askGenerate()` body (line 616) to make muscle chips call a new `askGenerateInjuries(muscle)` step instead of firing `ask(prompt)` directly
  - Add `askGenerateInjuries(muscle)` — renders the second sub-row pre-checked from the strip
  - Add `proceedGenerate(muscle, jointSet)` — calls `send` with the transient override
  - Add small CSS for the sub-step (checked state and the `Skip`/`Next` buttons)

After this task, the `+ New ↗` flow has two steps: muscle pick → injury pick (pre-checked from strip, toggle for this generate only) → POST with the transient set.

- [ ] **Step 1: Add CSS for the sub-step**

Add the following rules immediately after the `.sys-line` rule added in Task 2:

```css
  .gen-injuries { padding: 8px 0 0; }
  .gen-injuries .row { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
  .gen-injuries .pill { font-size: 12px; padding: 4px 10px; border-radius: 999px; border: 1px solid rgba(120,145,185,0.35); background: transparent; color: #2a3650; cursor: pointer; }
  .gen-injuries .pill.on { background: rgba(0,170,170,0.12); border-color: var(--teal-deep); color: var(--teal-deep); }
  .gen-injuries .actions { display: flex; gap: 6px; justify-content: flex-end; }
  .gen-injuries .actions button { font-size: 13px; padding: 6px 14px; border-radius: 999px; cursor: pointer; border: 1px solid rgba(120,145,185,0.35); background: transparent; color: #2a3650; }
  .gen-injuries .actions .next { background: var(--teal-deep); border-color: var(--teal-deep); color: #fff; }
```

If `--teal-deep` does not resolve in your stylesheet (it should — line 247 uses it), substitute the literal teal color used by the project's existing CSS variable.

- [ ] **Step 2: Replace `askGenerate()` to route through the new sub-step**

Locate the existing `askGenerate` function (line 616). Replace it entirely with:

```js
  function askGenerate(){
    const groups = ['Chest','Back','Legs','Shoulders','Arms','Full body'];
    const el = document.createElement('div');
    el.className = 'msg bot';
    const chipsHtml = groups.map(g =>
      `<button class="chip" data-muscle="${escAttr(g)}">${esc(g)}</button>`).join('');
    el.innerHTML = `<div class="bubble">Which muscle group?</div>`
      + `<div class="chips" style="padding: 8px 0 0;">${chipsHtml}</div>`;
    el.querySelectorAll('[data-muscle]').forEach(b =>
      b.addEventListener('click', () => askGenerateInjuries(b.getAttribute('data-muscle'))));
    log.appendChild(el); scroll();
  }
```

The only behavioral change: muscle chips now carry `data-muscle="<Group>"` instead of `data-ask="Build me a workout for …"`, and the click handler calls `askGenerateInjuries(muscle)` instead of `ask(prompt)`.

- [ ] **Step 3: Add `askGenerateInjuries(muscle)`**

Add this function immediately below the new `askGenerate`:

```js
  function askGenerateInjuries(muscle){
    const transient = new Set(loadInjuries()); // snapshot at render time
    const el = document.createElement('div');
    el.className = 'msg bot';
    const rowHtml = JOINTS.map(j => {
      const on = transient.has(j.value);
      return `<button type="button" class="pill${on ? ' on' : ''}" data-joint="${escAttr(j.value)}">`
        + `${on ? '✓ ' : '+ '}${esc(j.label)}</button>`;
    }).join('');
    el.innerHTML = `<div class="bubble">Any injuries to avoid for this workout?</div>`
      + `<div class="gen-injuries">`
      + `<div class="row">${rowHtml}</div>`
      + `<div class="actions">`
      + `<button type="button" class="skip">Skip</button>`
      + `<button type="button" class="next">Next</button>`
      + `</div></div>`;
    el.querySelectorAll('[data-joint]').forEach(b => {
      b.addEventListener('click', () => {
        const v = b.getAttribute('data-joint');
        if (transient.has(v)) { transient.delete(v); b.classList.remove('on'); b.textContent = '+ ' + displayLabel(v); }
        else { transient.add(v); b.classList.add('on'); b.textContent = '✓ ' + displayLabel(v); }
      });
    });
    const fire = () => proceedGenerate(muscle, Array.from(transient));
    el.querySelector('.skip').addEventListener('click', fire);
    el.querySelector('.next').addEventListener('click', fire);
    log.appendChild(el); scroll();
  }
```

- [ ] **Step 4: Add `proceedGenerate(muscle, joints)`**

Add immediately below `askGenerateInjuries`:

```js
  function proceedGenerate(muscle, joints){
    const prompt = `Build me a workout for ${muscle.toLowerCase()}`;
    send(prompt, joints);
  }
```

Note: `joints` is always an array (possibly empty). `send(text, jointsOverride)` from Task 2 builds the prefix when non-empty, skips the trace line when empty, and never reads the strip in the override path — so the askGenerate flow is fully decoupled from the strip's storage.

- [ ] **Step 5: Restart the server and run smoke checks**

```bash
uv run python -m spotter
```

```bash
curl -s http://127.0.0.1:8000/ | grep -c 'askGenerateInjuries'
curl -s http://127.0.0.1:8000/ | grep -c 'proceedGenerate'
curl -s http://127.0.0.1:8000/ | grep -c 'Any injuries to avoid for this workout'
curl -s http://127.0.0.1:8000/ | grep -c 'data-muscle'
```

Expected: each prints `1` (or more).

- [ ] **Step 6: Manual UI verification — askGenerate path**

1. Empty strip, click `+ New ↗` (which calls `askGenerate()`). Sub-row appears: `Which muscle group?` with 6 chips. Click `Legs`.
   - Next sub-row appears: `Any injuries to avoid for this workout?` with 9 chips all in `+ unchecked` state. Click `Next` (or `Skip`).
   - Network tab: POST body `message` = `"Build me a workout for legs"`. No prefix.
   - Chat: user bubble = `Build me a workout for legs`. No system line. Workout returns.
2. Add `knee` to the strip. Click `+ New ↗` → `Legs`.
   - Sub-row appears with `[ ✓ knee ]` checked and the other 8 chips `+ unchecked`. Click `Next`.
   - Network tab: POST body = `"(avoid: knee) Build me a workout for legs"`.
   - Chat: bubble = `Build me a workout for legs`. System line = `Injuries to avoid: knee`. Workout has no knee exercises.
3. Strip still has `knee`. Click `+ New ↗` → `Legs`. Sub-row pre-checks `knee`. Click `knee` to uncheck (chip flips to `+ knee`). Click `shoulder` to check (chip flips to `✓ shoulder`). Click `Next`.
   - Network tab: POST body = `"(avoid: shoulder) Build me a workout for legs"`. (knee removed, shoulder added — for this generate only.)
   - Chat: bubble = `Build me a workout for legs`. System line = `Injuries to avoid: shoulder`.
   - **Critical:** the strip above the composer still shows `[ knee × ]` only. The override did not mutate the strip.
4. Click `+ New ↗` → `Legs` again. Sub-row again pre-checks `knee` only (sourced from the unchanged strip).
5. With `knee` in the strip, click `+ New ↗` → `Legs` → `Skip` (without changing any chips). Behaves identically to `Next` (POST has `(avoid: knee) ...`, system line shows knee).

If any check fails, fix and re-run.

- [ ] **Step 7: Commit**

```bash
git add src/spotter/web/templates/index.html
git commit -m "$(cat <<'EOF'
feat(web): askGenerate adds per-workout injuries-to-avoid step

After picking a muscle group, the +New flow now shows an 'Any injuries
to avoid for this workout?' sub-row pre-checked from the strip. Toggling
is transient — the strip is read at render time and never written.
Skip and Next both fire proceedGenerate, which calls send with the
override joints so the prefix and system line use the transient set
rather than the persisted strip.
EOF
)"
```

---

## Self-Review

Run this checklist against the spec (`docs/superpowers/specs/2026-06-02-injury-avoidance-ui-design.md`) before handing off:

**1. Spec coverage:**
- §2 Goal "persistent chip strip above composer" → Task 1.
- §2 Goal "new step in askGenerate pre-checked from strip, transient" → Task 3.
- §2 Goal "inject merged canonical set as `(avoid: <values>) <text>`" → Task 2 Step 3 (`buildAvoidPrefix` + `send` modification).
- §2 Goal "render `Injuries to avoid: …` system line, no line when empty" → Task 2 Step 2 (`renderInjuriesLine` returns early when joints is empty).
- §2 Goal "display labels in UI, canonical values stored & injected" → Task 1 (JOINTS const, `displayLabel`, storage holds values) + Task 2 (`buildAvoidPrefix(joints)` joins canonical values; `renderInjuriesLine` maps to labels).
- §2 Non-goals (no backend changes, no severity, no localStorage, no card badges) → no tasks touch those.
- §5 Data model (sessionStorage key, JOINTS shape, dedup, schema-drift filter) → Task 1 Step 1 + Step 4 (`loadInjuries`).
- §6.1 Strip empty state + populated state + popover behavior → Task 1 Step 4 (`renderInjuries`, `openInjuryMenu`, `_injuryOutsideClick`) + Step 7 verification.
- §6.2 askGenerate sub-step pre-checked from strip, toggling transient, Skip+Next both fire → Task 3 Step 3 + Step 4.
- §6.3 Chat trace line silenced when empty → Task 2 Step 2.
- §7 Wiring items 1–9 → all covered across Tasks 1–3.
- §7 #8 (prefix strip from displayed bubble) → handled by the cleaner approach documented in the plan header (`text` never carries the prefix; nothing to strip). Behavior matches.
- §8 Edge cases — all covered:
  - Empty strip + Skip → Task 3 Step 6 #1.
  - Free-text "today knees are fine" with strip set → out of plan's verification scope; relies on existing Sonnet behavior (documented as out-of-scope in spec §8).
  - Strip edit mid-generation → Task 3 Step 6 implicitly (transient set snapshotted at sub-row render).
  - sessionStorage quota → Task 1 Step 4 (`saveInjuries` catches; `loadInjuries` returns `[]`).
  - Unknown joint in storage → Task 1 Step 7 #10 verifies.
  - Send-button keyboard shortcut → unchanged path goes through `send(text)` which uses `loadInjuries()` default → Task 2 Step 5 #2 verifies.
  - Duplicate joint in storage → Task 1 Step 4 `loadInjuries` dedup + Step 7 #10 verifies.
- §9 Testing — manual checks distributed across Tasks 1, 2, 3 verification steps.

**2. Placeholder scan:** No TBDs, no "handle appropriately", no "similar to Task N". Every step has exact code or exact commands.

**3. Type/name consistency:**
- `loadInjuries`, `saveInjuries`, `toggleInjury`, `renderInjuries`, `openInjuryMenu`, `closeInjuryMenu`, `displayLabel`, `buildAvoidPrefix`, `renderInjuriesLine`, `askGenerate`, `askGenerateInjuries`, `proceedGenerate` — consistent across tasks.
- `INJURY_KEY = 'spotter.avoidJoints'` matches spec §5.
- `send(text, jointsOverride)` signature used identically in Task 2 (definition) and Task 3 Step 4 (call site).
- `data-joint`, `data-muscle`, `data-add`, `data-remove` attribute names consistent within their owning blocks.
- CSS class names (`.injuries`, `.injury-chip`, `.injury-add`, `.injury-menu`, `.sys-line`, `.gen-injuries`, `.pill`, `.row`, `.actions`) are unique and used consistently.

Plan is internally consistent and covers the spec.
