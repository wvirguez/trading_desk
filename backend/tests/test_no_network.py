from pydantic_ai import models


def test_model_requests_are_disabled_for_the_whole_suite() -> None:
    """D84: ningún test puede llamar a un LLM real."""
    assert models.ALLOW_MODEL_REQUESTS is False
