import asyncio
import inspect

import httpx
import pytest
import respx

from job_alert.models import CompanyConfig
from job_alert.scrapers import REGISTRY, get_scraper


def scrape(type_, *companies):
    """Run adapter `type_` for each company on one AsyncClient; returns the last result."""
    async def go():
        async with httpx.AsyncClient() as client:
            for company in companies:
                result = await get_scraper(type_)(company, client)
            return result
    return asyncio.run(go())


@pytest.mark.parametrize("type_", sorted(REGISTRY))
def test_adapters_are_coroutine_functions(type_):
    assert inspect.iscoroutinefunction(REGISTRY[type_]), f"{type_}.fetch must be `async def`"


@respx.mock
def test_greenhouse(load_fixture):
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").respond(
        json=load_fixture("greenhouse_jobs.json")
    )
    company = CompanyConfig(id="acme", name="Acme", type="greenhouse", token="acme")
    jobs = scrape("greenhouse", company)
    assert [j.job_id for j in jobs] == ["4012345", "4012399"]
    assert jobs[0].title == "Senior Backend Engineer (Python)"
    assert jobs[0].location == "London, UK"
    assert jobs[0].company_id == "acme"


@respx.mock
def test_lever(load_fixture):
    route = respx.get("https://api.lever.co/v0/postings/foo").respond(
        json=load_fixture("lever_postings.json")
    )
    company = CompanyConfig(id="foo", name="Foo", type="lever", token="foo")
    jobs = scrape("lever", company)
    assert route.calls.last.request.url.params["mode"] == "json"
    assert len(jobs) == 2
    assert jobs[0].job_id == "5f1c2b9e-1111-4a2b-9c3d-aaaaaaaaaaaa"
    assert jobs[0].title == "Cloud Platform Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].department == "Infrastructure"
    assert jobs[0].url.startswith("https://jobs.lever.co/foo/")
    assert jobs[1].location == "" and jobs[1].department == ""


@respx.mock
def test_http_error_raises():
    respx.get("https://boards-api.greenhouse.io/v1/boards/nope/jobs").respond(404)
    company = CompanyConfig(id="nope", name="Nope", type="greenhouse", token="nope")
    with pytest.raises(httpx.HTTPStatusError):
        scrape("greenhouse", company)


def test_unknown_type():
    with pytest.raises(ValueError, match="Unknown scraper type"):
        get_scraper("myspace")


# --- Eightfold -------------------------------------------------------------

EIGHTFOLD_API = "https://career.mlp.com/api/apply/v2/jobs"


def _eightfold_company(**options):
    return CompanyConfig(
        id="mlp", name="MLP", type="eightfold", url="https://career.mlp.com/",
        options={"domain": "mlp.com", **options},
    )


def _serve_pages(load_fixture):
    """Answer by `start` param like the real API: 10 per page, empty past the end."""
    pages = {"0": load_fixture("eightfold_start_0.json"), "10": load_fixture("eightfold_start_10.json")}

    def handler(request):
        page = pages.get(request.url.params.get("start", "0"), {"count": 12, "positions": []})
        return httpx.Response(200, json=page)

    return handler


@respx.mock
def test_eightfold_paginates_and_maps_fields(load_fixture):
    route = respx.get(EIGHTFOLD_API).mock(side_effect=_serve_pages(load_fixture))
    jobs = scrape("eightfold", _eightfold_company())

    assert len(jobs) == 12
    assert route.call_count == 2  # start=0 and start=10; no third request once start >= count
    assert [c.request.url.params["start"] for c in route.calls] == ["0", "10"]
    first = jobs[0]
    assert first.job_id == "755958904170"
    assert first.title == "Software Engineer, Treasury Technology"
    assert first.location == "Singapore, Singapore"
    assert first.department == "Information Technology"
    assert first.url == "https://mlp.eightfold.ai/careers/job/755958904170"
    assert first.company_id == "mlp"


@respx.mock
def test_eightfold_sends_domain_and_optional_location(load_fixture):
    route = respx.get(EIGHTFOLD_API).mock(side_effect=_serve_pages(load_fixture))
    scrape("eightfold", _eightfold_company(location="Singapore"), _eightfold_company())

    with_loc, without_loc = route.calls[0].request.url.params, route.calls[-1].request.url.params
    assert with_loc["domain"] == "mlp.com" and with_loc["location"] == "Singapore"
    assert "location" not in without_loc


@respx.mock
def test_eightfold_stops_on_empty_page_even_if_count_says_more():
    route = respx.get(EIGHTFOLD_API).respond(json={"count": 500, "positions": []})
    assert scrape("eightfold", _eightfold_company()) == []
    assert route.call_count == 1


@respx.mock
def test_eightfold_refuses_to_return_truncated_results(load_fixture):
    page = load_fixture("eightfold_start_0.json")
    respx.get(EIGHTFOLD_API).respond(json={**page, "count": 100_000})
    with pytest.raises(RuntimeError, match="pages"):
        scrape("eightfold", _eightfold_company())


def test_eightfold_requires_domain():
    company = CompanyConfig(id="x", name="X", type="eightfold", url="https://career.x.com")
    with pytest.raises(ValueError, match="options.domain"):
        scrape("eightfold", company)
