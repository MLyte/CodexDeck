def test_core_and_runner_are_importable() -> None:
    import codexdeck_core
    import codexdeck_runner

    assert codexdeck_core.CockpitConfig
    assert codexdeck_runner.CodexProcessRunner

