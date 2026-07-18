from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class CompanyDiscoveryCandidate:
    company: str
    source: str
    score: float
    reason: str


class CompanyDiscoveryService:
    """Build a prioritized company list for official career-source exploration.

    The search pipeline should start with explicit user guardrails, then expand to
    companies that are likely to offer similar roles. This service is intentionally
    deterministic so company expansion does not spend LLM credits.
    """

    ROLE_FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
        "software_engineering": (
            "software", "backend", "front end", "frontend", "full stack", "fullstack",
            "platform", "firmware", "embedded", "mobile", "ios", "android", "developer",
        ),
        "data_analytics": (
            "data", "analytics", "analyst", "bi", "business intelligence", "warehouse",
            "etl", "machine learning", "ml", "scientist",
        ),
        "ai_ml": ("ai", "ml", "machine learning", "llm", "nlp", "computer vision", "research"),
        "security_infra": (
            "security", "sre", "site reliability", "devops", "infrastructure", "cloud",
            "platform", "network", "reliability",
        ),
        "product_design": ("product", "designer", "design", "ux", "ui", "researcher", "growth"),
        "fintech_ops": (
            "finance", "fintech", "risk", "payments", "payroll", "accounting", "operations",
            "revenue", "banking",
        ),
        "health_bio": ("health", "healthcare", "bio", "clinical", "medical", "pharma", "life sciences"),
    }

    ROLE_COMPANY_CATALOG: dict[str, tuple[str, ...]] = {
        "software_engineering": (
            "Stripe", "Datadog", "Cloudflare", "Figma", "Notion", "Airbnb", "DoorDash",
            "Uber", "Plaid", "Ramp", "Rippling", "Samsara", "MongoDB", "Atlassian",
            "GitLab", "HashiCorp", "Twilio", "Vercel", "Shopify", "Roblox",
        ),
        "data_analytics": (
            "Databricks", "Snowflake", "dbt Labs", "Fivetran", "Scale AI", "Stripe",
            "Airbnb", "DoorDash", "Instacart", "Netflix", "Grammarly", "MongoDB",
        ),
        "ai_ml": (
            "OpenAI", "Anthropic", "Scale AI", "Databricks", "Hugging Face", "Perplexity AI",
            "Cohere", "Runway", "Weights & Biases", "Together AI",
        ),
        "security_infra": (
            "Cloudflare", "CrowdStrike", "Okta", "Wiz", "Snyk", "Palo Alto Networks",
            "Datadog", "GitLab", "HashiCorp", "Zscaler",
        ),
        "product_design": (
            "Figma", "Notion", "Canva", "Atlassian", "Miro", "Webflow", "Shopify",
            "Airbnb", "Intercom", "Linear",
        ),
        "fintech_ops": (
            "Stripe", "Plaid", "Ramp", "Brex", "Block", "Coinbase", "Robinhood", "Chime",
            "SoFi", "Adyen", "Rippling", "Gusto",
        ),
        "health_bio": (
            "Oscar Health", "Hims & Hers", "Ro", "Tempus", "Flatiron Health", "Benchling",
            "10x Genomics", "Color Health",
        ),
    }

    GENERIC_ROLE_TERMS = {
        "senior", "sr", "junior", "jr", "lead", "staff", "principal", "manager",
        "engineer", "developer", "specialist", "associate", "full", "time", "remote",
    }

    @classmethod
    def discover_company_names(
        cls,
        *,
        seed_companies: Iterable[str] | None = None,
        target_roles: Iterable[str] | None = None,
        query: str = "",
        board_results: Iterable[Dict[str, Any]] | None = None,
        max_companies: int = 16,
    ) -> List[str]:
        return [
            candidate.company
            for candidate in cls.discover_companies(
                seed_companies=seed_companies,
                target_roles=target_roles,
                query=query,
                board_results=board_results,
                max_companies=max_companies,
            )
        ]

    @classmethod
    def discover_companies(
        cls,
        *,
        seed_companies: Iterable[str] | None = None,
        target_roles: Iterable[str] | None = None,
        query: str = "",
        board_results: Iterable[Dict[str, Any]] | None = None,
        max_companies: int = 16,
    ) -> List[CompanyDiscoveryCandidate]:
        candidates: list[CompanyDiscoveryCandidate] = []
        candidates.extend(cls._seed_candidates(seed_companies or []))
        candidates.extend(cls._board_candidates(board_results or [], target_roles or [], query))
        candidates.extend(cls._role_family_candidates(target_roles or [], query))
        return cls._rank_and_dedupe(candidates, max_companies=max_companies)

    @classmethod
    def _seed_candidates(cls, companies: Iterable[str]) -> list[CompanyDiscoveryCandidate]:
        candidates = []
        for company in companies:
            clean = cls._clean_company(company)
            if clean:
                candidates.append(
                    CompanyDiscoveryCandidate(
                        company=clean,
                        source="user_seed",
                        score=1.0,
                        reason="User-entered allowed or target company.",
                    )
                )
        return candidates

    @classmethod
    def _board_candidates(
        cls,
        board_results: Iterable[Dict[str, Any]],
        target_roles: Iterable[str],
        query: str,
    ) -> list[CompanyDiscoveryCandidate]:
        jobs_by_company: dict[str, list[Dict[str, Any]]] = {}
        display_names: dict[str, str] = {}
        for job in board_results:
            company = cls._clean_company(str(job.get("company") or ""))
            key = cls._company_key(company)
            if not key:
                continue
            display_names.setdefault(key, company)
            jobs_by_company.setdefault(key, []).append(job)

        has_role_filter = bool([role for role in target_roles if str(role).strip()] or query.strip())
        candidates = []
        for key, jobs in jobs_by_company.items():
            role_signal = max(
                cls._role_similarity(str(job.get("title") or ""), target_roles, query)
                for job in jobs
            )
            if has_role_filter and role_signal <= 0:
                continue
            frequency_bonus = min(len(jobs) * 0.025, 0.1)
            score = 0.72 + role_signal * 0.12 + frequency_bonus
            candidates.append(
                CompanyDiscoveryCandidate(
                    company=display_names[key],
                    source="board_hint",
                    score=score,
                    reason="Company appeared in job-board results for a similar role.",
                )
            )
        return candidates

    @classmethod
    def _role_family_candidates(cls, target_roles: Iterable[str], query: str) -> list[CompanyDiscoveryCandidate]:
        family_scores = cls._role_family_scores(target_roles, query)
        candidates = []
        for family, family_score in family_scores:
            for index, company in enumerate(cls.ROLE_COMPANY_CATALOG.get(family, ())):
                candidates.append(
                    CompanyDiscoveryCandidate(
                        company=company,
                        source=f"role_family:{family}",
                        score=0.62 + family_score * 0.08 - min(index * 0.003, 0.04),
                        reason=f"Company commonly hires for {family.replace('_', ' ')} roles.",
                    )
                )
        return candidates

    @classmethod
    def _role_family_scores(cls, target_roles: Iterable[str], query: str) -> list[tuple[str, float]]:
        haystack = cls._normalise_text(" ".join([query, *[str(role) for role in target_roles]]))
        if not haystack:
            return [("software_engineering", 0.5)]

        scores = []
        for family, markers in cls.ROLE_FAMILY_MARKERS.items():
            hits = 0
            for marker in markers:
                marker_text = cls._normalise_text(marker)
                if marker_text and marker_text in haystack:
                    hits += 1
            if hits:
                scores.append((family, min(1.0, hits / max(len(markers), 1) * 3)))

        if not scores and any(token in haystack for token in ("engineer", "developer", "software")):
            scores.append(("software_engineering", 0.7))
        if not scores:
            scores.append(("software_engineering", 0.45))
        return sorted(scores, key=lambda item: item[1], reverse=True)[:3]

    @classmethod
    def _rank_and_dedupe(
        cls,
        candidates: Sequence[CompanyDiscoveryCandidate],
        *,
        max_companies: int,
    ) -> list[CompanyDiscoveryCandidate]:
        best_by_key: dict[str, CompanyDiscoveryCandidate] = {}
        first_seen: dict[str, int] = {}
        for index, candidate in enumerate(candidates):
            clean = cls._clean_company(candidate.company)
            key = cls._company_key(clean)
            if not key:
                continue
            current = best_by_key.get(key)
            cleaned_candidate = CompanyDiscoveryCandidate(
                company=clean,
                source=candidate.source,
                score=candidate.score,
                reason=candidate.reason,
            )
            first_seen.setdefault(key, index)
            if current is None or cleaned_candidate.score > current.score:
                best_by_key[key] = cleaned_candidate

        ranked = sorted(
            best_by_key.items(),
            key=lambda item: (-item[1].score, first_seen[item[0]], item[1].company.lower()),
        )
        return [candidate for _, candidate in ranked[: max(max_companies, 0)]]

    @classmethod
    def _role_similarity(cls, title: str, target_roles: Iterable[str], query: str) -> float:
        title_tokens = cls._role_tokens(title)
        if not title_tokens:
            return 0.0
        role_texts = [str(role) for role in target_roles if str(role).strip()] or [query]
        best = 0.0
        for role in role_texts:
            role_tokens = cls._role_tokens(role)
            if not role_tokens:
                continue
            best = max(best, len(title_tokens & role_tokens) / max(len(title_tokens | role_tokens), 1))
        return best

    @classmethod
    def _role_tokens(cls, value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9+#.]+", value.lower())
            if len(token) >= 3 and token not in cls.GENERIC_ROLE_TERMS
        }

    @classmethod
    def _clean_company(cls, value: str) -> str:
        clean = " ".join(str(value or "").split())
        if clean.lower() in {"unknown", "unknown company"}:
            return ""
        return clean

    @classmethod
    def _company_key(cls, value: str) -> str:
        cleaned = re.sub(r"\([^)]*\)", " ", value.lower())
        cleaned = re.sub(
            r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company)\b\.?,?",
            " ",
            cleaned,
        )
        return cls._normalise_text(cleaned)

    @staticmethod
    def _normalise_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9+#.]+", value.lower()))
