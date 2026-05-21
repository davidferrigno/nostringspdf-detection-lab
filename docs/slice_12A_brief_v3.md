# Slice 12A — Double-tap-to-place manual text + unified selection clarity

**Branch:** Create new branch `lab/editor-tap-to-place` off `main`
**File:** `E:\Code\nostringspdf\index.html` ONLY
**Estimated effort:** 1.5–2 hours
**Risk:** Low — no architectural changes, only interaction refinement

---

## Performance constraint (read first)

**Preserve current performance characteristics. Do not introduce additional rerender loops, global listeners, or expensive geometry scans during click handling.** Specifically: do not add document-level mousemove/touchmove listeners that fire during normal interaction, do not add geometry/DOM queries inside `handleCanvasClick` or `handleCanvasDoubleClick` beyond what's already there, do not introduce useEffect dependencies that retrigger on every items mutation. The editor must feel exactly as snappy after this slice as before — or snappier.

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

DO NOT (specific exclusions Dave is flagging):
- Modify `DragItem` behavior for non-text field types except the visual polish for resize/delete handles described below. Checkbox, radio, signature, image, highlight, and note logic must be preserved untouched.
- Touch viewport scaling, `fitScale`, `cw` calculation, `maxWidth: "min(1100px, 92vw)"`, or any zoom logic. That is Slice 12B.
- Remove or collapse the `editorMode` ("fill"/"edit") distinction. The mode architecture stays. We are refining within it.
- Change typography rendering (font size logic, baseline alignment, padding calculations). That is Slice 12C.

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

**Primary new interaction: DOUBLE-click empty canvas in fill mode to add a text field at that position and immediately start typing.**

Key principle: **single-click semantics are unchanged.** Single-click in fill mode still means "interact with what's there" (focus a nearby field, or do nothing if empty). Double-click is the explicit create gesture, matching macOS/iPadOS muscle memory for text creation.

This means:
- Casual clicks (deselect, scroll intent on touch, accidental taps) do NOT create fields. No accidental field spam.
- The "+ Text" button in edit mode still works (preserved for power users).
- Users who explicitly want to add text can double-click anywhere, anytime.

### Specific changes to `handleCanvasClick`

Locate `handleCanvasClick` (the `useCallback` around line ~2530–2580). Find this block:

```javascript
if (editorMode === "fill") {
  focusFieldNearPoint(x, y);
  return;
}
```

This block stays exactly as-is. Single-click behavior in fill mode is UNCHANGED.

### Add a NEW double-click handler on the canvas

Find the canvas div in the render section (search for `onClick={handleCanvasClick}` inside the editor JSX, around line ~2850):

```javascript
<div ref={pdfContainerRef} onClick={handleCanvasClick} style={...}>
```

Add a new `onDoubleClick` handler:

```javascript
<div ref={pdfContainerRef} onClick={handleCanvasClick} onDoubleClick={handleCanvasDoubleClick} style={...}>
```

Then define `handleCanvasDoubleClick` as a new `useCallback` near `handleCanvasClick` (place it immediately after `handleCanvasClick`):

```javascript
const handleCanvasDoubleClick = useCallback((e) => {
  // Only handle double-click in fill mode for empty space (not on existing items)
  if (editorMode !== "fill") return;
  if (e.target.closest("[data-item]")) return; // clicked on an existing item
  // Don't create a field if the user is in the middle of placing something else
  if (placingSign || placingImg) return;
  e.preventDefault();
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  const x = (e.clientX - r.left) / scale;
  const y = (e.clientY - r.top) / scale;
  const id = Date.now().toString();
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
  captureTypographyTelemetry(nextItems, "manual_fill_doubletap");
  setPostPlacementHintVisible(true);
}, [editorMode, pg, scale, items, placingSign, placingImg]);
```

Key choices:
- Double-click ONLY works in fill mode. Edit mode keeps its existing "+ Text" button path.
- `boxW = 200` instead of 120 (gives more typing room than the toolbar-button path)
- `boxH = 16` instead of 14 (slightly more comfortable)
- `Math.max(0, x - 4)` so the click point is near the start of the text box (feels like a text cursor lands there)
- Telemetry source `"manual_fill_doubletap"` to distinguish from `"manual"` (toolbar button) for future analysis
- Guards against placing while sign/image placement is in progress

### Preserve the existing `placingTextField` path

The block lower in `handleCanvasClick` that handles `if (placingTextField)` remains UNCHANGED. Power users who explicitly click "+ Text" in edit mode get the same single-click placement as before.

### Touch device note

`onDoubleClick` works for both mouse double-click and touch double-tap on iOS Safari and Android Chrome. No additional touch handling needed. If a future Slice 12-X needs custom touch handling for this, that's a separate slice.

---

## Visual polish (selection clarity)

The current code has THREE different selection colors competing:
- Blue `#2D7FF9` for system/text fields in edit mode
- Orange `#FF6A00` for radio buttons in edit mode
- Orange `#E85D3A` for resize handles and delete buttons

Unify the selection LANGUAGE without changing accent colors elsewhere.

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

### Radio button selection in edit mode (visual polish only)

In the radio button render block (search for `type === "radio"` inside DragItem, around line ~1490):

Current border for the selection state:
```javascript
border: ... (sel ? "2px solid #FF6A00" : "1px solid rgba(255,106,0,0.45)")
```

Change ONLY the selection border color (when in edit mode AND selected) to use the unified selection blue:
```javascript
border: ... (sel ? "2px solid #2D7FF9" : "1px solid rgba(255,106,0,0.45)")
```

The radio button's fill behavior, click handler, group-radio mutex logic, and rendering must remain UNTOUCHED. Only the selected-state border color changes.

DO NOT change:
- The radio button's checked state fill color (`#FF6A00` for manual, `#007AFF` for system)
- Any radio button click/touch logic
- Radio groupId behavior
- The highlight box dashed border color (`#DAA520` gold)
- The note border color (`#DAA520`)
- The image border color (`#4F46E5`)

Those are field-type-specific accent colors, not selection language.

---

## Testing scenarios (run in browser before commit)

Open `index.html` in a browser. Easiest local path:
```bash
cd /d E:\Code\nostringspdf
python -m http.server 8080
```
Then visit `http://localhost:8080`.

If Python isn't installed on Windows, use any other static server, or open `index.html` directly (file:// URL — most features work but server-side detection won't).

### Scenario 1: Double-tap-to-add in fill mode (the main feature)
1. Load any PDF (use a flat one without AcroForm fields if possible)
2. Confirm you're in "fill" mode (button at top-right says "Edit Fields", not "Done")
3. SINGLE-click on empty space — should do nothing visible (no field created)
4. DOUBLE-click on empty space where you'd want text
5. A text field should appear at the click point and immediately accept keyboard input
6. Type some text — it should appear in the field
7. Press Enter or click outside — text should remain, field should deselect

### Scenario 2: Single-click in fill mode does NOT create fields (regression prevention)
1. Load any PDF
2. In fill mode, single-click multiple times on empty areas of the page
3. NO new fields should be created
4. Scroll/pan the page (if applicable) — no fields should be created
5. Click outside any existing field to deselect — no fields should be created

### Scenario 3: Tap-to-focus existing field still works (single-click)
1. Load a PDF with AcroForm fields (e.g. an IRS W-9 or similar)
2. In fill mode, SINGLE-click on or near an existing detected field
3. The existing field should be focused/activated (current behavior preserved)

### Scenario 4: "+ Text" button still works in edit mode
1. Load any PDF
2. Click "Edit Fields" → switches to edit mode
3. Click "+ Text" button in edit-mode toolbar
4. SINGLE-click on canvas
5. A text field should appear (current behavior preserved)
6. Double-click in edit mode should NOT trigger the new fill-mode double-click path

### Scenario 5: Double-tap on existing field does NOT create new one
1. Place or have a text field on the page
2. Double-click ON the existing field
3. No new field should be created
4. The existing field's normal click behavior (focus/edit) should run

### Scenario 6: Resize handle is subtler
1. Place or select any text field in edit mode
2. The resize handle in the bottom-right corner should be small (12px), blue, partially transparent (~55%)
3. Hover over it — should brighten to full opacity
4. Drag it — resize should still work normally

### Scenario 7: Delete button is subtler
1. Select any field in edit mode
2. The × button top-right should be small gray (14px, 75% opacity)
3. Hover — should turn red, full opacity
4. Click — field should delete

### Scenario 8: Existing undo/redo
1. Double-click empty space to create a text field
2. Cmd/Ctrl+Z — field should disappear
3. Cmd/Ctrl+Y — field should reappear
4. Verify drag, resize, type operations all undo correctly

### Scenario 9: Mobile / touch double-tap (if testable)
If you have a phone/tablet or browser dev tools mobile emulator:
1. Load a PDF in fill mode
2. Single-tap empty canvas — no field created
3. Double-tap empty canvas — text field created at tap location
4. Field should accept touch keyboard input
5. Resize handle should still be tappable

### Scenario 10: Auto-detected fields unchanged
1. Load a PDF that triggers AcroForm detection
2. Confirm detected fields render exactly as before (no visual regression)
3. Single-click into one in fill mode — should be focusable and typeable
4. Switch to edit mode — resize handles should appear in new subtler style on the selected field
5. Switch back to fill mode — fields should look the same as before

### Scenario 11: Non-text field types unchanged
1. Add a checkbox via the "+ Check" tool (edit mode) — should work exactly as before
2. Add a signature — should work exactly as before
3. Add a highlight — should work exactly as before
4. Add a note — should work exactly as before
5. Radio buttons (if present in detected fields) — should still toggle correctly

### Scenario 12: Performance regression check
1. Load any PDF with 50+ auto-detected fields
2. Click around the canvas rapidly (single-clicks)
3. The page should remain responsive — no visible lag, no console errors
4. Scroll the PDF rapidly
5. Open browser devtools Performance tab. Record a 5-second session of clicking and scrolling. Confirm no unusual long tasks (>50ms) appear in the timeline that weren't there before.

---

## Commit instructions

After all 12 scenarios pass:

```bash
git add index.html
git status
git diff --stat
git commit -m "feat(editor): double-tap to place text in fill mode + unified selection clarity"
git push -u origin lab/editor-tap-to-place
```

DO NOT merge to main. Dave will browser-verify on `lab/editor-tap-to-place` branch first, then merge if satisfied.

---

## Out of scope (do NOT do these now)

These are real issues but explicitly NOT this slice. If you have time after the 12 scenarios pass, create or append `docs/editor_ux_backlog.md` with these items. Do NOT implement them:

- Viewport / zoom: side-margin reduction, fit-to-width on load, stable scale during zoom (Slice 12B)
- Typography normalization: baseline alignment, vertical centering, font-size consistency across auto-detect (Slice 12C)
- Auto-detect placement quality (overlapping fields, wrong-position fields) (Slice 12D)
- Magnetic snap to nearby form geometry (future)
- Better post-placement hint (currently a banner — could become inline coachmark) (future)
- "Done editing" finalization flow (future)
- Eliminating the editorMode "fill"/"edit" distinction entirely (future, architecturally significant)

If you finish early, write the backlog doc. Do NOT start any next slice.
