import re
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 60
OTP_MAX_SENDS_PER_HOUR = 5


class PhoneVerificationError(ValueError):
    pass


class InvalidPhoneError(PhoneVerificationError):
    pass


class DuplicatePhoneError(PhoneVerificationError):
    pass


class VerificationRateLimitError(PhoneVerificationError):
    pass


class MockSmsProvider:
    """Development adapter. Codes remain transient and server-side."""

    name = "mock_sms"

    def __init__(self):
        self._outbox = {}

    def send(self, challenge_token, destination, code):
        self._outbox[challenge_token] = {
            "destination": destination,
            "code": code,
        }

    def code_for_testing(self, challenge_token):
        message = self._outbox.get(challenge_token)
        return message["code"] if message else None

    def clear(self):
        self._outbox.clear()


mock_sms_provider = MockSmsProvider()


def utc_now():
    return datetime.now(timezone.utc)


def normalize_mobile_number(country_code, mobile_number):
    calling_digits = re.sub(r"\D", "", str(country_code or ""))
    mobile_digits = re.sub(r"\D", "", str(mobile_number or ""))
    if not 1 <= len(calling_digits) <= 3:
        raise InvalidPhoneError("Select a valid country calling code.")
    mobile_digits = mobile_digits.lstrip("0")
    normalized = f"+{calling_digits}{mobile_digits}"
    if len(normalized) < 9 or len(normalized) > 16:
        raise InvalidPhoneError("Enter a valid mobile number.")
    return f"+{calling_digits}", normalized


def mask_phone(normalized_phone):
    return f"{normalized_phone[:3]}••••{normalized_phone[-3:]}"


def _as_datetime(value):
    return datetime.fromisoformat(value)


def request_verification(
    database,
    country_code,
    mobile_number,
    pending_registration_id=None,
    provider=None,
    now=None,
    fixed_code=None,
):
    provider = provider or mock_sms_provider
    now = now or utc_now()
    calling_code, normalized_phone = normalize_mobile_number(country_code, mobile_number)

    existing_user = database.execute(
        "SELECT id, phone_verified FROM users WHERE normalized_phone = ?",
        (normalized_phone,),
    ).fetchone()
    if existing_user is not None:
        if existing_user["phone_verified"]:
            raise DuplicatePhoneError("This mobile number is already verified.")
        raise DuplicatePhoneError("This mobile number is already in use.")

    if pending_registration_id is None:
        challenge = database.execute(
            """
            SELECT * FROM phone_verification_challenges
            WHERE normalized_phone = ? AND pending_registration_id IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (normalized_phone,),
        ).fetchone()
    else:
        challenge = database.execute(
            """
            SELECT * FROM phone_verification_challenges
            WHERE normalized_phone = ? AND pending_registration_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (normalized_phone, pending_registration_id),
        ).fetchone()

    if challenge is not None and challenge["status"] == "verified":
        raise PhoneVerificationError("This mobile number is already verified.")

    window_started_at = now
    send_count = 1
    if challenge is not None:
        resend_available_at = _as_datetime(challenge["resend_available_at"])
        if now < resend_available_at:
            wait_seconds = max(1, int((resend_available_at - now).total_seconds()))
            raise VerificationRateLimitError(
                f"Wait {wait_seconds} seconds before requesting another code."
            )
        previous_window = _as_datetime(challenge["send_window_started_at"])
        if now - previous_window < timedelta(hours=1):
            window_started_at = previous_window
            send_count = challenge["send_count"] + 1
            if send_count > OTP_MAX_SENDS_PER_HOUR:
                raise VerificationRateLimitError(
                    "Too many verification codes requested. Try again later."
                )

    if fixed_code is not None and not re.fullmatch(r"\d{6}", str(fixed_code)):
        raise ValueError("A fixed development OTP must contain exactly six digits.")
    code = (
        str(fixed_code)
        if fixed_code is not None
        else f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    )
    code_hash = generate_password_hash(code)
    expires_at = now + timedelta(minutes=OTP_EXPIRY_MINUTES)
    resend_available_at = now + timedelta(seconds=OTP_RESEND_SECONDS)

    if challenge is None:
        challenge_token = secrets.token_urlsafe(32)
        cursor = database.execute(
            """
            INSERT INTO phone_verification_challenges (
                challenge_token, pending_registration_id, country_calling_code,
                normalized_phone, code_hash, status, attempts_remaining,
                send_count, send_window_started_at, expires_at,
                resend_available_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                challenge_token,
                pending_registration_id,
                calling_code,
                normalized_phone,
                code_hash,
                OTP_MAX_ATTEMPTS,
                send_count,
                window_started_at.isoformat(),
                expires_at.isoformat(),
                resend_available_at.isoformat(),
                now.isoformat(),
            ),
        )
        challenge_id = cursor.lastrowid
    else:
        challenge_token = challenge["challenge_token"]
        challenge_id = challenge["id"]
        database.execute(
            """
            UPDATE phone_verification_challenges
            SET pending_registration_id = ?, code_hash = ?, status = 'pending',
                attempts_remaining = ?, send_count = ?,
                send_window_started_at = ?, expires_at = ?,
                resend_available_at = ?, verified_at = NULL
            WHERE id = ?
            """,
            (
                pending_registration_id,
                code_hash,
                OTP_MAX_ATTEMPTS,
                send_count,
                window_started_at.isoformat(),
                expires_at.isoformat(),
                resend_available_at.isoformat(),
                challenge_id,
            ),
        )

    provider.send(challenge_token, normalized_phone, code)
    return {
        "id": challenge_id,
        "challenge_token": challenge_token,
        "country_calling_code": calling_code,
        "normalized_phone": normalized_phone,
        "masked_phone": mask_phone(normalized_phone),
        "expires_at": expires_at.isoformat(),
        "resend_available_at": resend_available_at.isoformat(),
        "delivery": provider.name,
    }


def verify_code(database, challenge_token, code, now=None):
    now = now or utc_now()
    challenge = database.execute(
        "SELECT * FROM phone_verification_challenges WHERE challenge_token = ?",
        (challenge_token,),
    ).fetchone()
    if challenge is None:
        raise PhoneVerificationError("Verification request not found.")
    if challenge["status"] == "verified":
        return {
            "verified": True,
            "already_verified": True,
            "verified_at": challenge["verified_at"],
            "normalized_phone": challenge["normalized_phone"],
            "country_calling_code": challenge["country_calling_code"],
            "pending_registration_id": challenge["pending_registration_id"],
        }
    if challenge["status"] == "locked" or challenge["attempts_remaining"] <= 0:
        raise PhoneVerificationError(
            "Verification attempts exhausted. Request a new code later."
        )
    if now > _as_datetime(challenge["expires_at"]):
        database.execute(
            "UPDATE phone_verification_challenges SET status = 'expired' WHERE id = ?",
            (challenge["id"],),
        )
        raise PhoneVerificationError("Verification code expired. Request a new code.")

    supplied_code = re.sub(r"\D", "", str(code or ""))
    if len(supplied_code) != OTP_LENGTH or not check_password_hash(
        challenge["code_hash"], supplied_code
    ):
        attempts_remaining = challenge["attempts_remaining"] - 1
        status = "locked" if attempts_remaining <= 0 else "pending"
        database.execute(
            """
            UPDATE phone_verification_challenges
            SET attempts_remaining = ?, status = ?
            WHERE id = ?
            """,
            (attempts_remaining, status, challenge["id"]),
        )
        if attempts_remaining <= 0:
            raise PhoneVerificationError(
                "Verification attempts exhausted. Request a new code later."
            )
        raise PhoneVerificationError(
            f"Incorrect verification code. {attempts_remaining} attempts remaining."
        )

    verified_at = now.isoformat()
    database.execute(
        """
        UPDATE phone_verification_challenges
        SET status = 'verified', verified_at = ?
        WHERE id = ?
        """,
        (verified_at, challenge["id"]),
    )
    return {
        "verified": True,
        "already_verified": False,
        "verified_at": verified_at,
        "normalized_phone": challenge["normalized_phone"],
        "country_calling_code": challenge["country_calling_code"],
        "pending_registration_id": challenge["pending_registration_id"],
    }