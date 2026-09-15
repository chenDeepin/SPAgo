# SPAgo UI imagegen prompts

> Archived 2026-09-16: historical record of how the two design drafts in
> `docs/design/` were generated. Superseded as a reference by
> `docs/design/2026-09-14-ui-direction.md`; the images stay tracked in `docs/design/`.

Mode: built-in image_gen. Date: 2026-09-14. All scientific content is illustrative.

## Workspace

```text
Use case: ui-mockup
Asset type: SPAgo desktop web application UI design draft, first milestone patent chemistry viewer.
Primary request: Create a polished, realistic flat desktop application screenshot at wide 16:10 aspect ratio, high resolution, precise readable UI, suitable for frontend implementation reference. It is a scientific working application, dense but calm, not a marketing website. English UI. White background, very pale gray canvas, deep slate text, restrained teal accent #087F8C, thin gray dividers, 6px corners, minimal shadows, professional sans serif.
Composition: full application, no device frame or perspective. Top bar 56px high: wordmark "SPAgo" left, small project selector "Research project", right "Save to project" primary teal button. Under it a compact patent number search row containing "DEMO-PATENT-A" and one "Search" button. Upper right understated badge "DESIGN DRAFT · DEMO DATA". Main working area has 232px left navigation showing one selected "Patent family A" with metadata "3 documents", and below three document entries "DEMO-PATENT-A", "DEMO-PATENT-B", "DEMO-PATENT-C"; no invented real patent IDs or companies. Central broad column about 760px: heading "Patent family A", small subtitle "Illustrative dataset", document count, toolbar "Compounds · 24", "Columns", "Export". Table with checkbox, "Structure", "Compound", "Patent label", "Evidence". Show 5 spacious rows with small schematic chemistry placeholders visibly marked "Structure placeholder", labels C-001 through C-005, Example 01 through Example 05, and evidence links "Source record". First row selected in pale teal. Footer "1–24 of 24". No biological activity columns at this milestone.
Right 390px evidence inspector separated by vertical line, header "Evidence" with close icon. Below "C-001 / Example 01", compact provenance label "Database curated", a field list "Document: DEMO-PATENT-A", "Source: Demo fixture", "Locator: Not provided". An inset excerpt card reads "Illustrative source record" and "Original patent passage unavailable." Under it a text link "Open source", then folded section "Chemical identity". Bottom global fine print "All identifiers and structures are illustrative." Make visual hierarchy meticulous, use realistic text size and generous column spacing. Footer source availability unobtrusive.
Constraints: Main hierarchy search → family → compounds → evidence. Show evidence as metadata and honest missing locator, never a fake PDF with fabricated page numbers. No AI panel or AI button, no analytics charts, no dashboard metric cards, no gradients, no giant title, no full-height tools rail. No actual scientific claims or real activity numbers. Image is a UI concept, chemistry placeholders not factual structures.
```

## Structure search initial prompt

```text
Use case: ui-mockup
Asset type: SPAgo desktop UI draft for NEXT milestone structure search dialog.
Primary request: Create a high resolution realistic flat desktop web application screenshot, wide 16:10, matching this visual system: white panels on very pale gray canvas, slate text, teal #087F8C actions, thin gray dividers, 6px corners, professional sans serif, quiet scientific workspace. No perspective or device frame.
Composition: SPAgo app visible dimmed behind a large centered structure search dialog 920px wide, occupying most of the image. Background has compact top search, patent family list at left and compound table in center, no AI panel. Upper outside-dialog corner badge "NEXT MILESTONE · DESIGN DRAFT". Dialog header "Structure search" and close X. Under header left 65% is a white chemical drawing canvas with a slim editor toolbar showing simple bond, ring, undo, redo, clear icons; show a simple schematic ring outline labeled "Illustrative query" and small footer "Structure editor". Right 35% contains stacked form sections: "Search mode" with radio buttons "Exact", "Substructure" selected in teal, "Similarity"; "Search scope" with selected "Current family"; "Stereochemistry" with "Preserve where specified"; secondary text "Draw or paste a structure, then run search." Under canvas a collapsed "Paste SMILES" disclosure. Dialog footer with neutral "Cancel" and one primary teal "Run search" button. Small note "Editing does not start a search." 
Background compound table includes only demo IDs and structure placeholders. No real patent numbers or activity values.
Constraints: this must look implementable, highly readable, purposefully restrained. No marketing graphics, no molecular wallpaper, no huge dashboard cards, no auto-search, no AI invented structures. Use exact text as provided. Only one Run search primary control. Label as future design, not currently implemented functionality.
```

## Structure search correction

```text
Use case: precise-object-edit
Edit the most recent SPAgo structure-search UI mockup. Preserve the entire centered modal layout, editor canvas, typography, colors, and Run search / Cancel controls. Correct only scope drift: remove "All families" and "Selected families" from Search scope leaving only "Current family". Remove "Ignore stereochemistry", leaving "Preserve where specified" as static policy text without radio. In background top bar replace Search / Families / Compounds / Analytics navigation with a single "Research project" selector; background search placeholder must read "Enter patent publication number". Remove background "Advanced search" and replace background table Status / Active badges with "Evidence" / "Source record". Keep NEXT MILESTONE · DESIGN DRAFT badge. All background family and compound rows are demo data. Preserve the flat screenshot and centered modal, do not add other controls.
```

