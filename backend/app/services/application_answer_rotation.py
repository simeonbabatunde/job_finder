from typing import Optional

from sqlmodel import Session, select

from app.models import ApplicationAnswerProfile
from app.services.field_encryption import (
    decrypt_text_with_key_status,
    encrypt_text_with_current_key,
)
from app.time_utils import utc_now


APPLICATION_ANSWER_ENCRYPTED_FIELDS = (
    "work_authorized_us",
    "requires_sponsorship_now",
    "requires_sponsorship_future",
    "willing_to_relocate",
    "remote_preference",
    "earliest_start_date",
    "notice_period",
    "desired_salary",
    "work_authorization_notes",
    "gender",
    "race_ethnicity",
    "veteran_status",
    "disability_status",
)


def reencrypt_application_answer_profiles(
    session: Session,
    *,
    dry_run: bool = True,
    limit: Optional[int] = None,
) -> dict:
    query = select(ApplicationAnswerProfile).order_by(ApplicationAnswerProfile.id.asc())
    if limit and limit > 0:
        query = query.limit(limit)

    records = session.exec(query).all()
    result = {
        "dry_run": dry_run,
        "scanned_records": len(records),
        "current_records": 0,
        "previous_key_records": 0,
        "plaintext_records": 0,
        "reencrypted_records": 0,
        "unreadable_records": 0,
        "unreadable_fields": [],
    }

    for record in records:
        decrypted_values = {}
        statuses = []
        unreadable_fields = []

        for field in APPLICATION_ANSWER_ENCRYPTED_FIELDS:
            decrypted_value, status = decrypt_text_with_key_status(getattr(record, field))
            statuses.append(status)
            if status == "unreadable":
                unreadable_fields.append(field)
            else:
                decrypted_values[field] = decrypted_value

        if unreadable_fields:
            result["unreadable_records"] += 1
            result["unreadable_fields"].append({
                "application_answer_profile_id": record.id,
                "user_id": record.user_id,
                "fields": unreadable_fields,
            })
            continue

        has_previous_key_values = "previous" in statuses
        has_plaintext_values = "plaintext" in statuses
        should_reencrypt = has_previous_key_values or has_plaintext_values

        if has_previous_key_values:
            result["previous_key_records"] += 1
        if has_plaintext_values:
            result["plaintext_records"] += 1

        if not should_reencrypt:
            result["current_records"] += 1
            continue

        result["reencrypted_records"] += 1
        if dry_run:
            continue

        for field, decrypted_value in decrypted_values.items():
            setattr(record, field, encrypt_text_with_current_key(decrypted_value))
        record.updated_at = utc_now()
        session.add(record)

    if not dry_run:
        session.commit()

    return result
