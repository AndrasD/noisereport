from src import __version__


def test_version_present() -> None:
    assert __version__
    assert isinstance(__version__, str)
