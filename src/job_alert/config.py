"""Load and validate config/companies.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from job_alert.models import AppConfig


def load_config(path: str | Path) -> AppConfig:
    with open(path) as f:
        return AppConfig.model_validate(yaml.safe_load(f))
