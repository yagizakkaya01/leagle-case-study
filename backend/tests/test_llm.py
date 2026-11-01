"""Which timeout each model caller gets. No network: ChatNVIDIA is replaced by a recorder."""
from app import llm
from app.config import Settings, settings


def test_chat_waits_longer_than_the_optional_metadata_call(monkeypatch):
    timeouts = []
    monkeypatch.setattr(llm, "ChatNVIDIA", lambda **kwargs: timeouts.append(kwargs["timeout"]))
    monkeypatch.setattr(settings, "NVIDIA_API_KEY", "not-a-real-key")

    llm.get_chat_model()
    llm.get_metadata_model()

    assert timeouts == [settings.LLM_TIMEOUT_SECONDS, settings.METADATA_TIMEOUT_SECONDS]
    assert Settings.model_fields["LLM_TIMEOUT_SECONDS"].default == 180
    assert Settings.model_fields["METADATA_TIMEOUT_SECONDS"].default == 60
