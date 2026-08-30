

def test_afs_is_actually_registered_as_a_container():
    """all_plugins() only keeps a module that has BOTH detect and extract.

    The AFS container carried is_container/expand but no detect/extract pair, so it was never
    registered and no AFS archive on any of 31 discs was ever expanded - silently.
    """
    from gcrip.plugins import container_plugins

    names = [m.NAME for m in container_plugins()]
    assert "afs" in names
    assert "lpac" in names


def test_every_container_plugin_is_registered():
    """Guard the whole class of bug, not just the two that had it."""
    import importlib
    import pkgutil

    import gcrip.plugins as package
    from gcrip.plugins import container_plugins

    registered = {m.NAME for m in container_plugins()}
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"gcrip.plugins.{info.name}")
        if hasattr(mod, "is_container") and hasattr(mod, "expand"):
            assert getattr(mod, "NAME", info.name) in registered, (
                f"{info.name} is a container but is not registered: it needs detect/extract too"
            )
