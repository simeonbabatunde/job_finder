from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Optional


def _clean(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", (value or "").lower()).strip()


def _values(preferences: Any, attr: str) -> List[str]:
    raw = getattr(preferences, attr, []) if preferences else []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).strip() for item in raw if str(item).strip()]


def _has_phrase(text: str, phrases: Iterable[str]) -> bool:
    for phrase in phrases:
        cleaned_phrase = _clean(phrase)
        if not cleaned_phrase:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(cleaned_phrase)}(?![a-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def _role_tokens(role: str) -> set[str]:
    stopwords = {
        "and",
        "the",
        "role",
        "engineer",
        "developer",
        "manager",
        "specialist",
        "associate",
        "senior",
        "junior",
        "lead",
        "staff",
        "principal",
        "full",
        "time",
        "remote",
    }
    return {
        token
        for token in _clean(role).split()
        if len(token) >= 3 and token not in stopwords
    }


@dataclass(frozen=True)
class JobPreScreenResult:
    status: str
    reasons: List[str] = field(default_factory=list)

    @property
    def should_analyze(self) -> bool:
        return self.status in {"pass", "maybe"}


class JobPreScreenService:
    """Cheap, high-recall screening before expensive AI fit analysis."""

    LOW_SENIORITY_TERMS = (
        "intern",
        "internship",
        "apprentice",
        "co op",
        "coop",
        "student",
        "campus",
        "new grad",
        "new graduate",
        "graduate program",
        "entry level",
        "entrylevel",
        "junior",
        "jr",
    )
    HIGH_SENIORITY_TERMS = (
        "senior",
        "sr",
        "staff",
        "principal",
        "lead",
        "architect",
        "manager",
        "director",
        "head",
    )

    @classmethod
    def screen(cls, job: Dict[str, Any], preferences: Any) -> JobPreScreenResult:
        title = _clean(job.get("title"))
        company = _clean(job.get("company"))
        location = _clean(job.get("location"))
        description = _clean(str(job.get("description", ""))[:2000])
        title_text = f"{title} {company}".strip()
        job_text = " ".join(part for part in (title, company, location, description) if part)

        hard_rejects: List[str] = []
        maybe_reasons: List[str] = []

        cls._screen_seniority(title_text, preferences, hard_rejects)
        cls._screen_job_type(title_text, job_text, preferences, hard_rejects, maybe_reasons)
        cls._screen_location(location, job_text, preferences, hard_rejects, maybe_reasons)
        cls._screen_role_signal(title, description, preferences, maybe_reasons)

        if hard_rejects:
            return JobPreScreenResult(
                status="reject",
                reasons=hard_rejects[:4],
            )

        if maybe_reasons:
            return JobPreScreenResult(
                status="maybe",
                reasons=maybe_reasons[:4],
            )

        return JobPreScreenResult(
            status="pass",
            reasons=["Core role, seniority, job type, and location signals look compatible."],
        )

    @classmethod
    def _desired_experience(cls, preferences: Any) -> str:
        text = _clean(" ".join(_values(preferences, "experience_level")))
        if _has_phrase(text, ("intern", "internship")):
            return "intern"
        if _has_phrase(text, ("entry", "entry level", "junior", "jr", "new grad")):
            return "junior"
        if _has_phrase(text, cls.HIGH_SENIORITY_TERMS):
            return "senior"
        if _has_phrase(text, ("mid", "intermediate", "experienced")):
            return "mid"
        return ""

    @classmethod
    def _screen_seniority(cls, title_text: str, preferences: Any, hard_rejects: List[str]) -> None:
        desired = cls._desired_experience(preferences)
        has_low = _has_phrase(title_text, cls.LOW_SENIORITY_TERMS)
        has_high = _has_phrase(title_text, cls.HIGH_SENIORITY_TERMS)

        if desired == "senior" and has_low and not has_high:
            hard_rejects.append("Title is clearly entry-level, junior, internship, or campus-oriented while preferences target senior roles.")
        elif desired in {"junior", "intern"} and has_high and not has_low:
            hard_rejects.append("Title is clearly senior, lead, staff, principal, manager, or director-level while preferences target junior/entry roles.")
        elif desired not in {"", "intern"} and _has_phrase(title_text, ("intern", "internship", "student", "campus")):
            hard_rejects.append("Title is clearly internship/student-oriented while preferences target non-intern roles.")

    @classmethod
    def _screen_job_type(
        cls,
        title_text: str,
        job_text: str,
        preferences: Any,
        hard_rejects: List[str],
        maybe_reasons: List[str],
    ) -> None:
        desired = _clean(" ".join(_values(preferences, "job_type")))
        if not desired:
            return

        wants_full_time = _has_phrase(desired, ("full time", "fulltime", "permanent"))
        wants_part_time = _has_phrase(desired, ("part time", "parttime"))
        wants_contract = _has_phrase(desired, ("contract", "contractor", "freelance"))
        wants_intern = _has_phrase(desired, ("intern", "internship"))

        if wants_full_time:
            if _has_phrase(title_text, ("part time", "parttime", "temporary", "temp", "seasonal")):
                hard_rejects.append("Title is clearly not full-time.")
            elif _has_phrase(title_text, ("contract", "contractor", "freelance")):
                hard_rejects.append("Title is clearly contract/freelance while preferences target full-time roles.")
            elif _has_phrase(job_text, ("contract role", "contract position", "part time role", "part time position")):
                hard_rejects.append("Description clearly indicates a non-full-time role.")
            elif _has_phrase(job_text, ("contract to hire", "contract-to-hire")):
                maybe_reasons.append("Contract-to-hire wording found; kept for full review.")

        if wants_part_time and _has_phrase(title_text, ("full time", "fulltime")):
            hard_rejects.append("Title is clearly full-time while preferences target part-time roles.")

        if wants_contract and _has_phrase(title_text, ("full time", "fulltime", "permanent")):
            maybe_reasons.append("Title suggests full-time/permanent; kept because contract wording can vary by posting.")

        if not wants_intern and _has_phrase(title_text, ("intern", "internship")):
            hard_rejects.append("Title is clearly an internship while preferences do not target internships.")

    @classmethod
    def _screen_location(
        cls,
        location: str,
        job_text: str,
        preferences: Any,
        hard_rejects: List[str],
        maybe_reasons: List[str],
    ) -> None:
        desired_locations = _values(preferences, "location")
        desired = _clean(" ".join(desired_locations))
        if not desired:
            return

        wants_remote = _has_phrase(desired, ("remote", "anywhere"))
        job_says_remote = _has_phrase(f"{location} {job_text}", ("remote", "work from home", "distributed"))
        job_says_onsite = _has_phrase(f"{location} {job_text}", ("onsite", "on site", "on-site", "in office"))
        job_says_hybrid = _has_phrase(f"{location} {job_text}", ("hybrid",))

        if wants_remote:
            if job_says_onsite and not job_says_remote:
                hard_rejects.append("Posting appears on-site only while preferences target remote roles.")
            elif job_says_hybrid and not job_says_remote:
                maybe_reasons.append("Posting appears hybrid; kept for full review because remote wording can be inconsistent.")
            elif location and not job_says_remote:
                maybe_reasons.append("Location does not clearly say remote; kept for full review.")
            return

        if location and not job_says_remote:
            desired_tokens = {token for token in desired.split() if len(token) >= 3}
            if desired_tokens and not any(token in location for token in desired_tokens):
                maybe_reasons.append("Location is not an obvious preference match; kept for full review.")

    @classmethod
    def _screen_role_signal(
        cls,
        title: str,
        description: str,
        preferences: Any,
        maybe_reasons: List[str],
    ) -> None:
        roles = _values(preferences, "role")
        roles = [role for role in roles if role.strip()]
        if not roles:
            return

        title_and_description = f"{title} {description}"
        for role in roles:
            role_clean = _clean(role)
            tokens = _role_tokens(role)
            if role_clean and role_clean in title_and_description:
                return
            if tokens and sum(1 for token in tokens if token in title_and_description) >= min(2, len(tokens)):
                return

        maybe_reasons.append("Role keywords are not obvious in the title or description; kept for full AI review.")
