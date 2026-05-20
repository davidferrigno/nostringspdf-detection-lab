# Field Rendering Separation Rule

**Status:** Architectural constraint, effective immediately
**Filed:** May 18, 2026
**Context:** Established after MANUAL-2a-fix-1 (commit `ba55fee`) regressed AcroForm-detected field rendering by sharing the text-field render path between system and manual fields. Reverted in commit `d869f19`.

---

## The Rule

System fields (AcroForm, template-matched, or automatically detected) and manual user-created fields must use separate rendering, interaction, and state-management logic.

Changes to manual-field workflows must not alter:
- System-field rendering
- System-field interaction
- System-field visual treatment

Changes to system-field behavior must not alter:
- Manual placement workflow
- Manual geometry editing
- Manual-field interaction

---

## Why this matters

The two categories serve fundamentally different user intentions:

- **System fields prioritize content interaction.** They were discovered by the application. The user wants to fill them. The geometry already exists. The field should feel like part of the document.

- **Manual fields prioritize geometry interaction before content interaction.** The user is constructing a writable region. They define the size and position first, then type. The field is a user-created object.

At any moment, the user should always know whether they are:
- filling a field (entering content into a defined region)
- defining geometry (creating or sizing a region)
- editing document structure (rearranging, deleting, or modifying existing elements)

Ambiguity between these states is the source of most editor clunkiness. Separate rendering and interaction contracts for system vs manual fields is what keeps these states unambiguous.

Treating these as one component class produces UX regressions because any change to "text field rendering" affects both categories simultaneously. This is what caused the MANUAL-2a-fix-1 regression: the fix made all text-type fields render as visible input elements in Fill mode, including AcroForm-detected fields, which destroyed document readability.

---

## Mandatory regression testing

Every editor change must be verified against:

1. AcroForm PDF (system fields with embedded form metadata)
2. Flat PDF with manual fields (user-placed only)
3. Flat PDF with Pro automatic detection (heuristic-detected system fields)
4. Desktop browser (Chrome incognito)
5. Mobile Safari (iPhone)

If any of these scenarios is not tested before commit, the change is not complete.

---

## Implementation guidance

When making changes to field rendering or interaction:

- Identify whether the change applies to system fields, manual fields, or both
- If it applies to one category only, the code path must be gated by a check that distinguishes the categories
- If it appears to apply to both, the change must be implemented separately in each renderer to allow future divergence
- New shared logic is permitted only for behaviors that genuinely belong to both categories (e.g., basic text wrapping, font rendering)

When in doubt, default to separate code paths. Coupling is the larger risk.

---

## Detection architecture context

This rule operates within the existing detection architecture (per `Detection_Architecture_Future_Roadmap.md`, May 12, 2026):

1. AcroForm extraction (client-side, free + pro)
2. Template match (per document hash, pro)
3. NoStringsPDF heuristic engine (server-side, pro only)
4. Azure Document Intelligence (dormant fallback, not invoked in production)

All system-found fields share the same system-field interaction contract once detection completes. The source of detection does not affect rendering or behavior. Manual fields follow their own interaction contract regardless of which other detection paths may have run.

---

## Reference

For broader product philosophy, see:
- `NoStringsPDF-Product-Bible_Apr_18.md` (with obsolescence notices)
- `NoStringsPDF-Pricing-Strategy.md` (locked)
- `Detection_Architecture_Future_Roadmap.md`
- `docs/strategic-decisions/2026-05-azure-architecture.md` (repo)
