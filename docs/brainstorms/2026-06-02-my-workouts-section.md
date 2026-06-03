# My Workouts Section — Design

**Status:** Draft — awaiting user review
**Date:** 2026-06-02
**Branch:** `fix/logger-movement-pattern-bias`
**Scope:** Pure frontend change in `src/spotter/web/templates/index.html`. No backend changes.

## 1. Problem

The main page has a `Today's plan` section showing a single hardcoded stub workout card. There's no way to keep workouts the user has generated through the chat — every generated workout lives only inside the chat scrollback and is lost when the page is reloaded mid-tab or the chat scrolls past it.

The fix: turn the section into `My workouts`, auto-save every generated workout to it, let the user dismiss saved workouts with a small `×`, and keep the existing stub as a one-time placeholder for the empty state.

## 2. Goals & non-goals

**Goals:**
- Rename `Today's plan` → `My workouts`.
- Every workout returned by the chat (`d.workout`) is auto-saved to the section.
- Each saved workout shows title + meta + the same `Start` / `Log all` actions the in-chat card has, plus a small `×` that removes it.
- Empty state renders the existing stub card markup exactly as-is.
- Persists within the browser tab (`sessionStorage`), matching the existing `Recent logs` pattern.
- First generated workout replaces the stub. If the user `×`'s all saved workouts later, the stub returns.

**Non-goals:**
- Backend persistence, multi-user, or cross-tab sync.
- Edit, rename, reorder, duplicate, schedule, or favorite on saved workouts.
- Restoring a `×`'d workout (no undo).
- New chat behavior beyond the existing `d.workout` payload — the chat side is untouched.

## 3. Approach

Mirror the `Recent logs` pattern that already exists in the same template:

- A `sessionStorage` key (`spotter.savedWorkouts`) holds an array of `{ id, saved_at, workout }`.
- A `renderWorkouts()` function chooses the render mode: empty list → stub markup; non-empty → stacked saved cards.
- The existing `/chat` response handler (around line 566) already destructures `d.workout`; we add one line that calls `saveWorkout(d.workout)` when present.
- A small `×` button on each card calls `removeWorkout(id)`, which mutates storage and re-renders.

**Alternatives considered.**
- *Explicit "Save" button on the in-chat workout card.* Adds friction and a fourth button to the card's action row. User feedback chose auto-add + `×`.
- *Always-pinned stub.* Keeps the demo card visible forever. Rejected — once the user has their own workouts, the demo is clutter. The stub belongs in the empty state, not the populated state.
- *`localStorage` persistence across tabs.* Rejected to match the existing `Recent logs` precedent and avoid stale workouts accumulating over weeks.

## 4. Architecture

```
generated workout payload (d.workout from /chat response)
                 │
                 ▼
   saveWorkout({ id: uuid(), saved_at: ISO, workout })
                 │
                 ▼
   sessionStorage[spotter.savedWorkouts]  (cap 20, newest first)
                 │
                 ▼
            renderWorkouts()
            ┌──────────────┴──────────────┐
       empty list                   has items
            │                            │
            ▼                            ▼
   stub markup (existing       stacked saved-workout
   .plan card, untouched)      cards with × remove
```

## 5. Data model

```js
// sessionStorage['spotter.savedWorkouts'] = JSON.stringify([
{
  id: "<uuid>",                  // crypto.randomUUID()
  saved_at: "2026-06-02T18:42Z", // ISO string, for display + ordering
  workout: { blocks: [...], notes: "..." }  // raw d.workout payload from /chat
}
// ])
```

- Cap at 20 most recent (slice on save).
- Order: newest first (unshift).

## 6. UI components

**Section header.** `<h2>My workouts</h2>` and a right-aligned link `+ New ↗` that calls `askGenerate()` — the muscle-group sub-chip flow added in the previous step. Replaces the current `Regenerate ↗` link.

**Empty state.** The existing `.plan` card markup, unchanged. Image, "30-min push focus", Start session / View exercises buttons.

**Saved-workout card.** Reuses the visual language of the in-chat `.wcard` (white box, rounded, block summary) but lives inside the main column instead of the chat:

```
┌──────────────────────────────────────────────  ×  ┐
│ Generated workout                                  │
│ 4 exercises · Warmup · Main · Cooldown             │
│                                                    │
│  Warmup                                            │
│    Push-Up to Knee-Drive    2 × 10 · rest 30s      │
│  Main                                              │
│    Dumbbell Bench Press     4 × 8  · rest 90s      │
│    ...                                             │
│                                                    │
│  [ ▶ Start ]   [ Log all ]                         │
└────────────────────────────────────────────────────┘
```

- Title is the fixed string `Generated workout`. The `d.workout` payload doesn't carry a human title and inventing one would be lying.
- Meta line uses the same derivation already present in `renderWorkoutCard()` (`renderWorkoutCard` line ~407): exercise count + block names joined with `·`, or `w.notes` if present.
- Action buttons use `data-ask` exactly like the in-chat card so they piggyback on the existing click delegation pattern.
- `×` is a small unstyled button positioned top-right of the card, hover state matches `.wc-swap`.

## 7. Wiring (only file: `index.html`)

| Edit | Where | What |
|------|-------|------|
| 1 | section markup (line 321) | rename to `My workouts`, link → `+ New ↗ onclick="askGenerate()"`, wrap the existing stub in `<div id="workouts">` so JS can swap inner content |
| 2 | new CSS rule | `.workout` card style (reuse `.wcard`-like styling) and `.workout .x` for the remove button |
| 3 | new JS block | `loadWorkouts()`, `saveWorkouts()`, `saveWorkout(w)`, `removeWorkout(id)`, `renderWorkouts()` — mirrors the `loadLogs`/`saveLogs`/`recordLog`/`renderLogs` block at line 574+ |
| 4 | response handler (line 566) | add `if (d.workout) saveWorkout(d.workout);` after the `addBot(...)` call. The existing `addBot(...)` already renders the in-chat card; saving is additive. |
| 5 | page-load init | call `renderWorkouts()` once at the bottom of the script, next to the existing `renderLogs()` call (line 630) |

## 8. Edge cases

- **`d.workout` arrives but has no blocks.** Skip the save (`if (d.workout && Array.isArray(d.workout.blocks) && d.workout.blocks.length)`).
- **User generates 25 workouts in a session.** Cap at 20, drop oldest. Same as the logs cap-at-50 precedent (slightly tighter because workout cards are bigger).
- **User removes the last saved workout.** `renderWorkouts()` detects empty list, restores stub markup.
- **User refreshes the tab.** `renderWorkouts()` runs on init, reads from sessionStorage, restores the saved cards.
- **`crypto.randomUUID()` unavailable** (very old browser). Fall back to `Date.now() + Math.random().toString(36).slice(2)` for the id.

## 9. Testing

This is a frontend-only template change. There are no Python tests to add or update. Manual verification:

1. Reload the page → stub workout visible in the section, headed `My workouts`.
2. Click `+ New ↗` → muscle-group sub-chips appear in chat.
3. Click `Legs` → generation completes → saved workout appears in the section, stub gone.
4. Generate a second workout → it appears above the first.
5. Click `×` on the top card → it disappears, second card remains.
6. Click `×` on the last remaining saved card → stub returns.
7. Reload the tab → saved workouts are still there. Close tab and reopen → they're gone (sessionStorage).

I'll drive these manually after implementation. There is no headless browser tooling in this repo.
