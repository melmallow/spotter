# Workout Rendering Cleanup — Design

**Status:** Draft — awaiting user review
**Date:** 2026-06-03
**Branch:** `fix/logger-movement-pattern-bias`
**Supersedes (partial):** the saved-workout *card* design in `docs/brainstorms/2026-06-02-my-workouts-section.md` §6. The empty-state stub, sessionStorage shape, cap-at-20 policy, and auto-save behavior remain unchanged.

## 1. Problem

Two issues surfaced during the post-multi-turn browser walkthrough:

1. **Chat duplication.** When the generator returns a workout, the chat shows it twice — once as the LLM's verbose markdown narrative (per-block tables for `Warm-Up` / `Main Work` / `Cool-Down`, plus `Equipment Needed` and `Tips` sections), and again as the structured workout card with swap/start/log-all buttons. Both contain the same exercise list.
2. **My Workouts panel renders detail, not summary.** The currently-shipped panel (from `2026-06-02-my-workouts-section.md`) draws the full block-by-block exercise prescription inside each saved-workout card. With more than one or two workouts saved, the panel becomes a wall of text and the user can't scan their session.

## 2. Goals & non-goals

**Goals:**
- A single, non-duplicated representation of a generated workout in the chat.
- My Workouts panel becomes a compact, scannable list of saved workouts — one row per workout.
- Each row has a meaningful title (not all "Generated workout").
- Clicking a row opens a detailed view (modal overlay) with the full prescription and the existing actions (Start, Log all, per-exercise Swap).

**Non-goals:**
- Backend schema changes. No new `WorkoutPlan` / `BuildWorkoutInput` fields. The existing `notes: str | None` field on `BuildWorkoutInput` carries the title; everything else flows unchanged.
- Cross-session persistence (workouts still live in `sessionStorage` only, per the 2026-06-02 spec).
- Search, filtering, editing, or sorting of saved workouts.
- A separate "detail page" route — single-page app stays single-page.
- New chat card structure. The in-chat `renderWorkoutCard` stays as-is; the chat duplication is resolved by tightening the LLM's narrative, not by changing card markup.

## 3. Approach

Two coordinated changes (the backend workout-payload plumbing already shipped in commit `2b85bce`):

1. **`agents/generator.py` — prompt tightening.** Two additions to `GENERATOR_SYSTEM_PROMPT`:
   - Instruct the LLM to always populate `build_workout`'s `notes` field with a short (4–8 word) descriptive title (e.g., `"Arms-focused: biceps and triceps"`, `"30-min upper push"`). This becomes the saved-workout list title.
   - Instruct the LLM to keep its post-tool narrative brief (2–3 sentences, optional Equipment / Tips paragraph) and to NOT list exercises in tables or bullets — the structured card renders those. This eliminates the chat duplication.

2. **`web/templates/index.html` — My Workouts panel restructure.** Replace `renderSavedWorkout` (the current full-detail card) with `renderSavedWorkoutRow` (a compact row), add a modal overlay that opens on row click, and extract the existing detail-rendering body into a reusable `renderWorkoutDetail` used by both the in-chat card and the modal.

## 4. Architecture

```
agents/generator.py
└── GENERATOR_SYSTEM_PROMPT  (EDITED — two additions to the existing prompt)
    + "When calling build_workout, always populate `notes` with a short
       (4–8 word) descriptive title (e.g., 'Arms-focused: biceps and
       triceps', '30-min upper push'). This appears as the saved-
       workout title in the user's list."
    + "After tools complete, write a BRIEF response (2–3 sentences)
       describing the workout's intent and any equipment they'll need.
       Do NOT list exercises in tables or bullet points — the UI
       renders the structured workout below your text."

web/templates/index.html (within the existing script block)
├── send()                                  unchanged
├── addBot()                                unchanged (LLM produces less text → no more duplication)
├── saveWorkout(w)                          unchanged
├── titleOf(w)                              NEW — returns w.notes if non-empty else 'Generated workout'
├── relTime(iso)                            NEW — '2m' / '1h' / '3d' formatter
├── renderWorkoutDetail(w)                  NEW — extracted from the body of the
│                                                  current renderSavedWorkout (block-by-block
│                                                  exercise list). Used by the modal AND can
│                                                  optionally be used by renderWorkoutCard in
│                                                  the future to deduplicate (out of scope here).
├── renderSavedWorkoutRow(it)               NEW — one compact row:
│                                                  title (from titleOf), subtitle
│                                                  (count · block names · relTime),
│                                                  whole-row click → openWorkoutModal(it.id),
│                                                  × button (stopPropagation) → removeWorkout(it.id)
├── renderWorkouts()                        REWRITTEN — empty: keep current stub fallback.
│                                                       non-empty: map items through
│                                                       renderSavedWorkoutRow.
├── openWorkoutModal(id)                    NEW — builds a fixed-position overlay containing
│                                                  the title, subtitle, renderWorkoutDetail(w),
│                                                  and Start / Log all actions.
└── closeWorkoutModal()                     NEW — removes the overlay.

REMOVED: renderSavedWorkout (its detail body moves into renderWorkoutDetail; its outer card
shell is replaced by renderSavedWorkoutRow).
```

## 5. Component details

### Compact row (`renderSavedWorkoutRow`)

```
┌──────────────────────────────────────────────┐
│ Arms-focused: biceps and triceps         ×  │
│ 8 ex · warm/main/cd · 2m ago                │
└──────────────────────────────────────────────┘
```

- Title: `titleOf(it.workout)` — falls back to `'Generated workout'` when `notes` is empty.
- Subtitle: `${exerciseCount} ex · ${blockNames.join('/')} · ${relTime(it.saved_at)} ago`.
- Whole row is clickable; the `×` remove button calls `event.stopPropagation()` before `removeWorkout`.
- Cursor: `pointer` on the row.
- Visual density: similar to existing Recent Logs rows, slightly taller because of the subtitle line.

### Modal overlay (`openWorkoutModal`)

```
┌─ overlay (full viewport, rgba(0,0,0,.45)) ──────────────┐
│                                                         │
│       ┌─ card ─────────────────────────────────┐        │
│       │ Arms-focused: biceps and triceps   ×  │        │
│       │ 8 ex · warm/main/cd                    │        │
│       │ ────────────────────────────────────── │        │
│       │ WARMUP                                 │        │
│       │   Resistance Band Reverse Curl         │        │
│       │   2 × 15 · rest 30s                    │        │
│       │ MAIN                                   │        │
│       │   Wide-Grip Preacher Curl (EZ Bar)     │        │
│       │   3 × 10 · rest 60s        [swap]      │        │
│       │   ...                                  │        │
│       │ COOLDOWN                               │        │
│       │   ...                                  │        │
│       │ ────────────────────────────────────── │        │
│       │ [▶ Start]  [Log all]                   │        │
│       └────────────────────────────────────────┘        │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

- Fixed-position overlay covers the viewport (`position: fixed; inset: 0`).
- Dismiss: click on backdrop, click `×` button, or press `Escape`.
- Inside: title + subtitle (same shape as the row), block-by-block detail via `renderWorkoutDetail`, plus two workout-level actions (Start, Log all) that send their `data-ask` prompts to the chat (same behavior as today's inline card).
- Per-exercise Swap, Start, and Log all buttons all close the modal before sending their chat prompt — same rationale: the agent's reply is the next thing the user wants to see, and dismissing the overlay is faster than chasing it.
- Single modal at a time — `openWorkoutModal` removes any existing overlay before creating a new one (guards against double-click).
- No focus trap; demo scale doesn't justify it.

### Helper: `titleOf(workout)`

```javascript
function titleOf(w) {
  const notes = ((w && w.notes) || '').trim();
  return notes || 'Generated workout';
}
```

### Helper: `relTime(iso)`

```javascript
function relTime(iso) {
  const then = new Date(iso).getTime();
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

### Helper: `renderWorkoutDetail(w)`

Extracted verbatim from the body of the current `renderSavedWorkout` function (the block-by-block exercise list with names, side notes, and prescriptions). Returns a single HTML string. Pure function — no event wiring (the modal does that after injecting the HTML).

## 6. Data flow

The structured workout payload originates inside the generator's `_finalize` node, which scans the generator's scratch for the last `ToolMessage` whose JSON contains a `"blocks"` key (the `build_workout` tool result), and writes it to `state["sub_agent_output"]["workout"]`. From there:

1. `_resolved_workout(out)` in `hub.py` returns the workout payload when `out["route"] == "WORKOUT_GENERATE"` (already shipped in commit `2b85bce`).
2. `run_hub`'s success return includes `"workout": _resolved_workout(out)` (already shipped).
3. The `/chat` handler adds `"workout": result.get("workout")` to its JSON payload (already shipped).
4. Frontend `send()` reads `d.workout`; `addBot` renders the structured card (unchanged); `saveWorkout(d.workout)` persists to `sessionStorage`; `renderWorkouts()` re-renders the compact list (CHANGED in this spec).

This spec only changes step 4. Steps 1–3 are existing behavior.

## 7. Error handling

- **Modal opened with a stale id.** `loadWorkouts().find(it => it.id === id)` returns undefined → close the modal silently and `console.warn`.
- **`workout.notes` missing or empty.** `titleOf` fallback to `'Generated workout'`.
- **`relTime` for a future timestamp** (clock skew). `Math.max(1, ...)` floors at 1 second.
- **`workout.blocks` missing or non-array.** `renderWorkoutDetail` early-returns an empty string; the modal shows just the title + actions. The row's exercise count falls to 0.
- **Multiple rapid clicks open multiple modals.** `openWorkoutModal` calls `closeWorkoutModal()` first, so only one overlay exists at a time.
- **Escape pressed when no modal is open.** No-op — handler is attached/detached around `openWorkoutModal`/`closeWorkoutModal`.

## 8. Testing

No automated tests added. UI changes are visually verifiable, and the prompt change is covered by evals (not unit tests). Existing 26 tests stay green — generator tests stub the LLM, so prompt edits don't affect them.

**Manual verification before declaring done:**

1. Restart dev server, open browser.
2. `Build me a 30-minute arms workout`. Expect: chat bubble is brief (2–3 sentences, no exercise tables), structured card renders below it with the workout. My Workouts panel gains a new compact row with a meaningful title (e.g., "Arms-focused: biceps and triceps").
3. Click the new row. Modal opens with the full block-by-block detail.
4. Dismiss the modal three ways: click backdrop, click `×`, press Escape. All three close it.
5. Re-open the modal, click `Swap X` on any exercise. Modal closes AND the chat sends `Swap X for a different exercise`.
6. Re-open the modal, click `Start` and `Log all`. Modal closes (same rationale as Swap — the chat response is the next thing the user wants to see). Chat sends the corresponding prompts.
7. Generate a second workout. Both rows render in the panel. Open each — distinct titles, distinct details.
8. Click `×` on a row — workout removed from list; modal does not appear. Other workouts unaffected.

## 9. Follow-ups (explicitly out of scope)

- Persist saved workouts across page reloads / browser restarts (sessionStorage → localStorage or backend store).
- Generator edit support ("swap the second exercise") — already deferred from the multi-turn spec.
- Workout list sorting / filtering / search.
- Replacing the in-chat `renderWorkoutCard` with `renderWorkoutDetail` to fully share render logic (current overlap is small; consolidate when both diverge further).
- A "today's plan" prominent slot at the top of the panel.
