# 1,681 MCQ database import report

- Database: `placement_platform`
- Transaction: **COMMITTED**
- CSV SHA-256: `5704181e9d6b84b488f6a137872246c4fcb7bab24ce922f7e786a9aa993996a0`
- CSV rows: **1681**
- Database MCQ rows before/after: **1917 / 1917**
- Intended MCQ records permanently updated: **1681**
- Successful updates: **1681**; failed: **0**; skipped: **0**
- Missing DB IDs: **0**; duplicate CSV IDs: **0**
- Extra DB MCQ IDs not in the CSV (out of scope): **236**
- Invalid option sets: **0**; invalid correct answers: **0**; missing explanations: **0**
- PENDING import review records added: **1681**; question status history rows changed: **0**
- Questions deleted/created: **0 / 0**; original question IDs preserved: **yes**
- Question rows updated: **1681**; MCQ content rows updated: **1681**
- Option rows deleted/replaced: **3438 / 6911**; topic/subtopic mappings deleted/inserted: **1681 / 1681**
- Backup export: [`1681_mcq_db_backup_before.json`](./1681_mcq_db_backup_before.json)

## Pre-update audit

- CSV rows / unique IDs: 1681 / 1681
- DB MCQ row count: 1917
- Matching IDs: 1681
- Missing IDs: 0
- Extra IDs outside the source file: 236
- Rows missing required manual fields: 0
- Manual option counts: {4: 1494, 5: 187}
- Manual difficulty distribution: {'EASY': 720, 'MEDIUM': 961}
- Existing target statuses: {'REVIEW': 1676, 'ARCHIVED': 5}
- Latest existing review decisions: {'PENDING': 1681}

## Post-update audit

- Difficulty distribution: {'EASY': 720, 'MEDIUM': 961}
- Topic distribution: {'Algorithms': 10, 'Artificial Intelligence & ML': 10, 'Cloud Computing': 10, 'Computer Fundamentals': 20, 'Computer Networks': 14, 'Cybersecurity': 10, 'Data Structures': 10, 'Database Management': 10, 'Logical Reasoning': 654, 'Operating Systems': 10, 'Programming Concepts': 30, 'Quantitative Aptitude': 456, 'Software Engineering': 40, 'System Design': 10, 'Technical Concepts': 36, 'Verbal Ability': 341, 'Web Technologies': 10}
- Status distribution: {'REVIEW': 1676, 'ARCHIVED': 5}
- Reconstructed repeated-stem groups detected: 12
- Project publication-validator duplicate blockers: 44 questions; they remain behind REVIEW/ARCHIVED governance and were not published.
- Coding questions before/after: 290 / 290
- Unrelated tables and out-of-scope question rows unchanged: **yes**

## Validation details

- Every CSV ID matched an existing MCQ row; all non-empty source values came from the manual columns.
- Every updated question has non-empty text/explanation, unique options A-D (and E when present), a correct key matching exactly one stored option, a valid difficulty, and one existing same-track topic/subtopic mapping.
- No question rows were inserted or deleted. Existing REVIEW/ARCHIVED statuses were retained; no question was set to PUBLISHED.
- The project publication validator was executed for every updated question. Duplicate-content findings were retained as workflow blockers; all other validation errors would have rolled back the transaction.
- Protected table hashes, out-of-scope rows, coding-question count/data, and question status-history snapshots were compared before and after.

Post-commit checks passed.
