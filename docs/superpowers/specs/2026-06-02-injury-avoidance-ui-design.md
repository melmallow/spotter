# Injury Avoidance UI — Design

**Status:** Draft — awaiting user review
**Date:** 2026-06-02
**Branch:** `fix/logger-movement-pattern-bias`
**Scope:** Pure frontend change in `src/spotter/web/templates/index.html`. No backend changes.

## 1. Problem

Injury avoidance (R28) is fully wired at the tool layer: `search_exercises` accepts `avoid_joints: list[str]` and the Sonnet generator extracts the list from natural language (`src/spotter/tools/search_exercises.py:59-66`, `tests/test_generator_empty_search.py:111`). But the only way a user discovers or invokes it today is to remember to type "avoid my knees" in chat. The constraint isn't persistent across turns, isn't discoverable, and there's no visible confirmation that it was applied.

The fix: give the constraint a discoverable, session-persistent UI surface (a chip strip), let the user override it per workout from inside the existing `+ New ↗` flow, inject the merged set into the outgoing user message as a `(avoid: …)` prefix, and render a small system-style line in the transcript so the constraint is visible.

## 2. Goals & non-goals

**Goals:**
- Persistent "Injuries to avoid:" chip strip above the chat composer, toggleable, session-scoped (`sessionStorage`).
- New step in `askGenerate()` flow ("Any injuries to avoid for this workout?") pre-checked from the strip; toggling is transient and does not mutate the strip.
- Inject the merged canonical-value set into the outgoing message as `(avoid: <values>) <user text>`. The Sonnet generator already extracts from that shape — no system-prompt change required.
- Render a small "Injuries to avoid: knee, lower back" line in the transcript (rendered from display labels) before the bot reply. No line when the set is empty.
- Display labels in the UI are user-friendly ("lower back"); stored values and the injected prefix use the dataset's canonical values ("lumbar spine") so the existing substring matcher works without changes.

**Non-goals:**
- Backend changes — no edits to `hub.py`, `app.py`, `HubState`, schemas, or tools. The current R28 plumbing stays as-is.
- Severity grading (limit-vs-exclude), substitution hints, or movement-pattern downweighting.
- Joint vocabulary expansion or fuzzy synonym matching at the tool layer.
- Cross-tab persistence (`localStorage`). Matches the `Recent logs` / `My workouts` precedent of session-only.
- Workout-card "knee-safe" badges. The chat trace line covers visibility; per-card tagging is a separate scope.

## 3. Approach

Mirror the two patterns already established in `index.html`:

- The `Recent logs` / `My workouts` sessionStorage + render-on-load pattern (around line 574+).
- The `askGenerate()` muscle-group sub-chip flow (existing).

The strip is one `<div id="injuries">` host with a `renderInjuries()` function. Storage is an array of canonical joint values. The `askGenerate()` step is extended with a second sub-chip group whose initial check state is derived from the strip but whose toggles are kept in a local closure variable — strip state is read at render time and never written by the override surface.

Sending a message — whether typed normally or via the `askGenerate` flow — prepends `(avoid: <values>) ` to the outgoing text when the relevant set is non-empty. A small `── Injuries to avoid: <labels> ──` line is rendered client-side in the transcript before the bot reply.

**Alternatives considered.**
- *Strip-only, no override sub-step.* Simpler but doesn't deliver the per-workout override the user asked for. Rejected.
- *Per-generate sub-chips only, no persistent strip.* Smaller scope but every workout requires re-picking joints. Rejected.
- *Backend `/chat` field `avoid_joints`.* More "correct" architecturally, but adds plumbing in `app.py`, `hub.py`, `HubState`, and schemas. The message-injection path is invisible to the user (UI strips the prefix from the displayed bubble), preserves existing tool/test coverage, and keeps this spec frontend-only. Rejected for now; can be revisited if free-text extraction proves unreliable.

## 4. Architecture

```
┌──────────────────────────────┐
│ Injuries to avoid strip       │  ◄── sessionStorage['spotter.avoidJoints']
│  [ knee × ] [ shoulder × ]    │      (array of canonical values)
│  [ + add ▾ ]                  │
└──────────────────────────────┘
                │ read on every send
                ▼
┌──────────────────────────────┐
│ askGenerate() chat flow       │
│   step 1: muscle group        │
│   step 2: "Any injuries...?"  │  ◄── pre-checked from strip
│           sub-chips + Skip    │      (transient closure state)
└──────────────────────────────┘
                │ merged canonical-value set
                ▼
   POST body text =
   "(avoid: knee, lumbar spine) lower body workout"
                │
                ▼
┌──────────────────────────────┐
│ /chat POST  (unchanged)       │
└──────────────────────────────┘
                │
                ▼
   Sonnet extracts avoid_joints → search_exercises filter (R28, already wired)
                │
                ▼
┌──────────────────────────────┐
│ Chat transcript               │
│   user bubble shows typed     │     (prefix stripped from display)
│   text only                   │
│   ── Injuries to avoid:       │  ◄── small system line, client-side,
│      knee, lower back ──      │      rendered from display labels
│   [ bot reply / workout card ]│
└──────────────────────────────┘
```

## 5. Data model

```js
// sessionStorage['spotter.avoidJoints'] = JSON.stringify(["knee", "lumbar spine"])
```

- Array of **canonical dataset values** (what the tool's substring filter matches on), not display labels.
- Default empty — feature is opt-in.
- Read once on page load to render the strip; re-read on every send so the latest state is always used.
- Per-generate overrides do not mutate this — they live in a closure variable inside the `askGenerate` flow.

```js
// Module-level constant — single source of truth for both surfaces.
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
```

Canonical values match dataset exactly (verified against `exercises.json` by enumerating `joints_loaded`: shoulder, hip, knee, ankle, elbow, wrist, cervical spine, thoracic spine, lumbar spine).

## 6. UI components

### 6.1 Strip (always visible, above the chat composer)

Empty state — one tap opens the add menu:

```
┌────────────────────────────────────────────────────────────────┐
│  + Add injuries to avoid                                       │
└────────────────────────────────────────────────────────────────┘
```

Populated:

```
┌────────────────────────────────────────────────────────────────┐
│ Injuries to avoid:                                             │
│  [ knee × ] [ shoulder × ] [ + add ▾ ]                         │
└────────────────────────────────────────────────────────────────┘
```

- Chip per active joint; tap `×` to remove. Tap `+ add ▾` to open a small popover anchored to the add-chip, listing the joints not currently in the strip as a stacked list of clickable rows. Clicking a row adds the chip and closes the popover. Clicking outside the popover (document-level click handler) also closes it. One chip can be added at a time; for multi-add, the user reopens the menu.
- Chip displays the `label`; stores the `value`.
- Visual language: reuses `.chip` typography (already in the stylesheet).

### 6.2 askGenerate sub-step

After muscle-group pick, the existing flow inserts a second sub-row:

```
─── Any injuries to avoid for this workout? ───
[ ✓ knee ] [ ✓ shoulder ] [ + hip ] [ + ankle ] [ + … ]
                                  [ Skip ] [ Next ]
```

- Chip with `✓` = active for this generate; chip with `+` = available, not active.
- Initial state: each chip in `JOINTS` is checked iff its value is in `loadInjuries()` at render time.
- Toggling builds a local `Set` in the closure. The strip is not modified.
- `Skip` and `Next` both call `proceedGenerate(muscle, transientSet)` — they're the same action, dual-affordance so users reading "Skip" understand they don't have to engage.

### 6.3 Chat trace line

```
── Injuries to avoid: knee, lower back ──
[ generated workout card ]
```

- Rendered client-side, before the bot reply bubble, from the same merged canonical set used to build the prefix.
- Display labels (look them up via `JOINTS`); joined by `, `.
- If the merged set is empty, no line is rendered. (Silence is fine; don't render "no injuries to avoid".)

## 7. Wiring (only file: `src/spotter/web/templates/index.html`)

| # | Where | What |
|---|-------|------|
| 1 | new `const JOINTS` near the other client-side constants | Array of `{value, label}` for the 9 dataset joints. Single source of truth for strip, askGenerate sub-step, and trace-line label lookup. |
| 2 | header markup, just above the chat composer | New `<div id="injuries">` host for the strip. |
| 3 | new CSS rules | `.injuries` row layout, `.injury-chip`, `.injury-chip .x`, `.injury-add` menu, `.gen-step` reuse for the askGenerate step, `.sys-line` muted divider for the chat trace. Mirror existing `.chip` / `.sub-chip` typography. |
| 4 | new JS block, mirroring `loadLogs`/`saveLogs`/`renderLogs` (~line 574+) | `loadInjuries()`, `saveInjuries(arr)`, `toggleInjury(value)`, `renderInjuries()`. State lives in `sessionStorage['spotter.avoidJoints']` (array of canonical values). `loadInjuries()` filters out any stored values not in `JOINTS`. |
| 5 | `askGenerate()` (existing) | After muscle pick, post a second sub-chip group from `JOINTS`. Each chip's initial checked state derived from `loadInjuries()`. Track checked state in a local `Set` (the closure). `Skip` and `Next` both call `proceedGenerate(muscle, transientSet)`. Strip state is NOT written. |
| 6 | new `proceedGenerate(muscle, injuriesSet)` | Build the muscle-message text as today. If `injuriesSet.size > 0`, prepend `(avoid: <canonical values joined by ', '>) `. POST. Append the `── Injuries to avoid: <display labels> ──` system line to the transcript before the bot reply renders. |
| 7 | normal send path (typed message, not via askGenerate) | Same prefix-injection logic, sourced from `loadInjuries()` only. Same system line. Free-text "today knees are fine" still works — Sonnet extracts as today. |
| 8 | display of the user bubble | Render the typed text only. Strip the prefix client-side via the deterministic shape `/^\(avoid: [^)]+\) /` before passing the string to the bubble renderer. Prefix is purely a transport detail and never displayed. |
| 9 | page-load init (next to `renderLogs()` ~line 630) | `renderInjuries()` once. |

**No backend changes.** `hub.py`, `app.py`, schemas, tools all untouched. R28 tests still cover the tool-layer correctness end-to-end.

## 8. Edge cases

- **Empty strip, askGenerate Skipped:** no prefix injected, no system line rendered. Behaves identically to today.
- **Strip set, user types free-text "avoid my elbow too":** the injected prefix lists strip values; the free text adds elbow. Sonnet merges both into `avoid_joints` — no UI handling needed.
- **Strip set, user types "today knees are fine":** the prefix still says `(avoid: knee)`. The Sonnet system prompt tolerates contradictions and the user's last word wins; we don't try to be smarter than that. Documented behavior, not a bug.
- **User toggles strip mid-generation** (after `+ New ↗` but before clicking `Next`): the askGenerate step's pre-checked state is captured when the sub-row renders. Strip edits after that point don't bleed in. Behavior is consistent and explained by the UI: the sub-chips are *this turn's*.
- **`sessionStorage` quota / disabled:** treat as empty strip; `saveInjuries` catches the exception and the chip just doesn't persist. Strip still works in-memory.
- **Unknown joint value in storage** (schema drift, manual edit): `loadInjuries()` filters values not in `JOINTS`. Bogus values silently dropped.
- **Send-button keyboard shortcut bypasses askGenerate:** the typed-message send (wiring #7) is the catch-all. Even with no askGenerate flow, the strip prefix is still injected. The askGenerate sub-step is only the *override* surface, never the *only* surface.
- **Duplicate joint in storage** (e.g., `["knee", "knee"]`): `loadInjuries()` dedups via `new Set` before returning.

## 9. Testing

Frontend-only template change. No Python tests to add or update — existing R28 backend coverage (`tests/test_generator_empty_search.py`) still validates the tool-layer behavior end-to-end.

**Manual verification, against `make dev` locally:**

1. Reload — strip shows muted `+ Add injuries to avoid` collapsed state. No chips.
2. Open strip menu → tap "knee" → strip shows `[ knee × ]`. Reload — still there (sessionStorage).
3. Type "lower body workout" → Send. Network tab: POST body contains `(avoid: knee) lower body workout`. Chat: user bubble shows `lower body workout` only (no prefix), system line `Injuries to avoid: knee` above the bot reply, workout card has no knee-loaded exercises (spot-check against `joints_loaded` in the returned card).
4. Tap `+ New ↗` → muscle sub-chips → tap `Legs`. Next sub-row reads `Any injuries to avoid for this workout?` with `[ ✓ knee ]` and `[ + shoulder ]` etc. Tap `knee` to uncheck, tap `shoulder` to check. Click `Next`. POST: `(avoid: shoulder) Legs ...`. System line: `Injuries to avoid: shoulder`. Strip still shows only `knee` (override didn't mutate the strip).
5. Clear all strip chips via `×`. Empty state returns to `+ Add injuries to avoid`. Sending a plain message: no prefix, no system line.
6. Add `lower back` from the menu → DevTools confirms `sessionStorage['spotter.avoidJoints']` contains `"lumbar spine"`. Send → POST contains `(avoid: lumbar spine)`. System line displays `Injuries to avoid: lower back`.
7. Close tab and reopen → strip is empty (sessionStorage scope confirmed).
8. Manually set `sessionStorage['spotter.avoidJoints']` to `["knee", "elbow joint"]` → reload. Strip shows only `[ knee × ]`; the bogus value is silently dropped.

I'll drive these manually after implementation — no headless browser tooling in the repo, matching the precedent set by the My-Workouts spec.
