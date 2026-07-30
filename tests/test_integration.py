def test_all_public_api_importable():
    """Simulate what a downstream module repo does: import everything."""
    import woodard_module_helpers as wmh

    # Exercise each export is callable / instantiable.
    assert wmh.Settings()
    assert callable(wmh.prefix)
    assert callable(wmh.current_user)
    assert callable(wmh.require_role("reservoir"))
    assert callable(wmh.require_any_role("reservoir", "land"))
    assert callable(wmh.require_capability)
    assert callable(wmh.require_any_capability)
    assert callable(wmh.has_capability)
    assert callable(wmh.has_any_capability)
    assert wmh.has_capability({"roles": ["admin"]}, "anything") is True
    assert wmh.has_any_capability({"roles": []}, "x") is False
    assert callable(wmh.compute_capability_signature)
    assert wmh.__version__
