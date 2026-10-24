# Design write-up

## Approach

The agent uses Playwright rules to find fields, enter patient data, handle popups and check the result. It finds controls through labels, headings and ARIA roles. Fixed browser settings, `--as-of` for the validation date, bounded waits and logs without timestamps make runs comparable. Repeatability tests require identical results and logs.

## Why no LLM

The structured input and narrow workflow made rules a practical choice. Decisions are explicit and testable, without model latency, API costs or another service dependency. The tradeoff is that unfamiliar wording can cause a valid case to escalate. An LLM could help interpret unfamiliar labels, but would still need deterministic checks around patient values and submission.

## Data contract

Portal A follows the pharmacy trace and sample patients. The agent also validates the medical fields in Section 4. Completion means reaching a new request marked **Not sent to plan**, as in the trace. The agent never clicks Send to Plan.

P002's BIN `22022` is accepted unchanged because that exact value appears in the supplied metadata. The agent never adds a leading zero.

## Validation and escalation

Validation happens before the browser opens. The agent reads entered values back, checks exposed review details and requires read-only values to match. Missing required data, ambiguous choices, changed values, unfamiliar confirmations and uncertain outcomes escalate with a reason and next step.

- **SUCCESS:** a verified request reference and matching patient details. Downloaded text or JSON receipts must match every supplied field.
- **FAILED:** the portal explicitly refused the request.
- **ESCALATED:** a person needs to resolve the data, workflow or uncertain outcome.

## Avoiding duplicate requests

A local ledger records the attempt before Start or Submit. Confirmed outcomes are cached; uncertain outcomes block reruns. Retries require explicit evidence that nothing was created. A rejected draft version allows one refresh; continuing requires a changed version and every supplied value to still match. Production would also need server-side idempotency or reliable reconciliation.

## What may break on Portal B

Validation, field matching and submission checks are designed for reuse, but recognized labels, button wording and result messages remain limited. Unknown controls, iframes, shadow DOM and PDF or image receipts may cause valid workflows to escalate. Lamar will test the frozen agent on its hidden Portal B; I have not seen it.

## Tests

Tests check saved values and creation counts. The evaluation passed 77 checks; 11 cases repeated three times produced identical results and logs. Regression tests passed 222/222. My additional local portal tests different layouts and interruptions, but does not establish performance on Lamar's Portal B.

## With another week

1. Study the actual Portal B failures and prioritize valid workflows that escalate.
2. Split the runner into form selection, submission and verification components.
3. Add redacted escalation screenshots and safer reconciliation after uncertain outcomes.
4. Evaluate an LLM fallback for unfamiliar labels, keeping it only if completion improves without compromising safety or repeatability.
