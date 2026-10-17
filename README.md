# cloudy-job-notif

Watches company careers pages and emails a digest of new roles: relevant ones highlighted,
everything else still listed so nothing slips through. Python + AWS serverless
(Lambda, DynamoDB, EventBridge Scheduler, SES), infrastructure in CDK (Python), ~$0/month.

```
Scheduler ─▶ Lambda ─▶ scrapers ─▶ diff vs store ─▶ keyword matcher ─▶ HTML digest ─▶ SES
```

## Setup
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest
```
Targets Python >=3.10 locally; Lambda runs Python 3.13.

## Run locally
Put the companies you want to watch in `config/companies.yaml`, then:
```bash
python -m job_alert.cli run --dry-run   # writes out/digest.html, doesn't save state
python -m job_alert.cli run             # saves .data/store.json; run again → 0 new
```

## Deploy
No account IDs live in the repo: the CDK app reads `CDK_DEFAULT_ACCOUNT` /
`CDK_DEFAULT_REGION`, which the CDK CLI fills from your AWS profile.
```bash
AWS_PROFILE=<your-profile> cdk deploy
```

## Supported platforms
`type:` in `config/companies.yaml` picks the scraper adapter:

| Type | Source | Config |
|---|---|---|
| `greenhouse` | `boards-api.greenhouse.io/v1/boards/{token}/jobs` | `token` |
| `lever` | `api.lever.co/v0/postings/{token}?mode=json` | `token` |
| `eightfold` | `{url}/api/apply/v2/jobs`, 10 per page | `url`, `options.domain`, optional `options.location` |

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
3. **No JSON API** (JS-only, bot protection): not supported; that needs a headless browser.

Save a trimmed real response under `tests/fixtures/` and write the test first, as in
`tests/test_scrapers.py`.
