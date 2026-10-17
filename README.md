# cloudy-job-notif

Watches company careers pages and emails a digest of new roles: relevant ones highlighted,
everything else still listed so nothing slips through. Plan: Python + AWS serverless
(Lambda, DynamoDB, EventBridge Scheduler, SES), CDK in Python, ~$0/month.

```
Scheduler ─▶ Lambda ─▶ scrapers ─▶ diff vs store ─▶ keyword matcher ─▶ HTML digest ─▶ SES
```

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest                       # 5 pass, 17 fail until you finish Phase 1
```
(Lambda will run Python 3.13; code here targets >=3.10 so your local 3.10 works.)

## Phase 1 — your exercises (in this order)
| # | File | Tests | What |
|---|------|-------|------|
| 1 | `src/job_alert/diff.py` | `pytest tests/test_diff.py` | `compute_diff`, `is_suspicious_empty` |
| 2 | `src/job_alert/matcher.py` | `pytest tests/test_matcher.py` | keyword relevance + reason string |
| 3 | `src/job_alert/scrapers/lever.py` | `pytest tests/test_scrapers.py -k lever` | Lever adapter (copy `greenhouse.py`'s pattern) |
| 4 | — | `pytest tests/test_runner.py` | should pass for free once 1–2 are done |

Then put your real companies in `config/companies.yaml` and run:
```bash
python -m job_alert.cli run --dry-run   # writes out/digest.html, doesn't save state
python -m job_alert.cli run             # saves .data/store.json; run again → 0 new
```

Already provided: models (`models.py`), config loading, Greenhouse adapter, local JSON
store, orchestration (`runner.py`), email template, CLI.

## Adding a company's own careers site
Most "own website" careers pages are a hosted platform underneath. Identify it once, and one
adapter then covers every company on that platform.

1. **Look for a known platform.** Open a job and check the URL and page source:
   `greenhouse.io`, `lever.co`, `eightfold` / `&domain=…&pid=…`, `myworkdayjobs.com`,
   `ashbyhq.com`, `successfactors`, `icims`, `phenom`.
2. **Find the JSON the page loads.** DevTools → Network → Fetch/XHR, reload, filter for
   "job". Right-click the request → *Copy as cURL* and replay it in a terminal. If it works
   without cookies, write a platform adapter for it (`scrapers/eightfold.py` is the model:
   endpoint, params, pagination, field mapping).
3. **No JSON API** (JS-only, bot protection): out of scope for now. That needs a headless
   browser (Playwright in a container Lambda).

Save a trimmed real response under `tests/fixtures/` and write the test first, as in `tests/test_scrapers.py`.

Supported platforms (`type:` in config):

| Type | Source | Config |
|---|---|---|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | `token` |
| `lever` | `api.lever.co/v0/postings/{token}?mode=json` | `token` |
| `eightfold` | `{url}/api/apply/v2/jobs`, 10 per page | `url`, `options.domain`, optional `options.location` |

## Next phases
2. **AWS** — `infra/` CDK app: DynamoDB table, Lambda (`handler.py` calling `runner.run`),
   EventBridge Scheduler, SES identity. Add `DynamoStore` implementing the `Store` protocol
   in `store.py`, and `send_ses()` in `notifier.py`.
   No account IDs in the repo: the CDK app reads `CDK_DEFAULT_ACCOUNT` / `CDK_DEFAULT_REGION`,
   which the CDK CLI fills from your AWS profile. Deploy with
   `AWS_PROFILE=<your-profile> cdk deploy` (region: `ap-southeast-2`).
3. **Hardening** — more platform adapters (Workday, Ashby, …) as your company list needs them, CSV of all open roles, CloudWatch alarm,
   AWS Budget, structured logging.
4. **Extras** — Claude Haiku relevance scorer on new roles, Step Functions fan-out, CI deploy.
