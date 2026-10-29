from __future__ import annotations

import re
from urllib.parse import urlsplit
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Email = str

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    @classmethod
    def validate_email(cls, value: str) -> str:
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
            raise ValueError("Invalid email address")
        return value.strip()

class Theme(StrictModel):
    primaryColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    dark: bool | None = None
    position: Literal["bottom-right", "bottom-left"] | None = None
    logoUrl: str | None = None
    avatarUrl: str | None = None
    radius: int | None = Field(default=None, ge=0, le=32)
    @field_validator("logoUrl", "avatarUrl")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("URL must use HTTP or HTTPS")
        return value

class WidgetSettings(StrictModel):
    launcherLabel: str | None = Field(default=None, min_length=1, max_length=80)
    placeholder: str | None = Field(default=None, min_length=1, max_length=120)
    showBranding: bool | None = None

class AnalyticsSettings(StrictModel):
    enabled: bool | None = None
    retainDays: int | None = Field(default=None, ge=1, le=3650)

class Widget(StrictModel):
    primaryColor: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    dark: bool | None = None
    logoUrl: str | None = None
    avatarUrl: str | None = None
    assistantName: str | None = Field(default=None, min_length=1, max_length=80)
    welcomeMessage: str | None = Field(default=None, max_length=500)
    suggestedQuestions: list[str] | None = Field(default=None, max_length=6)
    position: Literal["bottom-right", "bottom-left"] | None = None
    width: int | None = Field(default=None, ge=280, le=600)
    height: int | None = Field(default=None, ge=360, le=800)
    radius: int | None = Field(default=None, ge=0, le=32)
    icon: Literal["chat", "sparkles", "help"] | None = None
    @field_validator("logoUrl", "avatarUrl")
    @classmethod
    def check_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("URL must use HTTP or HTTPS")
        return value
    @field_validator("suggestedQuestions")
    @classmethod
    def check_questions(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not q or len(q) > 120 for q in value):
            raise ValueError("Each suggested question must be 1-120 characters")
        return value

class ClientConfig(StrictModel):
    companyName: str | None = Field(default=None, min_length=1, max_length=120)
    assistantName: str = Field(min_length=1, max_length=80)
    teamEmail: str | None = None
    fallbackMessage: str = Field(min_length=1, max_length=500)
    welcomeMessage: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=120)
    temperature: float | None = Field(default=None, ge=0, le=2)
    language: str | None = Field(default=None, min_length=2, max_length=35)
    collectLead: bool | None = None
    leadCollectionEnabled: bool | None = None
    leadFields: list[Literal["name", "email", "phone", "requirement"]] | None = Field(default=None, max_length=4)
    notificationEmail: str | None = None
    notificationChannels: list[Literal["email", "webhook"]] | None = Field(default=None, max_length=2)
    theme: Theme | None = None
    widgetSettings: WidgetSettings | None = None
    analyticsSettings: AnalyticsSettings | None = None
    widget: Widget | None = None
    topK: int | None = Field(default=None, ge=1, le=40)
    minSimilarity: float | None = Field(default=None, ge=-1, le=1)
    @field_validator("teamEmail", "notificationEmail")
    @classmethod
    def check_emails(cls, value: str | None) -> str | None:
        return StrictModel.validate_email(value) if value is not None else None

class CreateClientBody(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    domains: list[str] = Field(min_length=1, max_length=30)
    config: ClientConfig
    prompt: str = Field(min_length=1, max_length=20000)

class ChatBody(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    sessionId: UUID | None = None

class LeadBody(StrictModel):
    conversationId: UUID | None = None
    name: str = Field(min_length=1, max_length=120)
    email: str | None = None
    phone: str | None = Field(default=None, max_length=40)
    requirement: str | None = Field(default=None, max_length=2000)
    message: str | None = Field(default=None, max_length=2000)
    @field_validator("name", "email", "phone", "requirement", "message")
    @classmethod
    def strip_values(cls, value: str | None, info) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if "\r" in value or "\n" in value:
            raise ValueError("Lead fields contain invalid characters")
        if info.field_name == "name" and not value:
            raise ValueError("Lead name cannot be empty")
        return value
    @field_validator("email")
    @classmethod
    def check_email(cls, value: str | None) -> str | None:
        return StrictModel.validate_email(value) if value else value
    @model_validator(mode="after")
    def require_message(self):
        if not (self.requirement or self.message):
            raise ValueError("Message is required")
        return self

class ClientPatchBody(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    config: ClientConfig | None = None
    domains: list[str] | None = Field(default=None, min_length=1, max_length=30)

class LeadPatchBody(StrictModel):
    status: Literal["new", "contacted", "qualified", "won", "lost"] | None = None
    assignee: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=10000)

class PromptPreviewBody(StrictModel):
    question: str = Field(min_length=1, max_length=1000)
    prompt: str = Field(min_length=1, max_length=20000)

class DuplicateClientBody(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")

class ProviderBody(StrictModel):
    provider: Literal["local", "nvidia", "openai", "openrouter", "groq", "together", "deepseek", "custom", "azure"]
    baseUrl: str | None = None
    model: str | None = Field(default=None, max_length=200)
    apiKey: str | None = Field(default=None, min_length=1, max_length=1000)
    temperature: float = Field(default=0, ge=0, le=2)
    maxTokens: int | None = Field(default=None, ge=1, le=100000)
    @field_validator("baseUrl")
    @classmethod
    def check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if any(ch in value for ch in "\r\n\x00"):
            raise ValueError("Base URL must not contain control characters")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError("Base URL must be a valid HTTP(S) URL without credentials, query, or fragment")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Base URL contains an invalid port") from exc
        return value.rstrip("/")

    @field_validator("model")
    @classmethod
    def check_model_text(cls, value: str | None) -> str | None:
        if value is not None and any(ch in value for ch in "\r\n\x00"):
            raise ValueError("Model must not contain control characters")
        return value.strip() if value is not None else value
