# MCQ Backend Eligibility Diagnostic

**Executed:** 2026-09-30 22:08:12 +05:30  
**Database:** `placement_platform`  
**Mode:** Read-only. No mock-generation endpoint was called; no database writes were made.

## Summary

The canonical mock eligibility predicate returns **0 eligible and 1,681 blocked** target MCQs. The selector is consistently enforcing the platform's current governance and provenance gates; the evidence does not indicate a selector defect. The 1,681-row detail, including each canonical evaluator's exact blocker strings, is in [mcq_backend_eligibility_diagnostic.csv](./mcq_backend_eligibility_diagnostic.csv).

| Measure | Count |
| --- | ---: |
| Reconstructed target MCQs | 1,681 |
| Canonically eligible | 0 |
| Blocked / ineligible for mock selection | 1,681 |
| Review-required (latest decision PENDING) | 1,681 |
| REVIEW status | 1,676 |
| ARCHIVED status | 5 |
| PUBLISHED status | 0 |

The blocker counts below are overlapping: one question may have several blockers.

## Canonical implementation and selection trace

The canonical implementation is `app.services.mock_eligibility_service`: its shared SQL predicate is consumed by blueprint and generic selection paths, and `evaluate_mock_eligibility()` supplies per-question blocker details. No eligibility rules were reimplemented for this audit.

| Actual canonical gate | Current target result |
| --- | --- |
| Publication and latest review | Mock eligibility requires PUBLISHED and latest review APPROVE. All 1,681 latest reviews are PENDING; 1,676 statuses are REVIEW and 5 are ARCHIVED. |
| MCQ structure and answer | Required MCQ record, valid option set, and correct answer matching a stored option. Prior import integrity checks found no target structural option or answer defects. |
| Difficulty and taxonomy | Valid difficulty and same-track topic/subtopic taxonomy are required. Prior integrity checks found no target difficulty or taxonomy defects. |
| Provenance | Traceable source is not sufficient for SCRAPED questions: the canonical check also requires scraped-source authorization evidence. 1,386 targets are SCRAPED and blocked by that authorization gate; 295 are CUSTOM. |
| Duplicates / governance | Duplicate-content checks remain in force. The 44 previously identified duplicate-content questions are still returned as duplicate blockers. |
| Other gates | The shared predicate also applies its current report/review governance constraints; the CSV preserves exact evaluator blocker strings for every target. |

### Blueprint and generic selector

- There are 14 blueprints, and **none is ACTIVE**; no active/effective blueprint is available to users.
- Blueprint 19's required mix is 2 Quantitative, 2 Logical Reasoning, and 1 Verbal MCQ. Its track/topic candidate counts before canonical eligibility are 456, 654, and 341 respectively; after the shared eligibility predicate each pool is zero.
- A read-only generic selection probe with MCQ, track 1, topic 1, EASY, requested count 1 narrowed 1,917 MCQs to 1,687 by track, 456 by topic, 157 by difficulty, then **0 canonically eligible**. It returned HTTP 409 (`available=0`, `requested=1`).
- No mock API or mock-generation endpoint was called. No mock tests were created.
- No eligible control question exists: the database-wide canonical eligible MCQ count is zero.

## Blocker distribution

| Exact canonical blocker category | Questions |
| --- | ---: |
| Latest question review decision is PENDING | 1,681 |
| Question status is REVIEW, not PUBLISHED | 1,676 |
| Question status is ARCHIVED, not PUBLISHED | 5 |
| Scraped-source authorization is not evidenced in source URL/notes | 1,386 |
| Duplicate-content blocker | 44 |

Status and review counts are also reported separately above; all categories can overlap. The per-question CSV contains the complete set of returned blocker messages rather than replacing them with a locally invented classification.

### Duplicate blocker verification

The canonical evaluator still reports duplicate-content blockers for all 44 questions:

`1110, 1120, 1133, 1235, 1238, 1306, 2884–2911, 3002, 3003, 3004, 3005, 3094, 3429, 3434, 3513, 3525, 3526`

These remain blocked; none was removed, merged, repointed, or made eligible by the audit.

## Samples and explanation

| Question | Current state | Canonical result |
| --- | --- | --- |
| 2001 | REVIEW, MEDIUM, Quantitative Aptitude / Alligation & Mixture, SCRAPED | Blocked: status is REVIEW rather than PUBLISHED; scraped-source authorization is not evidenced in source URL/notes; latest review is PENDING. |
| Duplicate-blocker set above | REVIEW or ARCHIVED | Duplicate blocker remains present; questions were not merged or deleted. |

The reconstructed content itself has no observed selector-incompatible option, answer, difficulty, or taxonomy defects. Passing those structural checks does not satisfy publication/review approval or the scraped-source authorization requirements, so it does not make these records mock-eligible.

The existing admin difficulty-review route remains limited to PENDING reviews whose notes start with `QUESTION_CLASSIFICATION:`. Reconstruction imports use `MCQ_RECONSTRUCTION_IMPORT:v1:` and now have a separate governed content-review route; classification review semantics were not changed. The publication route remains separate and does not automatically run when content is approved.

## Distribution and integrity observations

### Status

| Status | Count |
| --- | ---: |
| REVIEW | 1,676 |
| ARCHIVED | 5 |
| PUBLISHED | 0 |

### Difficulty

| Difficulty | Count |
| --- | ---: |
| EASY | 720 |
| MEDIUM | 961 |
| HARD | 0 |

No invalid target difficulty was found in the read-only integrity checks.

### Topic

| Topic | Count |
| --- | ---: |
| Algorithms | 10 |
| Artificial Intelligence & ML | 10 |
| Cloud Computing | 10 |
| Computer Fundamentals | 20 |
| Computer Networks | 14 |
| Cybersecurity | 10 |
| Data Structures | 10 |
| Database Management | 10 |
| Logical Reasoning | 654 |
| Operating Systems | 10 |
| Programming Concepts | 30 |
| Quantitative Aptitude | 456 |
| Software Engineering | 40 |
| System Design | 10 |
| Technical Concepts | 36 |
| Verbal Ability | 341 |
| Web Technologies | 10 |

The read-only integrity checks recorded 2,207 questions overall (1,917 MCQ and 290 coding), all 1,681 target IDs present with MCQ records, no missing or duplicate question IDs, and no target option-set, correct-answer, difficulty, or taxonomy defects. No target status drift from the verified imported state was observed. The previous import baseline also recorded no changes to status history. The audit did not write to or mutate questions, coding questions, attempts, user data, analytics, or other tables.

## Backend tests

The current test configuration was inspected. Collection found 109 tests. The broad safe run completed with **76 passed, 0 failed, 12 skipped, and 1 warning** (Starlette/httpx `TestClient` deprecation). Database integration tests that create/delete fixture data were not run against production; the broad safe subset was used to avoid writes. A focused MCQ validation selection completed with **37 passed**. No backend source code was changed for this audit.

## Outcome

The reconstructed records are currently **not usable by canonical mock selection**. The immediate blockers are outstanding review/publication governance for every target, scraped-source authorization evidence for the SCRAPED subset, and duplicate-content governance for 44. All blueprints are inactive as well. Do not publish, alter, merge, or create replacement questions as part of this diagnostic.

**Database changes made: NONE.**  
**Mock tests created: NONE.**

## Follow-up governed review workflow

Implemented on 2026-09-30 after the read-only diagnostic:

- `POST /admin/questions/{question_id}/content-review` permits the existing authenticated `ADMIN` role to decide only the latest pending reconstruction-import review for an MCQ in `REVIEW`. It supports `APPROVE` and `REJECT`, records the authenticated reviewer and notes, preserves the import note, and rejects stale, already-decided, or wrong-type reviews.
- Approval records only the content-review decision; it does not publish or set mock eligibility. Rejection uses `transition_question_status()` and writes the established status-history entry.
- Reconstruction questions with a pending content review cannot be published through the existing transition until that review is approved. Once approved, publication still runs the existing publication validator and status transition. Provenance and duplicate requirements remain unchanged.
- `GET /admin/questions/{question_id}` now includes review/source/taxonomy details, open reports, duplicate matches and states, provenance/traceability summaries, and `evaluate_mock_eligibility()`'s exact canonical blockers.
- `GET /admin/questions/reconstruction-review-queue` is a read-only, paginated queue of latest pending reconstruction reviews in `REVIEW`; it does not perform bulk decisions.
- There is no reviewer-assignment field or assignment workflow in the current review model; access is therefore limited to the existing `require_admin` authorization, with reviewer identity recorded from the authenticated user. No provenance evidence is fabricated and duplicate resolution remains separate.

Post-change read-only canonical re-audit: **0 / 1,681 eligible**, **1,681 / 1,681 blocked**, and **44 duplicate-content blockers**. The global canonical eligible MCQ count remains zero. The canonical eligibility service and SQL predicate were not modified.

Targeted test result: **45 passed, 0 failed**, 1 existing Starlette/httpx deprecation warning (plus 2 successful unittest subtests). Database-writing integration tests were not run against the configured database.

**Database writes during this implementation and validation: NONE.**

There is no existing duplicate-resolution route/service in the inspected backend. The detail and queue APIs expose persisted `duplicate_matches` plus exact content-duplicate blockers and counterpart review state, but do not resolve them. Duplicate resolution remains a separate governance task; no source authorization or duplicate resolution was fabricated.

## Isolated end-to-end pipeline verification

Executed 2026-09-30 in an ephemeral Docker MySQL 8.4.11 database named `placement_mock_pipeline_test`. The test database was initialized by reflecting the **27-table schema only** from `placement_platform`; no production question or user rows were copied. Only synthetic reference rows and test fixtures were inserted. The container was removed after test completion.

- Synthetic question ID: **245**; synthetic mock test ID: **23** (IDs are local to that disposable run).
- Lifecycle passed: `REVIEW → APPROVE → PUBLISHED → ELIGIBLE → SELECTED → MOCK CREATED`.
- The admin detail endpoint returned the pending reconstruction review; unauthenticated and student review requests were rejected; wrong-type and repeat decisions were rejected.
- Approval stored the authenticated admin reviewer, retained the reconstruction-import note, and left status `REVIEW`. Publication before approval was rejected. Governed publication afterward used `transition_question_status()` and passed `validate_question_for_publication()`.
- Canonical per-question evaluator: eligible. Shared canonical SQL: eligible. `count_mock_eligible("MCQ")`: 1.
- Generic selector selected only question 245. The active test blueprint was valid and ready, and blueprint selection selected question 245.
- The actual blueprint mock-creation service persisted one ordered mock-question row. Reopening the same mock twice returned the same question set.
- Negative gates passed in rollback-only test savepoints: REVIEW status, PENDING review, missing SCRAPED-source authorization, unresolved duplicate, invalid option count, and invalid correct answer all made the canonical evaluator reject the synthetic question.
- Full backend suite in the isolated MySQL: **124 passed, 0 failed**, 3 warnings (one Starlette/httpx `TestClient` deprecation and two existing JWT HMAC-key length warnings).

The runner captured a production read-only fingerprint immediately before and after the isolated suite. Counts were identical: 2,207 questions (1,917 MCQ, 290 coding), 7 mock tests, and 35 mock-test question links. All 1,681 target IDs remained present and the SHA-256 over their question content, options, review decisions/notes, and status history was unchanged. **Production database changes: NONE.**
