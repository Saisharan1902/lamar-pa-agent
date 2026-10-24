# Prior Authorization Portal Agent

This project recreates Portal A from the supplied trace and uses Playwright to create a request from a patient JSON record. The agent uses explicit rules; it does not call an LLM or need an API key.

Portal A follows the pharmacy fields in the supplied trace and samples, including `medication_search`, `rx_bin`, `rx_pcn` and `rx_group`. The agent also validates the medical fields in Section 4 of the brief, including `payer_name`, `member_id` and `provider_npi`.

The supplied browser trace is kept outside this project and excluded through `.gitignore` because it contains authentication cookies.

## Setup

Requires Python 3.10+. Run these commands from the project folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

Start the portal:

```sh
./run_portal --port 5055
```

Open http://localhost:5055 and sign in with `demo` / `demo123`. To enable scenarios, use a URL such as `http://localhost:5055/?scenarios=flaky_start,survey_overlay`. Available scenarios are listed in `portal/scenarios.json`.

In another terminal, activate the same environment and run:

```sh
source .venv/bin/activate
./run_agent --portal-url http://localhost:5055/ --patient examples/P001_trace_exact.json --out out/result.json
```

The input must contain one patient object, or a list containing one object. The five supplied examples are in `examples/`.

The agent writes `out/result.json` and `out/result.log.jsonl`. Results include the status, reason, request reference and any escalation details:

- `SUCCESS`: the request was created and its receipt passed verification.
- `FAILED`: the portal explicitly refused the request.
- `ESCALATED`: the data, page or outcome needs a person to check it.

For Portal A, completion means reaching the new request marked **Not sent to plan**, as in the trace.

Useful options:

- `--headed` shows the browser.
- `--as-of YYYY-MM-DD` fixes the date used for validation.
- `--form-policy clarify` escalates when several compatible forms remain. The default selects the first form after skipping titles for other states.
- `--state-dir PATH` sets the submission ledger location. Keep the same ledger across reruns; an uncertain submission stays blocked to avoid creating another request.

For other credentials, set `PORTAL_USERNAME` and `PORTAL_PASSWORD`.

## Tests

```sh
python -m pytest tests -q
python tests/run_eval.py --out out/eval-rerun
python tests/run_hard_b.py --runs 3 --out out/hard-rerun
python tests/run_fresh_b.py --runs 3 --out out/fresh-rerun
```

Reruns write to `out/`, keeping the saved evidence in `results/` intact. Use a new output directory for each fresh benchmark run.

The latest run passed 222 regression checks and 77 evaluation checks. Eleven standard cases repeated three times produced identical results and logs. Evaluation checks saved values and creation counts as well as status. [Evaluation report](results/final-v3/eval_report.md).

`portal_b/` is an extra local test portal with different layouts and workflows; Lamar's hidden Portal B remains untested. See the [stress results](results/hard-b-v3/hard_report.md) and [additional test results](results/fresh-b-v3/fresh_report.md).

## Known limits

P002 uses the captured BIN `22022` unchanged. Other five-digit BINs are accepted only if they also appear in the supplied trace metadata; the agent never pads them.

The agent does not read iframes or shadow DOM. Downloaded receipts support UTF-8 text/JSON; PDFs and other formats escalate. Reviewed Spanish actions and Member ID label variants are supported; this is not general translation. Unknown required fields and ambiguous choices escalate. Portal data resets when the server restarts. Use a fresh test ledger only when intentionally resetting the synthetic portal; do not clear an uncertain live submission.


<details>
<summary>Portal A scenarios and expected responses</summary>

Enable any row with `/?scenarios=NAME`; combine names with commas. `none` disables all scenarios. `chat_widget` is on by default.

| Scenario | Behavior | Expected response |
|---|---|---|
| `chat_widget` | Widget covers Continue. | Close the widget. |
| `announcement` | Announcement lightbox. | Dismiss with Got it. |
| `bottom_banner` | Fixed bottom banner. | Close the banner. |
| `maintenance_notice` | Login notice. | Acknowledge the notice. |
| `session_warning` | Session expiry warning. | Stay signed in. |
| `session_warning_late` | Warning arrives during entry. | Stay signed in before leaving the section. |
| `survey_overlay` | Survey covers form choices. | Decline the survey. |
| `slow_drug_search` | Delayed medication results. | Wait for matching options. |
| `slow_forms` | Delayed form list. | Wait for a stable form list. |
| `random_ids` | Element IDs change. | Continue using labels and roles. |
| `native_dates` | Native date picker. | Enter the same date in ISO form. |
| `state_not_prefilled` | Empty insurance state. | Select the supplied insurance state. |
| `duplicate_patient` | Possible existing patient. | Escalate; do not create another patient. |
| `session_expiry` | Session lost mid-form. | Sign in again, then re-enter source values. |
| `flaky_start` | First attempt explicitly creates nothing. | Retry only the explicit no-creation refusal, at most twice. |
| `start_fails` | Plan refuses the request. | Return FAILED with the portal reason. |
| `no_forms` | No insurance forms found. | Escalate the insurance/form lookup. |
| `payer_eligibility` | Optional eligibility lookup. | Skip the optional eligibility offer. |
| `therapeutic_alternatives` | Suggested substitute drugs. | Continue with the prescribed drug. |
| `existing_pa` | Active prior authorization exists. | Escalate the active existing request. |
| `existing_pa_expired` | Prior authorization expired. | Continue with a new request. |
| `request_page_error` | Request GET fails to load. | Reload a known GET once; never replay a POST. |
| `native_confirm` | Native confirmation dialog. | Dismiss and escalate. |
| `other_state_forms_first` | Other-state forms appear first. | Skip other-state forms and report the selection. |
| `review_step` | Separate final review. | Verify review values before submitting. |
| `review_validation` | ZIP rejected at review. | Escalate the rejected ZIP without changing it. |

The base flow also includes medication selection from results, a skippable diagnosis, progressively revealed cards, live form search and field-level server validation.

</details>
