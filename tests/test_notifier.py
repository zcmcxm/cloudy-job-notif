from datetime import datetime, timezone

from conftest import make_job

from job_alert.models import CompanyConfig, CompanyResult, MatchedJob, MatchResult, RunReport
from job_alert.notifier import open_since, render_html, subject


RELEVANT = MatchResult(relevant=True, reason="title: python")


def _report():
    acme = CompanyConfig(id="acme", name="Acme", type="greenhouse", token="acme")
    broken = CompanyConfig(id="broken", name="Broken Co", type="greenhouse", token="x")
    new_relevant = MatchedJob(job=make_job("1", "Python Dev <script>"), match=RELEVANT, is_new=True,
                              open_since=datetime(2026, 10, 5, 8, tzinfo=timezone.utc))
    old_relevant = MatchedJob(job=make_job("3", "Python Lead"), match=RELEVANT,
                              open_since=datetime(2026, 9, 26, 8, tzinfo=timezone.utc))
    return RunReport(
        started_at=datetime(2026, 10, 5, 8, tzinfo=timezone.utc),
        results=[
            CompanyResult(
                company=acme,
                total_open=5,
                new=[
                    new_relevant,
                    MatchedJob(job=make_job("2", "Designer"), match=MatchResult(relevant=False, reason="no title match"), is_new=True),
                ],
                relevant_open=[old_relevant, new_relevant],
                closed=[make_job("9", "Old Role")],
                hidden_new=4,
            ),
            CompanyResult(company=broken, error="HTTPStatusError: 404"),
        ],
    )


def test_subject():
    assert subject(_report()) == "Job alert: 2 relevant open (1 new), 2 new roles overall, 1 scrape problem"


def test_render_contains_all_sections_and_escapes():
    html = render_html(_report())
    assert "Relevant open roles (2, 1 new)" in html
    assert "Python Lead" in html  # still-open relevant role is listed, not just new ones
    assert "Designer" in html  # irrelevant roles still listed in the holistic section
    assert "Old Role" in html
    assert "Broken Co" in html and "404" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_render_mentions_hidden_roles():
    html = render_html(_report())
    assert "+4 elsewhere" in html
    assert "4 new roles outside your locations" in html


def test_render_omits_hidden_note_when_nothing_hidden():
    report = _report()
    report.results[0].hidden_new = 0
    assert "outside your locations" not in render_html(report)


def test_relevant_roles_list_new_first_with_badge():
    html = render_html(_report())
    section = html[html.index("Relevant open roles"):html.index("All new roles")]
    assert section.index("Python Dev") < section.index("Python Lead")  # new first
    assert section.count(">NEW<") == 1


def test_baseline_company_roles_are_not_badged_new():
    report = _report()
    report.results[0].baseline = True
    html = render_html(report)
    section = html[html.index("Relevant open roles"):html.index("All new roles")]
    assert ">NEW<" not in section
    assert "(2, 0 new)" in section


def test_relevant_roles_show_open_since():
    html = render_html(_report())
    section = html[html.index("Relevant open roles"):html.index("All new roles")]
    assert "open since 26 Sep 2026 (9 days)" in section
    assert "open since today" in section


def test_open_since_format():
    now = datetime(2026, 10, 14, 8, tzinfo=timezone.utc)
    assert open_since(datetime(2026, 10, 13, 8, tzinfo=timezone.utc), now) == "open since 13 Oct 2026 (1 day)"
    assert open_since(datetime(2026, 10, 14, 1, tzinfo=timezone.utc), now) == "open since today"
    assert open_since(None, now) == ""
