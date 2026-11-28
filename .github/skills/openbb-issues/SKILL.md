---
name: "openbb-issues"
description: "Turn an approved Spec Kit tasks.md into GitHub sub-issues on the rashmijain02 Portfolio Intelligence Engine board, with Phase, Lane and Type set. Use after openbb-spec reaches gate G1, or when asked to sync tasks to issues."
compatibility: "Requires gh authenticated as rashmijain02 with the project scope"
metadata:
  author: "rashmijain02"
  strategy: "docs/dev-strategy.md"
---

# openbb-issues: tasks to issues (end of Phase 1)

Spec Kit 1.4 has no built-in `taskstoissues`. This skill does that job for this repository,
because issues here must also be sub-issues of the parent and items on the board.

Model (D1): best available for the task, named explicitly; stop if none is suitable.

## Board

| Setting | Value |
|---|---|
| Board | https://github.com/users/rashmijain02/projects/1/views/1 (`--owner rashmijain02`, number `1`) |
| Project ID | `PVT_kwHOAE4h8M4BqDs2` |
| Status field | `PVTSSF_lAHOAE4h8M4BqDs2zhocetk` (Todo `f75ad846`, In Progress `47fc9ee4`, Done `98236657`) |
| Phase field | `PVTSSF_lAHOAE4h8M4BqDs2zhoceu4` (M0 `369a1421`, P0 `9d94cce8`, P1 `040321ec`, P2 `62b45453`, P3 `3cb0e2f8`, M4 `1ccac243`) |
| Lane field | `PVTSSF_lAHOAE4h8M4BqDs2zhocevA` (A-Data `76fa01d6`, B-Analytics `942abc23`, C-App+Paper `0a094b38`, D-Widgets+QA `8f2251e7`, PM `9d82918b`, QA `3614f452`) |
| Type field | `PVTSSF_lAHOAE4h8M4BqDs2zhocevE` (Epic `6a4a1e4d`, Feature `9e7e5af3`, Task `16a0f716`, Bug `672eea10`) |

If a field or option ID does not resolve, re-read them with
`gh project field-list 1 --owner rashmijain02 --format json` and update
`scripts/proj_fields.json`; never write to any other project.

## Granularity (D4)

- One **sub-issue per user story** in `tasks.md`, not one per task.
- The sub-issue body carries that story's tasks as a checklist (`- [ ] T001 …`), the acceptance
  criteria from `spec.md`, and a link to `specs/gh-NN-slug/`.
- Title: `[<area>] <story title>`; labels follow the parent issue's labels.

## Steps

1. Read `specs/gh-NN-slug/tasks.md` and `spec.md`. List the stories you will turn into issues
   (title, task count, proposed Phase/Lane/Type) and show the list to the user.
2. **If more than 3 issues** will be created, get the user's explicit "yes" for that count
   before creating any. Otherwise proceed.
3. For each story:
   ```bash
   url=$(gh issue create --repo rashmijain02/OpenBB --title "<title>" --body-file <tmp> --label <labels>)
   gh project item-add 1 --owner rashmijain02 --url "$url" --format json --jq .id     # -> item id
   gh project item-edit --project-id PVT_kwHOAE4h8M4BqDs2 --id <item> --field-id <field> --single-select-option-id <option>
   ```
   Then link it as a sub-issue of the parent (REST):
   ```bash
   gh api -X POST repos/rashmijain02/OpenBB/issues/<parent>/sub_issues -F sub_issue_id=<child issue database id>
   ```
   (`gh api repos/rashmijain02/OpenBB/issues/<child> --jq .id` gives the database id.)
4. Write the new numbers back into `tasks.md` next to each story heading as `(#NN)` so Phase 2
   can cite them in commits. This is a plan annotation, not status (D3).
5. Report the created issues as `#NN (title)` and remind the user of the next step: Claude Code,
   "Use openbb-execute for #<parent>".

Never set Status to In Progress here; the executor claims with `pi_claim.py` in Phase 2.
