from madosho_server.settings import Settings


def test_llm_settings_default_to_none(monkeypatch):
    monkeypatch.delenv("MADOSHO_LLM_API_KEY", raising=False)
    monkeypatch.delenv("MADOSHO_LLM_API_BASE", raising=False)
    s = Settings.from_env()
    assert s.llm_api_key is None
    assert s.llm_api_base is None


def test_llm_settings_blank_env_coerces_to_none(monkeypatch):
    monkeypatch.setenv("MADOSHO_LLM_API_KEY", "")
    monkeypatch.setenv("MADOSHO_LLM_API_BASE", "")
    s = Settings.from_env()
    assert s.llm_api_key is None
    assert s.llm_api_base is None


def test_llm_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("MADOSHO_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("MADOSHO_LLM_API_BASE", "http://ollama:11434")
    s = Settings.from_env()
    assert s.llm_api_key == "sk-test"
    assert s.llm_api_base == "http://ollama:11434"
