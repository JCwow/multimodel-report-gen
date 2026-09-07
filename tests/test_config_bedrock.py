import app.config as config


def test_use_bedrock_false_without_aws_credentials(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setattr(config, "has_aws_credentials", lambda: False)
    assert config.use_bedrock() is False


def test_use_bedrock_true_with_flag_and_creds(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setattr(config, "has_aws_credentials", lambda: True)
    assert config.use_bedrock() is True


def test_has_credentials_via_anthropic_key(monkeypatch):
    monkeypatch.setattr(config, "use_bedrock", lambda: False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert config.has_anthropic_api_key() is True
