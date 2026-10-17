"""Keyword-based relevance matching.

Run `pytest tests/test_matcher.py` to check your implementation.
"""

from __future__ import annotations

from job_alert.models import Job, MatchingRules, MatchResult


def match(job: Job, rules: MatchingRules) -> MatchResult:
    """Decide whether a job is relevant. All comparisons are case-insensitive substrings.

    A job is relevant when ALL of these hold:
      1. its title contains at least one `include_title` keyword
         (if include_title is empty, every title passes this check),
      2. its title contains none of the `exclude_title` keywords,
      3. its location contains at least one `include_location` keyword
         (if include_location is empty, every location passes).

    `reason` lists what matched, joined by "; ", e.g. "title: python; location: remote".
    Report the first keyword *in config order* that matched (not the first in the title).
    Only include parts that came from a non-empty keyword list.
    For an irrelevant job, explain why, e.g. "excluded: intern" or "no title match".
    The tests pin down the exact strings.
    """
    is_title_include_keyword_match = any(keyword.lower() in job.title.lower(
    ) for keyword in rules.include_title) if rules.include_title else True
    is_title_exclude_keyword_match = not any(
        keyword.lower() in job.title.lower() for keyword in rules.exclude_title)
    is_location_include_keyword_match = any(keyword.lower() in job.location.lower(
    ) for keyword in rules.include_location) if rules.include_location else True

    is_relevant = is_title_include_keyword_match and is_title_exclude_keyword_match and is_location_include_keyword_match

    reason_parts = []
    if is_relevant:
        if rules.include_title:
            for keyword in rules.include_title:
                if keyword.lower() in job.title.lower():
                    reason_parts.append(f"title: {keyword}")
                    break
        if rules.include_location:
            for keyword in rules.include_location:
                if keyword.lower() in job.location.lower():
                    reason_parts.append(f"location: {keyword}")
                    break
    else:
        if rules.include_title and not is_title_include_keyword_match:
            reason_parts.append("no title match")
        if rules.exclude_title and not is_title_exclude_keyword_match:
            for keyword in rules.exclude_title:
               if keyword.lower() in job.title.lower():
                  reason_parts.append(f"excluded: {keyword}")
                  break
        if rules.include_location and not is_location_include_keyword_match:
            reason_parts.append("no location match")

    reason = "; ".join(reason_parts)
    return MatchResult(relevant=is_relevant, reason=reason)



def in_my_locations(job: Job, rules: MatchingRules) -> bool:
    """Whether a job belongs in the digest at all, regardless of its title.

    Same location test as `match`, except a blank location counts as a match: an
    unknown location (a posting with no location field) shouldn't make
    a role disappear. With `include_location` empty, every job is in.
    """
    if not rules.include_location or not job.location.strip():
        return True
    location = job.location.lower()
    return any(keyword.lower() in location for keyword in rules.include_location)
