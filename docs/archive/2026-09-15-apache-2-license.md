# Apache-2.0 licensing for SPAgo

> Archived 2026-09-16 (done; `LICENSE`, `NOTICE` and `THIRD_PARTY_NOTICES.md` are
> tracked and current).

Date: 2026-09-15  
Status: **done** (files written; not committed unless requested)

## Goal

Publish SPAgo under Apache License 2.0, with package metadata aligned and a third-party notices inventory so redistributors and adopters can see included tools’ licenses.

## Completed

| Item | Result |
| --- | --- |
| Root `LICENSE` | Official Apache-2.0 text from apache.org |
| Root `NOTICE` | Copyright 2026 chenDeepin + pointers |
| `THIRD_PARTY_NOTICES.md` | Direct Python/JS deps, containers, fixtures, data/API ToS |
| `services/core/pyproject.toml` | `Proprietary` → `Apache-2.0` |
| `apps/web/package.json` | `"license": "Apache-2.0"` |
| Root `README.md` | Top badge line + `# License` section |
| `services/core/README.md` | License pointer |
| Chrome extension | Covered by root license; no store-facing description change |
| `AGENTS.md` §23 + §36 | Ongoing rule: new tools update license notice files in the same change |

## Verification

- [x] `LICENSE` present and Apache-2.0
- [x] `NOTICE` + `THIRD_PARTY_NOTICES.md` present
- [x] No remaining `Proprietary` in package metadata
- [x] README documents License and third-party notices
- [x] `AGENTS.md` requires notice updates when dependencies change
- [x] Unrelated dirty product-readiness files left untouched
- [ ] Git commit (not done; await user request)

## NEXT (optional)

- CONTRIBUTING.md + DCO
- CI job to refresh license-checker / pip-licenses summaries on release
- Confirm copyright holder string if publishing under an organization name
