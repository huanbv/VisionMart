from app.vision import config


def test_checkout_scan_defaults_on_for_checkout_cameras(monkeypatch):
    monkeypatch.delenv("CHECKOUT_SCAN_MODE", raising=False)
    monkeypatch.delitem(config._OVERRIDES, "CHECKOUT_SCAN_MODE", raising=False)

    assert config.VisionConfig().checkout_scan_mode is True


def test_checkout_scan_can_still_be_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("CHECKOUT_SCAN_MODE", "false")
    monkeypatch.delitem(config._OVERRIDES, "CHECKOUT_SCAN_MODE", raising=False)

    assert config.VisionConfig().checkout_scan_mode is False
