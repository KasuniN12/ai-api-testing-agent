"""Configuration verification script.

Tests that Pydantic BaseSettings loads environment variables and prints them
safely without exposing sensitive keys.
"""

from config.settings import get_settings


def mask_secret(secret: str) -> str:
    """Mask sensitive secret values for safe terminal display."""
    if not secret or secret == "your_openai_api_key_here":
        return "[NOT CONFIGURED / PLACEHOLDER]"
    if len(secret) <= 8:
        return "****"
    return f"{secret[:4]}...{secret[-4:]}"


def main():
    print("=" * 60)
    print("[*] Testing Application Configuration")
    print("=" * 60)

    try:
        settings = get_settings()

        print(f"Base Directory:       {settings.BASE_DIR}")
        print(f"OpenAI Model:         {settings.OPENAI_MODEL}")
        print(f"OpenAI Temperature:   {settings.OPENAI_TEMPERATURE}")
        print(f"OpenAI API Key:       {mask_secret(settings.OPENAI_API_KEY)}")
        print(f"Target API Base URL:  {settings.TARGET_API_BASE_URL}")
        print(f"OpenAPI Spec Path:    {settings.OPENAPI_SPEC_PATH}")
        print(f"Execution Timeout:    {settings.EXECUTION_TIMEOUT}s")
        print(f"Docker Sandbox:       {settings.ENABLE_DOCKER_SANDBOX}")
        print(f"Artifacts Dir:        {settings.ARTIFACTS_DIR}")
        print(f"Reports Dir:          {settings.REPORTS_DIR}")
        print(f"Generated Tests Dir:  {settings.GENERATED_TESTS_DIR}")

        print("=" * 60)
        print("[SUCCESS] Configuration loaded successfully!")
        print("=" * 60)
    except Exception as e:
        print(f"[ERROR] Failed to load configuration: {e}")
        raise


if __name__ == "__main__":
    main()
