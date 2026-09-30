"""Request and response bodies of the authentication endpoints."""

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.models.user import FULL_NAME_MAX_LENGTH
from app.schemas.types import NormalizedEmail, UtcDatetime

PASSWORD_MIN_LENGTH = 10
# argon2 accepts any length, but an unbounded password lets one request buy a
# lot of hashing time. 128 characters is far beyond any passphrase.
PASSWORD_MAX_LENGTH = 128

FullName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=FULL_NAME_MAX_LENGTH)
]


class UserCreate(BaseModel):
    """A new account.

    The password is a SecretStr so it never shows up in reprs, logs or
    tracebacks; its rules are checked here rather than with Field(min_length),
    whose message ("at least 10 items") is written for collections.
    """

    model_config = ConfigDict(extra="forbid")

    email: NormalizedEmail
    full_name: FullName
    password: SecretStr = Field(
        json_schema_extra={"minLength": PASSWORD_MIN_LENGTH, "maxLength": PASSWORD_MAX_LENGTH}
    )

    @field_validator("password")
    @classmethod
    def _check_password_policy(cls, password: SecretStr, info: ValidationInfo) -> SecretStr:
        value = password.get_secret_value()
        if len(value) < PASSWORD_MIN_LENGTH:
            raise PydanticCustomError(
                "password_too_short",
                "The password must be at least {min_length} characters long.",
                {"min_length": PASSWORD_MIN_LENGTH},
            )
        if len(value) > PASSWORD_MAX_LENGTH:
            raise PydanticCustomError(
                "password_too_long",
                "The password must be at most {max_length} characters long.",
                {"max_length": PASSWORD_MAX_LENGTH},
            )
        # Fields validate in order, so the email is present here unless it was invalid.
        email = info.data.get("email")
        if email is not None and value.lower() == email:
            raise PydanticCustomError(
                "password_equals_email", "The password must not be the same as the email address."
            )
        return password


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    created_at: UtcDatetime
