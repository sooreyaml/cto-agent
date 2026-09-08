from src.connections.redact import redact_obj, redact_secrets


def test_redact_github_and_granola_tokens() -> None:
    text = "pat gho_abcdefghijklmnopqrstuvwxyz1234 and grn_abcdefghijklmnopqrstuvwxyz"
    out = redact_secrets(text)
    assert "gho_" not in out
    assert "grn_" not in out
    assert "[redacted]" in out


def test_redact_obj_hides_token_keys() -> None:
    assert redact_obj({"token": "secret", "note": "ok"}) == {"token": "[redacted]", "note": "ok"}
