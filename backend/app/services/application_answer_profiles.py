from typing import Optional

from sqlmodel import Session

from app.models import ApplicationAnswerAudit, ApplicationAnswerProfile
from app.services.field_encryption import decrypt_text, encrypt_text


APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS = {
    "work_authorized_us": "unspecified",
    "requires_sponsorship_now": "unspecified",
    "requires_sponsorship_future": "unspecified",
    "willing_to_relocate": "unspecified",
    "remote_preference": "unspecified",
    "earliest_start_date": None,
    "notice_period": None,
    "desired_salary": None,
    "work_authorization_notes": None,
    "gender": "prefer_not_to_answer",
    "race_ethnicity": "prefer_not_to_answer",
    "veteran_status": "prefer_not_to_answer",
    "disability_status": "prefer_not_to_answer",
}

APPLICATION_ANSWER_AUDIT_FIELDS = tuple(
    APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS.keys()
) + (
    "consent_to_use_answers",
    "consent_to_use_demographics",
)


def encrypt_application_answer_payload(payload: dict) -> dict:
    encrypted = dict(payload)
    for field in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS:
        encrypted[field] = encrypt_text(encrypted.get(field))
    return encrypted


def decrypt_application_answer_profile(record: Optional[ApplicationAnswerProfile]) -> Optional[ApplicationAnswerProfile]:
    if not record:
        return None

    data = record.model_dump()
    for field, fallback in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS.items():
        data[field] = decrypt_text(data.get(field), fallback=fallback)
    return ApplicationAnswerProfile(**data)


def serialize_application_answer_profile(record: Optional[ApplicationAnswerProfile]):
    decrypted = decrypt_application_answer_profile(record)
    if not decrypted:
        return None

    data = {
        field: getattr(decrypted, field)
        for field in APPLICATION_ANSWER_ENCRYPTED_FIELD_DEFAULTS
    }
    data.update({
        "id": decrypted.id,
        "consent_to_use_answers": decrypted.consent_to_use_answers,
        "consent_to_use_demographics": decrypted.consent_to_use_demographics,
        "updated_at": decrypted.updated_at,
    })
    return data


def audit_application_answer_access(
    session: Session,
    *,
    user_id: int,
    action: str,
    access_reason: str,
    source: str,
    application_id: Optional[int] = None,
    fields: Optional[list[str]] = None,
    commit: bool = True,
):
    audit = ApplicationAnswerAudit(
        user_id=user_id,
        application_id=application_id,
        action=action,
        access_reason=access_reason,
        source=source,
        fields=fields or list(APPLICATION_ANSWER_AUDIT_FIELDS),
    )
    session.add(audit)
    if commit:
        session.commit()
        session.refresh(audit)
    return audit


def sanitize_application_answer_payload(payload) -> dict:
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    if not data.get("consent_to_use_demographics"):
        data["gender"] = "prefer_not_to_answer"
        data["race_ethnicity"] = "prefer_not_to_answer"
        data["veteran_status"] = "prefer_not_to_answer"
        data["disability_status"] = "prefer_not_to_answer"
    return data
