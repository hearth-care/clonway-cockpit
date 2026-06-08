def test_public_api_is_importable_from_package_root():
    from clonway_cockpit.gateway import (
        Completion,
        Gateway,
        GatewayConfig,
        GatewayError,
        Message,
        OpenAICompatibleAdapter,
        RoleConfig,
        Usage,
        load_events,
        record_call,
    )

    assert Gateway is not None
    assert issubclass(GatewayError, RuntimeError)
    # smoke: build a config + gateway object (no call)
    cfg = GatewayConfig.from_dict(
        {"roles": {"chat": {"provider": "openai_compatible", "base_url": "u", "model": "m"}}}
    )
    assert isinstance(Gateway(cfg), Gateway)
    assert callable(record_call) and callable(load_events)
    assert RoleConfig and Completion and Usage and Message and OpenAICompatibleAdapter
