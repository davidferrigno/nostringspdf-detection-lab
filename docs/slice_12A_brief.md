# Slice 12A — Tap-to-place manual text + unified selection clarity

**Branch:** Create new branch `lab/editor-tap-to-place` off `main`
**File:** `E:\Code\nostringspdf\index.html` ONLY
**Estimated effort:** 1.5–2 hours
**Risk:** Low — no architectural changes, only interaction refinement

---

## Hard scope boundaries

DO:
- Edit only `E:\Code\nostringspdf\index.html`
- Stay on branch `lab/editor-tap-to-place`
- Preserve all existing types: text, checkbox, radio, check, sign, image, highlight, note
- Preserve existing undo/redo behavior
- Preserve existing AcroForm and server-detected field paths
- Preserve all keyboard shortcuts
- Preserve session continuity / restore behavior
- Preserve mobile/iOS keyboard handling (inputRef focus, etc.)
- Preserve Stripe/auth/Pro logic
- Test in browser before declaring success

DO NOT:
- Touch backend code
- Touch Stripe, Supabase auth, Turnstile, or any payment code
- Split `index.html` into components
- Replace state shape (`items`, `selId`, `editingItemId`, `editorMode`, `editMode`, `placingTextField`)
- Add libraries
- Change auto-detect logic
- Change `getTextLayout`, `getDefaultFieldFontSize`, `getVisibleFieldFontSize` or any of the typography helpers
- Change `inferFieldType`
- Add new top-level state unless absolutely necessary
- "Improve" anything outside this slice's scope — document it in code comments instead

---

## Behavior to change

### CURRENT BEHAVIOR (the problem)

To add a manual text field today, a user must:
1. Click "Edit Fields" button (top-right of toolbar) — switches `editorMode` from "fill" to "edit"
2. Click "+ Text" button in the edit toolbar — sets `placingTextField = true`
3. Click on the canvas — fires `handleCanvasClick`, which creates a 120x14 text field and starts editing it

Three clicks before typing. Too much friction.

If a user clicks empty canvas in fill mode WITHOUT first switching to edit mode, `handleCanvasClick` calls `focusFieldNearPoint` which only does something if there's an existing field nearby. If there's no field, the click does nothing. The user has no idea they should switch modes.

### DESIRED BEHAVIOR (the fix)

**Primary interaction: tap empty space anywhere to add text immediately.**

In fill mode, when a user clicks empty canvas (not on an existing field):
1. If `focusFieldNearPoint(x, y)` finds and focuses a nearby field, do that (current behavior — preserve).
2. If no nearby field exists, CREATE a new manual text field at the click position and immediately start editing it. Same behavior as the current `placingTextField` flow, but without requiring mode switch or "+ Text" button.

The "+ Text" button in edit mode toolbar still works (preserved for power users) but becomes secondary.

### Specific changes to `handleCanvasClick`

Locate `handleCanvasClick` (around line ~2530–2580). Find this block:

```javascript
if (editorMode === "fill") {
  focusFieldNearPoint(x, y);
  return;
}
```

Replace with:

```javascript
if (editorMode === "fill") {
  // First try to focus a nearby existing field (auto-detected or manual)
  if (focusFieldNearPoint(x, y)) return;
  // No nearby field — create a new manual text field at the click position
  const boxW = 200;
  const boxH = 16;
  const nextField = {
    id,
    page: pg,
    x: Math.max(0, x - 4),
    y: Math.max(0, y - boxH / 2),
    width: boxW,
    height: boxH,
    fontSize: getDefaultFieldFontSize({ height: boxH }),
    text: "",
    type: "text"
  };
  const nextItems = [...items, nextField];
  setItems(nextItems);
  setSelId(id);
  setEditingItemId(id);
  captureTypographyTelemetry(nextItems, "manual_fill_tap");
  setPostPlacementHintVisible(true);
  return;
}
```

Key changes vs current `placingTextField` path:
- `boxW = 200` instead of 120 (gives more typing room)
- `boxH = 16` instead of 14 (slightly more comfortable)
- `Math.max(0, x - 4)` so click point is near the start of the text box, not centered (feels more like a text cursor)
- Does NOT set `placingTextField = false` (it was never true)
- Does NOT set `editorMode = "fill"` (already in fill mode)
- Uses `"manual_fill_tap"` telemetry source to distinguish from `"manual"` (the toolbar button path)

### Preserve the existing `placingTextField` path

The block lower in `handleCanvasClick` that handles `if (placingTextField)` should remain unchanged. Power users who explicitly click "+ Text" in edit mode get the same behavior as before.

---

## Visual polish (selection clarity)

The current code has THREE different selection colors competing:
- Blue `#2D7FF9` for system/text fields in edit mode
- Orange `#FF6A00` for radio buttons in edit mode
- Orange `#E85D3A` for resize handles and delete buttons

Unify the selection LANGUAGE without changing accent colors elsewhere:

### Resize handle (currently very heavy)

Locate `resizeHandle` definition inside `DragItem` (around line ~1450):

```javascript
const resizeHandle = isEditMode && sel ? (
  <div onMouseDown={startResize} onTouchStart={startResize} style={{ position: "absolute", bottom: "-7px", right: "-7px", width: "18px", height: "18px", background: "#E85D3A", borderRadius: "4px", cursor: "nwse-resize", zIndex: 55, ...
```

Change to softer styling that becomes more prominent on hover:

```javascript
const resizeHandle = isEditMode && sel ? (
  <div
    onMouseDown={startResize}
    onTouchStart={startResize}
    onMouseEnter={e => e.currentTarget.style.opacity = "1"}
    onMouseLeave={e => e.currentTarget.style.opacity = "0.55"}
    style={{
      position: "absolute",
      bottom: "-6px",
      right: "-6px",
      width: "12px",
      height: "12px",
      background: "#2D7FF9",
      borderRadius: "3px",
      cursor: "nwse-resize",
      zIndex: 55,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      opacity: 0.55,
      transition: "opacity 0.15s",
      boxShadow: "0 1px 3px rgba(0,0,0,0.15)"
    }}>
    <svg width="7" height="7" viewBox="0 0 14 14">
      <line x1="10" y1="4" x2="4" y2="10" stroke="white" strokeWidth="1.5"/>
      <line x1="10" y1="8" x2="8" y2="10" stroke="white" strokeWidth="1.5"/>
    </svg>
  </div>
) : null;
```

Key changes: 12px instead of 18px, blue instead of orange (matches selection ring), 55% opacity by default that brightens on hover, smaller chevron inside.

### Delete button (currently same heavy orange)

Locate `deleteButton` definition (a few lines above resizeHandle, ~line 1445):

```javascript
const deleteButton = isEditMode && sel ? (
  <button onClick={e => { e.stopPropagation(); onDel(); }} style={{ position: "absolute", top: "-9px", right: "-9px", width: "18px", height: "18px", borderRadius: "50%", background: "#E85D3A", ...
```

Change to:

```javascript
const deleteButton = isEditMode && sel ? (
  <button
    onClick={e => { e.stopPropagation(); onDel(); }}
    onMouseEnter={e => { e.currentTarget.style.background = "#E85D3A"; e.currentTarget.style.opacity = "1"; }}
    onMouseLeave={e => { e.currentTarget.style.background = "#888"; e.currentTarget.style.opacity = "0.75"; }}
    style={{
      position: "absolute",
      top: "-7px",
      right: "-7px",
      width: "14px",
      height: "14px",
      borderRadius: "50%",
      background: "#888",
      color: "white",
      border: "none",
      fontSize: "10px",
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 60,
      opacity: 0.75,
      transition: "all 0.15s",
      boxShadow: "0 1px 3px rgba(0,0,0,0.15)",
      lineHeight: 1,
      padding: 0
    }}>
    ×
  </button>
) : null;
```

Key changes: 14px instead of 18px, neutral gray that turns red on hover, slightly less aggressive position.

### Radio button selection in edit mode

In the radio button render block (around line ~1490), the current border:
```javascript
border: ... (sel ? "2px solid #FF6A00" : "1px solid rgba(255,106,0,0.45)")
```

Change to use the unified selection blue:
```javascript
border: ... (sel ? "2px solid #2D7FF9" : "1px solid rgba(45,127,249,0.35)")
```

And the radio fill dot color when selected, change:
```javascript
background: isSystemField ? "#007AFF" : "#FF6A00"
```
to:
```javascript
background: isSystemField ? "#007AFF" : "#2D7FF9"
```

This keeps `#FF6A00` (orange) out of selection state but doesn't touch system-field rendering.

DO NOT change the highlight box dashed border color (`#DAA520` gold), the note border (`#DAA520`), or the image border (`#4F46E5`). Those are field-type-specific accent colors, not selection.

---

## Testing scenarios (run in browser before commit)

Open `index.html` in a browser (e.g. `python -m http.server 8080` from the project folder, then visit `http://localhost:8080`).

### Scenario 1: Tap-to-add in fill mode (the main feature)
1. Load any PDF (use a flat one with no AcroForm fields — e.g. an image-based form)
2. Confirm you're in "fill" mode (the "Edit Fields" button is gray, not "Done")
3. Click on empty space in the PDF where you'd want text
4. A text field should appear at the click point and immediately accept keyboard input
5. Type some text — it should appear in the field
6. Press Enter or click outside — text should remain, field should deselect

### Scenario 2: Tap-to-focus existing field still works
1. Load a PDF with AcroForm fields (e.g. an IRS form)
2. In fill mode, click on or near an existing detected field
3. The existing field should be focused/activated (not a new field created)

### Scenario 3: "+ Text" button still works in edit mode
1. Load any PDF
2. Click "Edit Fields" → switches to edit mode
3. Click "+ Text" button in toolbar
4. Click on canvas
5. A field should appear (current behavior preserved)

### Scenario 4: Resize handle is subtler
1. Place or select any text field in edit mode
2. The blue resize handle in the bottom-right corner should be small (12px), partially transparent
3. Hover over it — it should brighten to full opacity
4. Drag it — resize should still work

### Scenario 5: Delete button is subtler
1. Select any field in edit mode
2. The × button top-right should be small gray
3. Hover — should turn red
4. Click — field should delete

### Scenario 6: Existing undo/redo
1. Place a text field via tap
2. Cmd/Ctrl+Z — field should disappear
3. Cmd/Ctrl+Y — field should reappear

### Scenario 7: Mobile / touch behavior unchanged
If you have access to a phone/tablet or browser dev tools mobile emulator:
1. Tap empty canvas — same behavior as click
2. Field should accept touch keyboard input
3. Resize handle should still be tappable

### Scenario 8: Auto-detected fields look correct
1. Load a PDF that triggers AcroForm detection (any IRS form, USCIS form, etc.)
2. Confirm detected fields render as before (blue tints, no resize handles visible until selected in edit mode)
3. Click into one in fill mode — should be focusable and typeable

---

## Commit instructions

After all 8 scenarios pass:

```bash
git add index.html
git status
git diff --stat
git commit -m "feat(editor): tap-to-place text in fill mode + unified selection clarity"
git push -u origin lab/editor-tap-to-place
```

DO NOT merge to main. Dave will browser-verify on `lab/editor-tap-to-place` branch first.

---

## Out of scope (do NOT do these now)

These are real issues but explicitly NOT this slice. Document them in `docs/editor_ux_backlog.md` (create the file if it doesn't exist) and move on:

- Viewport / zoom: side-margin reduction, fit-to-width on load, stable scale during zoom
- Typography normalization: baseline alignment, vertical centering, font-size consistency across auto-detect
- Auto-detect placement quality (overlapping fields, wrong-position fields)
- Magnetic snap to nearby form geometry
- Better post-placement hint (currently a banner — could become inline coachmark)
- "Done editing" finalization (the "Done" toggle)

If you finish early, write the backlog doc. Do NOT start the next slice.
