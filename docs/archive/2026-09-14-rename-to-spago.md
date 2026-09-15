# Rename PatentChem → SPAgo Implementation Plan

> Archived 2026-09-16 (completed 2026-09-14; no open items).

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rename the project from PatentChem to SPAgo (small molecule patent analysis GO) across all repository documentation.

**Architecture:** Documentation-only rename in the current repo root (`README.md`, `AGENTS.md`, `PROMPT.md`). Product name becomes `SPAgo`; package/path identifiers become `spago`. Domain phrases like "patent chemistry" stay unchanged.

**Tech Stack:** Markdown documentation only (no application code yet).

**Status:** COMPLETED (2026-09-14)

---

### Task 1: Inventory rename targets — DONE

**Mappings applied**

| From | To |
|------|----|
| `PatentChem` | `SPAgo` |
| `patentchem` | `spago` |
| `patentchem-app` | `spago-app` |
| Product tagline | **Small molecule patent analysis GO** |

**Left unchanged:** domain language ("patent chemistry", "Patent Chemistry Viewer", etc.)

---

### Task 2: Update README.md — DONE

- Title: `# SPAgo`
- Tagline: `**Small molecule patent analysis GO**`
- All product-name and path identifiers renamed (`cd spago`, `spago/`, `SPAgo Core`, etc.)

---

### Task 3: Update AGENTS.md — DONE

- Header: `SPAgo Engineering Rules`
- Mission line includes expansion: `SPAgo (small molecule patent analysis GO)`
- Remaining product references use `SPAgo`

---

### Task 4: Update PROMPT.md — DONE

- Header/intro use `SPAgo` + expansion
- `spago-app`, `cd spago` applied
- Extension/Web App wording uses `SPAgo`

---

### Task 5: Post-conduction verification — DONE

- Grep for `PatentChem|patentchem|PATENTCHEM` in project docs: **none remaining**
- Plan file itself retains historical name for traceability
