"""Compare this run's scrape against what the store says is currently open.

Pure functions only (no I/O), which makes them easy to unit test.
Run `pytest tests/test_diff.py` to check your implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from job_alert.models import Job


@dataclass
class Diff:
    new: list[Job] = field(default_factory=list)  # in current, not in stored_open
    closed: list[Job] = field(default_factory=list)  # in stored_open, not in current
    still_open: list[Job] = field(default_factory=list)  # in both (use the *current* version)


def compute_diff(current: list[Job], stored_open: list[Job]) -> Diff:
    """Split jobs into new / closed / still_open, keyed by `job_id`.

    - Preserve the input order of `current` for `new` and `still_open`.
    - For still_open, return the job from `current` (title/location may have changed).
    - Duplicate job_ids in `current` should appear only once.

    Hint: build a dict {job_id: job} for each side, then use set operations.
    """
    current_dict = {job.job_id: job for job in current}
    stored_dict = {job.job_id: job for job in stored_open}

    new_job_id_set = current_dict.keys() - stored_dict.keys()
    closed_job_id_set = stored_dict.keys() - current_dict.keys()
    still_open_job_id_set = current_dict.keys() & stored_dict.keys()

    new = [job for job_id, job in current_dict.items() if job_id in new_job_id_set]
    closed = [job for job_id, job in stored_dict.items() if job_id in closed_job_id_set]
    still_open = [job for job_id, job in current_dict.items() if job_id in still_open_job_id_set]

    return Diff(new=new, closed=closed, still_open=still_open)


def is_suspicious_empty(current: list[Job], stored_open: list[Job]) -> bool:
    """Safety guard: True when a scrape returned nothing but we previously had open jobs.

    That almost always means the site changed or the scraper broke, not that every
    role closed at once. The runner skips diffing in that case so we don't
    mass-close everything and then re-announce it all as "new" next run.
    """
    if not current or len(current) == 0:
        return bool(stored_open)
    return False

