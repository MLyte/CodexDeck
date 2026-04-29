def test_core_and_runner_are_importable() -> None:
    import codexdeck
    import codexdeck.app
    import codexdeck.cli
    import codexdeck.core
    import codexdeck.runner
    import codexdeck.ui
    import codexdeck_core
    import codexdeck_runner

    assert codexdeck.__version__
    assert codexdeck.app.Cockpit
    assert codexdeck.cli.main
    assert codexdeck.core.CockpitConfig
    assert codexdeck.runner.CodexProcessRunner
    assert codexdeck.ui.render_frame
    assert codexdeck_core.CockpitConfig
    assert codexdeck_runner.CodexProcessRunner
