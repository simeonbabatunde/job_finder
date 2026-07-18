from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import csv
import os
from pathlib import Path
import re
from typing import Iterable, List


DEFAULT_RANKING_CSV = Path(__file__).resolve().parents[1] / "data" / "company_rankings" / "fortune_us_seed.csv"
ROLE_TAG_SYNONYMS: dict[str, set[str]] = {
    "firmware": {"firmware", "embedded", "bare", "metal", "rtos"},
    "embedded": {"firmware", "embedded", "hardware", "iot", "device", "devices"},
    "hardware": {"hardware", "electrical", "electronics", "semiconductor", "device", "devices"},
    "software": {"software", "backend", "frontend", "fullstack", "developer", "platform"},
    "cloud": {"cloud", "platform", "infrastructure", "devops", "sre"},
    "ai": {"ai", "ml", "machine", "learning", "llm", "data"},
    "data": {"data", "analytics", "analyst", "bi", "scientist"},
    "network": {"network", "telecom", "communications", "wireless"},
    "semiconductor": {"semiconductor", "chip", "silicon", "asic", "fpga"},
    "aerospace": {"aerospace", "defense", "avionics", "flight"},
    "automotive": {"automotive", "vehicle", "ev", "battery", "mobility"},
    "industrial": {"industrial", "automation", "controls", "manufacturing"},
    "finance": {"finance", "financial", "bank", "risk", "payments"},
    "healthcare": {"health", "healthcare", "clinical", "medical"},
}


@dataclass(frozen=True)
class RankedCompany:
    rank: int
    company: str
    sector: str
    role_tags: tuple[str, ...]
    aliases: tuple[str, ...]

    @property
    def cohort(self) -> str:
        return "fortune_500" if self.rank <= 500 else "fortune_1000_tail"


class CompanyRankingService:
    """Ranked large-company source for deterministic official-career exploration.

    The bundled CSV is intentionally local so matching does not scrape Fortune during
    a run. Set FORTUNE_COMPANY_RANKING_CSV to a full licensed Fortune 1000 export
    with the same columns to replace or expand the seed data.
    """

    @classmethod
    def fortune_500_names(
        cls,
        *,
        target_roles: Iterable[str] | None = None,
        query: str = "",
        limit: int | None = None,
        exclude: Iterable[str] | None = None,
    ) -> List[str]:
        return cls.ranked_company_names(
            min_rank=1,
            max_rank=500,
            target_roles=target_roles,
            query=query,
            limit=limit,
            exclude=exclude,
        )

    @classmethod
    def fortune_1000_tail_names(
        cls,
        *,
        target_roles: Iterable[str] | None = None,
        query: str = "",
        limit: int | None = None,
        exclude: Iterable[str] | None = None,
    ) -> List[str]:
        return cls.ranked_company_names(
            min_rank=501,
            max_rank=1000,
            target_roles=target_roles,
            query=query,
            limit=limit,
            exclude=exclude,
        )

    @classmethod
    def ranked_company_names(
        cls,
        *,
        min_rank: int,
        max_rank: int,
        target_roles: Iterable[str] | None = None,
        query: str = "",
        limit: int | None = None,
        exclude: Iterable[str] | None = None,
    ) -> List[str]:
        excluded = {cls._company_key(company) for company in exclude or [] if str(company).strip()}
        companies = [
            company
            for company in cls.load_rankings()
            if min_rank <= company.rank <= max_rank and cls._company_key(company.company) not in excluded
        ]
        ranked = sorted(
            companies,
            key=lambda company: (-cls._role_relevance(company, target_roles or [], query), company.rank, company.company.lower()),
        )
        names = [company.company for company in ranked]
        return names[:limit] if limit and limit > 0 else names

    @classmethod
    @lru_cache(maxsize=1)
    def load_rankings(cls) -> tuple[RankedCompany, ...]:
        csv_path = Path(os.getenv("FORTUNE_COMPANY_RANKING_CSV") or DEFAULT_RANKING_CSV)
        rows: list[RankedCompany] = []
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    rank = int(str(row.get("rank") or "").strip())
                except ValueError:
                    continue
                company = " ".join(str(row.get("company") or "").split())
                if not company:
                    continue
                rows.append(
                    RankedCompany(
                        rank=rank,
                        company=company,
                        sector=" ".join(str(row.get("sector") or "").split()),
                        role_tags=cls._split_pipe_field(row.get("role_tags") or ""),
                        aliases=cls._split_pipe_field(row.get("aliases") or ""),
                    )
                )
        return tuple(sorted(rows, key=lambda company: (company.rank, company.company.lower())))

    @classmethod
    def _role_relevance(cls, company: RankedCompany, target_roles: Iterable[str], query: str) -> float:
        role_tokens = cls._role_tokens(" ".join([query, *[str(role) for role in target_roles]]))
        if not role_tokens:
            return 0.0
        score = 0.0
        for tag in company.role_tags:
            tag_tokens = ROLE_TAG_SYNONYMS.get(tag, {tag})
            if role_tokens & tag_tokens:
                score += 1.0
        return score

    @staticmethod
    def _split_pipe_field(value: str) -> tuple[str, ...]:
        return tuple(part.strip().lower() for part in value.split("|") if part.strip())

    @staticmethod
    def _role_tokens(value: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9+#.]+", value.lower()) if len(token) >= 2}

    @staticmethod
    def _company_key(value: str) -> str:
        cleaned = re.sub(r"\([^)]*\)", " ", str(value or "").lower())
        cleaned = re.sub(
            r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|group)\b\.?,?",
            " ",
            cleaned,
        )
        return " ".join(re.findall(r"[a-z0-9]+", cleaned))
