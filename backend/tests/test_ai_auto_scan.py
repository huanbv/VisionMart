from app.modules.camera.application.ai_auto_scan import _paused_from_value


def test_missing_override_follows_disabled_deployment_default():
    assert _paused_from_value(None, default_enabled=False) is True


def test_missing_override_follows_enabled_deployment_default():
    assert _paused_from_value(None, default_enabled=True) is False


def test_explicit_ui_enable_overrides_disabled_deployment_default():
    assert _paused_from_value("0", default_enabled=False) is False


def test_explicit_ui_pause_overrides_enabled_deployment_default():
    assert _paused_from_value("1", default_enabled=True) is True
