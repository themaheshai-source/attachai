"""LLM adapters with explicit failure status and safe provider error handling."""
import os
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str = "local"
    raw: dict | None = None
    ok: bool = True


class BaseLLM:
    def generate(self, prompt, **kwargs) -> LLMResponse:
        raise NotImplementedError


class LocalLLM(BaseLLM):
    """Deterministic, extractive offline fallback; it is not presented as a remote model."""
    def generate(self, prompt, **kwargs):
        import re
        match = re.search(r"\[Source 1:[^\]\n]*\]\n(.+?)(?:\n\n\[Source|$)", prompt, re.S)
        if match:
            fact = " ".join(match.group(1).strip().split())
            return LLMResponse(f"Based on the retrieved evidence: {fact} [Source 1]", "local")
        return LLMResponse("I cannot provide a grounded answer because no evidence was retrieved.", "local")


class OpenAICompatibleLLM(BaseLLM):
    def __init__(self, api_key=None, model="gpt-4o-mini", base_url=None, timeout_seconds=None, max_retries=None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url
        try:
            self.timeout_seconds = max(1.0, float(timeout_seconds if timeout_seconds is not None else os.getenv("LLM_TIMEOUT_MS", "30000")) / (1000.0 if timeout_seconds is None else 1.0))
        except (TypeError, ValueError):
            self.timeout_seconds = 30.0
        try:
            self.max_retries = max(0, min(8, int(max_retries if max_retries is not None else os.getenv("LLM_MAX_RETRIES", "2"))))
        except (TypeError, ValueError):
            self.max_retries = 2

    def generate(self, prompt, **kwargs):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url or None, timeout=self.timeout_seconds, max_retries=self.max_retries)
            request_options = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": kwargs.get("temperature", 0),
                "max_tokens": kwargs.get("max_tokens", 1000),
            }
            if kwargs.get("json_mode"):
                request_options["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**request_options)
            text = response.choices[0].message.content or ""
            return LLMResponse(text, response.model or self.model, response.model_dump() if hasattr(response, "model_dump") else {})
        except Exception as exc:
            # Do not return provider exception text: it can contain endpoint/config data.
            return LLMResponse("LLM provider unavailable.", self.model, {"error_type": type(exc).__name__}, ok=False)


class GeminiLLM(BaseLLM):
    def __init__(self, api_key=None, model="gemini-1.5-flash", timeout_seconds=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model
        try:
            self.timeout_seconds = max(1.0, float(timeout_seconds if timeout_seconds is not None else os.getenv("LLM_TIMEOUT_MS", "30000")) / (1000.0 if timeout_seconds is None else 1.0))
        except (TypeError, ValueError):
            self.timeout_seconds = 30.0

    def generate(self, prompt, **kwargs):
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            generation_config = {
                "temperature": kwargs.get("temperature", 0),
                "max_output_tokens": kwargs.get("max_tokens", 1000),
            }
            if kwargs.get("json_mode"):
                generation_config["response_mime_type"] = "application/json"
            response = genai.GenerativeModel(self.model).generate_content(
                prompt, generation_config=generation_config, request_options={"timeout": self.timeout_seconds}
            )
            return LLMResponse(getattr(response, "text", "") or "", self.model)
        except Exception as exc:
            return LLMResponse("LLM provider unavailable.", self.model, {"error_type": type(exc).__name__}, ok=False)


def get_llm(provider="none", **kwargs):
    selected = (provider or "none").lower()
    if selected in {"openai", "nvidia", "openai-compatible", "openai_compatible"}:
        base_url = kwargs.get("base_url") or ("https://integrate.api.nvidia.com/v1" if selected == "nvidia" else None)
        default_model = "meta/llama-3.1-8b-instruct" if selected == "nvidia" else "gpt-4o-mini"
        return OpenAICompatibleLLM(api_key=kwargs.get("api_key"), model=kwargs.get("model") or default_model, base_url=base_url,
                                   timeout_seconds=kwargs.get("timeout_seconds"), max_retries=kwargs.get("max_retries"))
    if selected in {"gemini", "google"}:
        return GeminiLLM(api_key=kwargs.get("api_key"), model=kwargs.get("model") or "gemini-1.5-flash",
                         timeout_seconds=kwargs.get("timeout_seconds"))
    return LocalLLM()
