# Difficult mock Portal B results

This is a local stress test, not Lamar’s hidden portal. The agent was frozen before the challenge run.
A safe escalation is reported separately from successful completion of a valid workflow.

- Safety: 72/72 runs; unsafe successes: 0.
- Clean workflow completion: 48/48 runs.
- Goal met: 24/24 scenarios.
- Identical results: 24/24; identical logs: 24/24.
- Median run: 19.41s; slowest: 32.73s.

| Scenario | Goal | Observed | Safety | Completion / expected stop | Median s |
|---|---|---|---|---|---|
| baseline | SUCCESS | SUCCESS | PASS | PASS | 19.31 |
| dependent_subscriber | SUCCESS | SUCCESS | PASS | PASS | 20.79 |
| locked_policy_fields | SUCCESS | SUCCESS | PASS | PASS | 17.49 |
| rotating_csrf | SUCCESS | SUCCESS | PASS | PASS | 25.38 |
| revision_conflict | SUCCESS | SUCCESS | PASS | PASS | 21.47 |
| queued_acceptance | SUCCESS | SUCCESS | PASS | PASS | 20.31 |
| queued_denial | FAILED | FAILED | PASS | PASS | 20.43 |
| spa_review | SUCCESS | SUCCESS | PASS | PASS | 19.4 |
| background_long_poll | SUCCESS | SUCCESS | PASS | PASS | 30.24 |
| case_sensitive_member_rewrite | ESCALATED | ESCALATED | PASS | PASS | 17.4 |
| day_first_review | SUCCESS | SUCCESS | PASS | PASS | 19.37 |
| localized_actions | SUCCESS | SUCCESS | PASS | PASS | 19.34 |
| unicode_label | SUCCESS | SUCCESS | PASS | PASS | 19.29 |
| chips_procedure | SUCCESS | SUCCESS | PASS | PASS | 19.85 |
| keyboard_commit | SUCCESS | SUCCESS | PASS | PASS | 20.16 |
| withdrawn_procedure | ESCALATED | ESCALATED | PASS | PASS | 16.92 |
| download_only_receipt | SUCCESS | SUCCESS | PASS | PASS | 19.44 |
| expiry_after_commit | ESCALATED | ESCALATED | PASS | PASS | 19.3 |
| cross_origin_signin | ESCALATED | ESCALATED | PASS | PASS | 6.45 |
| draft_receipt | ESCALATED | ESCALATED | PASS | PASS | 19.22 |
| conditional_attachment | ESCALATED | ESCALATED | PASS | PASS | 16.31 |
| history_on_review | SUCCESS | SUCCESS | PASS | PASS | 19.16 |
| combined_handoff | SUCCESS | SUCCESS | PASS | PASS | 32.61 |
| combined_conflict | ESCALATED | ESCALATED | PASS | PASS | 22.36 |

## Problems exposed
