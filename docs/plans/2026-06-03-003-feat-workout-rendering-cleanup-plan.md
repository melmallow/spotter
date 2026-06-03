# Workout Rendering Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the chat-rendering duplication when a workout is generated and convert the My Workouts panel from full-detail cards to compact rows with a click-to-detail modal.

**Architecture:** Two coordinated changes. Backend: two paragraphs added to `GENERATOR_SYSTEM_PROMPT` — populate `notes` as a short title, keep the post-tool narrative brief and table-free. Frontend: replace `renderSavedWorkout` (full-detail card) with `renderSavedWorkoutRow` (compact row), extract its body into `renderWorkoutDetail`, add `openWorkoutModal` / `closeWorkoutModal` for an overlay that contains the detail + actions. Two helpers (`titleOf`, `relTime`) support both.

**Tech Stack:** Python 3.14, LangGraph, FastAPI (no backend changes beyond a prompt edit), vanilla JS + CSS in `src/spotter/web/templates/index.html`.

**Spec:** `docs/brainstorms/2026-06-03-workout-rendering-cleanup.md`

---

## File Structure

**Modified files:**
- `src/spotter/agents/generator.py` — two paragraphs added to `GENERATOR_SYSTEM_PROMPT` (no other code changes).
- `src/spotter/web/templates/index.html` — three localized edits within the existing `<script>` block + a small CSS addition for the modal:
  - **CSS:** new rules for `.workout-row`, `.workout-row .x`, `.modal-backdrop`, `.modal-card`, `.modal-card .x`.
  - **JS helpers:** `titleOf(w)`, `relTime(iso)`, `renderWorkoutDetail(w)` (extracted from existing `renderSavedWorkout` body).
  - **JS render:** replace `renderSavedWorkout(it)` with `renderSavedWorkoutRow(it)`; `renderWorkouts()` keeps its empty-state stub path but maps non-empty items through the row renderer; row click + remove + modal-action wiring.
  - **JS modal:** `openWorkoutModal(id)`, `closeWorkoutModal()`, Escape-key handler.

**Files this plan deliberately leaves alone:**
- `src/spotter/hub.py`, `src/spotter/web/app.py`, `src/spotter/schemas.py` — backend workout-payload plumbing already shipped in commit `2b85bce`.
- All test files — no automated tests for this change (UI-only behavior; prompt changes don't affect stubbed LLM tests). Manual browser walkthrough in Task 3.

---

## Task 1: Tighten `GENERATOR_SYSTEM_PROMPT`

**Files:**
- Modify: `src/spotter/agents/generator.py` (the `GENERATOR_SYSTEM_PROMPT` constant)

**Why this task is small:** The two prompt additions land in one constant; no tests change because the existing `test_generator_empty_search` stubs the LLM via `FakeStructuredChatModel` (responses are scripted; prompt content doesn't affect them).

- [ ] **Step 1: Read the current prompt**

Open `src/spotter/agents/generator.py`. The current `GENERATOR_SYSTEM_PROMPT` constant begins around line 23. Read it in full so you know where the new paragraphs slot in (you'll insert them in two specific places).

- [ ] **Step 2: Add the `notes` instruction to the existing workflow list**

In `GENERATOR_SYSTEM_PROMPT`, find the existing line that begins:

```
3. If results are good, call `build_workout` with selected exercise IDs grouped into
   warmup, main, and cooldown blocks with sets/reps/rest.
```

Append a new sentence to step 3 so it becomes:

```
3. If results are good, call `build_workout` with selected exercise IDs grouped into
   warmup, main, and cooldown blocks with sets/reps/rest. ALWAYS populate
   `build_workout`'s `notes` field with a short (4–8 word) descriptive title
   (e.g., "Arms-focused: biceps and triceps", "30-min upper push", "Lower-body
   strength block"). This appears as the saved-workout title in the user's list.
```

- [ ] **Step 3: Replace step 4 with the brief-narrative instruction**

In the same `GENERATOR_SYSTEM_PROMPT`, find:

```
4. After tools complete, write a brief response describing the workout in plain language.
```

Replace it with:

```
4. After tools complete, write a BRIEF response (2–3 sentences) describing the
   workout's intent and any equipment the user will need. Do NOT list exercises
   in tables or bullet points — the UI renders the structured workout below
   your text, so duplicating the exercise list would clutter the chat.
```

- [ ] **Step 4: Run the test suite to confirm nothing regressed**

Run: `uv run pytest -v`
Expected: 26 passed. The existing generator test stubs the LLM, so prompt text changes don't affect it.

- [ ] **Step 5: Commit**

```bash
git add src/spotter/agents/generator.py
git commit -m "$(cat <<'EOF'
feat(generator): tighten prompt — short notes title + brief narrative

Two additions to GENERATOR_SYSTEM_PROMPT:
- Step 3: require a 4–8 word descriptive title in `notes`. Surfaces as
  the saved-workout title in the My Workouts list (replaces the
  generic "Generated workout" string for every workout).
- Step 4: brief 2–3 sentence narrative, no exercise tables. The
  structured workout card already renders the exercise list; the LLM
  duplicating it as markdown tables was producing the chat-duplication
  the user reported.

Tests stub the LLM via FakeStructuredChatModel, so prompt text changes
do not affect them; 26/26 still green.
EOF
)"
```

---

## Task 2: Rewire the My Workouts panel — compact rows + modal

**Files:**
- Modify: `src/spotter/web/templates/index.html` (CSS additions + JS helpers + JS render + JS modal)

This task bundles CSS, helpers, render rewrite, and modal because they interlock — splitting them into separate commits would leave the panel in a broken state mid-task. All edits are within the single `index.html` file.

- [ ] **Step 1: Add CSS for the compact row and the modal**

In `src/spotter/web/templates/index.html`, find the existing `.workout` CSS rules (search for `.workout .x` — that block of rules begins around line 144 and ends around line 169). Immediately AFTER that block of `.workout`-related rules, INSERT the following CSS:

```css
  .workout-row {
    background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius-sm);
    padding: 12px 14px; position: relative; cursor: pointer; transition: .15s;
    display: flex; flex-direction: column; gap: 2px;
  }
  .workout-row:hover { border-color: var(--text-faint); background: var(--surface-2); }
  .workout-row .x {
    position: absolute; top: 8px; right: 8px;
    width: 26px; height: 26px; border: 0; background: transparent; cursor: pointer;
    color: var(--text-faint); border-radius: 7px; display: grid; place-items: center; transition: .15s;
  }
  .workout-row .x:hover { background: var(--surface-3); color: var(--text); }
  .workout-row .x svg { width: 13px; height: 13px; }
  .workout-row .row-title { font-size: 14.5px; font-weight: 700; letter-spacing: -0.01em; padding-right: 32px; }
  .workout-row .row-sub { color: var(--text-dim); font-size: 12.5px; }

  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(0,0,0,0.45);
    display: grid; place-items: center; z-index: 100; padding: 24px;
  }
  .modal-card {
    background: var(--surface); border-radius: var(--radius);
    max-width: 560px; width: 100%; max-height: 88vh; overflow-y: auto;
    padding: 24px 26px 22px; position: relative;
    box-shadow: 0 24px 60px rgba(0,0,0,0.35);
  }
  .modal-card .x {
    position: absolute; top: 12px; right: 12px;
    width: 30px; height: 30px; border: 0; background: transparent; cursor: pointer;
    color: var(--text-faint); border-radius: 8px; display: grid; place-items: center; transition: .15s;
  }
  .modal-card .x:hover { background: var(--surface-2); color: var(--text); }
  .modal-card .x svg { width: 15px; height: 15px; }
  .modal-card .m-title { font-size: 18px; font-weight: 700; letter-spacing: -0.01em; padding-right: 36px; }
  .modal-card .m-sub { color: var(--text-dim); font-size: 13px; margin-top: 2px; }
  .modal-card .m-divider { height: 1px; background: var(--line); margin: 14px 0; }
```

- [ ] **Step 2: Add the `titleOf` and `relTime` helpers**

In the same file, find the existing `prescOf(it)` function (around line 550, immediately above `renderWorkoutCard`). Immediately AFTER `prescOf`, INSERT the two new helpers:

```javascript
  function titleOf(w){
    const notes = ((w && w.notes) || '').trim();
    return notes || 'Generated workout';
  }
  function relTime(iso){
    const then = new Date(iso).getTime();
    if (isNaN(then)) return '';
    const sec = Math.max(1, Math.floor((Date.now() - then) / 1000));
    if (sec < 60) return `${sec}s`;
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h`;
    const d = Math.floor(hr / 24);
    return `${d}d`;
  }
```

- [ ] **Step 3: Extract the detail body into `renderWorkoutDetail`**

In the same file, find the existing `renderSavedWorkout(it)` function (currently around line 776). It contains a block-by-block exercise-rendering loop that the modal will reuse.

Immediately ABOVE `renderSavedWorkout`, INSERT a new `renderWorkoutDetail(w)` function that contains JUST the detail body (no card chrome, no action row, no title — the modal supplies those):

```javascript
  function renderWorkoutDetail(w){
    const blocks = Array.isArray(w && w.blocks) ? w.blocks : [];
    if (!blocks.length) return '';
    let body = '';
    blocks.forEach(b => {
      const items = b.items || [];
      if (!items.length) return;
      body += `<div><div class="w-bname">${esc(b.name || 'block')}</div>`;
      items.forEach(ex => {
        const nm = esc(ex.exercise_name || 'Exercise')
          + (ex.side_note ? ` <span class="w-side">(${esc(ex.side_note)})</span>` : '');
        const swap = escAttr(`Swap ${ex.exercise_name || 'this exercise'} for a different exercise`);
        body += `<div class="w-ex">`
          + `<div><div class="w-name">${nm}</div><div class="w-pres">${esc(prescOf(ex))}</div></div>`
          + `<button class="wc-swap" data-modal-swap="${swap}">swap</button>`
          + `</div>`;
      });
      body += `</div>`;
    });
    return `<div class="w-blocks">${body}</div>`;
  }
```

NOTE: Uses `data-modal-swap=` (not `data-ask=`) so the modal's event delegation can close the modal AND send the prompt — see Step 5.

- [ ] **Step 4: Replace `renderSavedWorkout` with `renderSavedWorkoutRow`**

In the same file, REPLACE the entire `renderSavedWorkout(it)` function (the one you just inserted `renderWorkoutDetail` above) with the new compact-row renderer:

```javascript
  function renderSavedWorkoutRow(it){
    const w = it.workout || {};
    const blocks = Array.isArray(w.blocks) ? w.blocks : [];
    let count = 0; blocks.forEach(b => count += (b.items || []).length);
    const names = blocks.map(b => b.name).filter(Boolean).join('/');
    const time = relTime(it.saved_at);
    const sub = `${count} ex · ${esc(names || 'workout')}${time ? ` · ${time} ago` : ''}`;
    const removeIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6 18 18M18 6 6 18"/></svg>`;
    return `<div class="workout-row" data-open="${escAttr(it.id)}">`
      + `<button class="x" data-remove="${escAttr(it.id)}" aria-label="Remove">${removeIcon}</button>`
      + `<div class="row-title">${esc(titleOf(w))}</div>`
      + `<div class="row-sub">${sub}</div>`
      + `</div>`;
  }
```

- [ ] **Step 5: Add the modal open/close functions**

In the same file, immediately AFTER the new `renderSavedWorkoutRow` you just added, INSERT the modal control:

```javascript
  let _modalEscapeHandler = null;

  function openWorkoutModal(id){
    closeWorkoutModal();
    const it = loadWorkouts().find(x => x.id === id);
    if (!it) { console.warn('openWorkoutModal: workout not found', id); return; }
    const w = it.workout || {};
    const blocks = Array.isArray(w.blocks) ? w.blocks : [];
    let count = 0; blocks.forEach(b => count += (b.items || []).length);
    const names = blocks.map(b => b.name).filter(Boolean).join('/');
    const sub = `${count} ex · ${esc(names || 'workout')}`;
    const closeIcon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6 18 18M18 6 6 18"/></svg>`;
    const startIcon = `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`;

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `<div class="modal-card" role="dialog" aria-modal="true">`
      + `<button class="x" data-modal-close="1" aria-label="Close">${closeIcon}</button>`
      + `<div class="m-title">${esc(titleOf(w))}</div>`
      + `<div class="m-sub">${sub}</div>`
      + `<div class="m-divider"></div>`
      + renderWorkoutDetail(w)
      + `<div class="m-divider"></div>`
      + `<div class="w-row">`
      + `<button class="w-start" data-modal-ask="Start this workout">${startIcon}Start</button>`
      + `<button class="w-log" data-modal-ask="Log all the exercises from this workout">Log all</button>`
      + `</div>`
      + `</div>`;

    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) closeWorkoutModal();
    });
    backdrop.querySelectorAll('[data-modal-close]').forEach(b =>
      b.addEventListener('click', closeWorkoutModal));
    backdrop.querySelectorAll('[data-modal-ask]').forEach(b =>
      b.addEventListener('click', () => {
        const prompt = b.getAttribute('data-modal-ask');
        closeWorkoutModal();
        ask(prompt);
      }));
    backdrop.querySelectorAll('[data-modal-swap]').forEach(b =>
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const prompt = b.getAttribute('data-modal-swap');
        closeWorkoutModal();
        ask(prompt);
      }));

    _modalEscapeHandler = (e) => { if (e.key === 'Escape') closeWorkoutModal(); };
    document.addEventListener('keydown', _modalEscapeHandler);

    document.body.appendChild(backdrop);
  }

  function closeWorkoutModal(){
    const existing = document.querySelector('.modal-backdrop');
    if (existing) existing.remove();
    if (_modalEscapeHandler) {
      document.removeEventListener('keydown', _modalEscapeHandler);
      _modalEscapeHandler = null;
    }
  }
```

- [ ] **Step 6: Rewire `renderWorkouts()` to use the new row + open handler**

In the same file, find the existing `renderWorkouts()` function (currently around line 807). REPLACE it with:

```javascript
  function renderWorkouts(){
    const wrap = document.getElementById('workouts');
    const items = loadWorkouts();
    if (!items.length){
      wrap.className = '';
      wrap.innerHTML = STUB_WORKOUT_HTML;
      return;
    }
    wrap.className = 'workouts';
    wrap.innerHTML = items.map(renderSavedWorkoutRow).join('');
    wrap.querySelectorAll('[data-remove]').forEach(b =>
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        removeWorkout(b.getAttribute('data-remove'));
      }));
    wrap.querySelectorAll('[data-open]').forEach(row =>
      row.addEventListener('click', () => openWorkoutModal(row.getAttribute('data-open'))));
  }
```

The notable change vs the existing version: `data-remove` handlers now call `event.stopPropagation()` so clicking the × does not also trigger the row's open-modal handler.

- [ ] **Step 7: Restart the server and smoke-test**

If the dev server is running, restart it (it serves `index.html` fresh per request, so a hard refresh in the browser is sufficient — no need to restart Python unless you also edited `generator.py`):

If you did Task 1 in the same branch/commit sequence, restart the server:

```bash
lsof -ti:8000 2>/dev/null | xargs kill 2>/dev/null; sleep 1
uv run python -m spotter &
sleep 2
curl -sf -o /dev/null http://127.0.0.1:8000/ && echo "ready"
```

Hard refresh the browser (Cmd-Shift-R). Open the dev tools console — expect no JS errors on page load.

- [ ] **Step 8: Run the test suite — nothing should have changed**

Run: `uv run pytest -v`
Expected: 26 passed. This task touches only `index.html`; no Python tests are affected.

- [ ] **Step 9: Commit**

```bash
git add src/spotter/web/templates/index.html
git commit -m "$(cat <<'EOF'
feat(workouts): compact rows + click-to-detail modal

My Workouts panel renders each saved workout as a single compact row:
title (from workout.notes via titleOf, falling back to "Generated
workout"), subtitle (count · block names · relative time), small × to
remove. Whole row is clickable.

Clicking a row opens a fixed-position modal overlay containing the
full block-by-block detail (extracted from the previous full-card
renderer into a reusable renderWorkoutDetail) plus the existing
Start / Log all actions and per-exercise Swap buttons. Modal dismisses
on backdrop click, × button, or Escape key. All in-modal actions
(Start, Log all, Swap) close the modal before sending their prompt so
the chat response is visible.

Two new helpers (titleOf, relTime) support both the row and the modal.

No backend changes; the structured workout payload was already
exposed in commit 2b85bce.
EOF
)"
```

---

## Task 3: Manual browser verification

**Files:** none (manual)

This task does not commit code. It is the gate before declaring done.

- [ ] **Step 1: Ensure the dev server is running**

```bash
lsof -ti:8000 >/dev/null || (uv run python -m spotter &)
until curl -sf -o /dev/null http://127.0.0.1:8000/; do sleep 0.5; done
echo "ready"
```

Open http://127.0.0.1:8000 in the browser. Hard-refresh (Cmd-Shift-R) to bust the cached `index.html`.

- [ ] **Step 2: Generate a workout — verify chat duplication is gone**

In the chat, send: `Build me a 30-minute arms workout`.

Expected:
- Chat bubble is BRIEF — 2 to 3 sentences describing intent and possibly equipment. NO markdown tables. NO exercise list.
- Below the bubble, the structured workout card renders with the exercise list and Start / Log all / per-exercise Swap buttons.
- My Workouts panel gains a new compact row at the top with a meaningful title (e.g., "Arms-focused: biceps and triceps" — NOT "Generated workout") and a subtitle like `8 ex · warmup/main/cooldown · 1s ago`.

If the chat bubble still includes tables, the LLM did not follow the new prompt — re-send to retry, and if it persists across 2–3 generations, the prompt needs further tightening.

If the row title is still "Generated workout", the LLM did not populate `notes`. Same retry logic.

- [ ] **Step 3: Click the new row — verify the modal**

Click anywhere on the new compact row.

Expected:
- Modal overlay appears, centered, with a translucent dark backdrop.
- Modal shows the title, subtitle, full block-by-block exercise list (with swap buttons per exercise), and a Start / Log all action row.

- [ ] **Step 4: Test all three dismiss paths**

With the modal open:
1. Click the backdrop (outside the card) → modal closes.
2. Re-open the modal, click the × button → modal closes.
3. Re-open the modal, press the Escape key → modal closes.

All three should close the modal cleanly with no console errors.

- [ ] **Step 5: Test in-modal actions**

Open the modal again. Click any `Swap` button (per-exercise).

Expected: modal closes, the chat sends `Swap <exercise name> for a different exercise`, the agent replies in chat.

Re-open the modal. Click `Start`.

Expected: modal closes, the chat sends `Start this workout`.

Re-open the modal. Click `Log all`.

Expected: modal closes, the chat sends `Log all the exercises from this workout`.

- [ ] **Step 6: Verify multiple saved workouts behave independently**

Generate a second workout (e.g., `Build me a 20-minute leg session`). Expect the panel now shows TWO compact rows — distinct titles.

Click each row in turn. Each modal should show that workout's distinct details. Close each.

- [ ] **Step 7: Verify the × button on a row removes only that workout**

Click the × on the first row.

Expected: that row disappears, the second row remains. No modal opens (the × should `stopPropagation` so the row's click handler does not also fire).

- [ ] **Step 8: Verify the empty state still works**

Click × on the remaining row.

Expected: the panel reverts to the `STUB_WORKOUT_HTML` empty-state stub (the "30-min push focus" placeholder).

- [ ] **Step 9: Done**

If all eight checks pass, the feature is complete. If any step fails, file the failure as a follow-up — do not mark the task done.

---

## Out of scope (deferred per spec §9)

- Persist saved workouts across page reloads / browser restarts (sessionStorage → localStorage or a backend store).
- Generator edit support ("swap the second exercise") — already deferred from the multi-turn spec.
- Workout list sorting / filtering / search.
- Replacing the in-chat `renderWorkoutCard` with `renderWorkoutDetail` to fully share render logic (current overlap is small; consolidate when both diverge further).
- A "today's plan" prominent slot at the top of the panel.
