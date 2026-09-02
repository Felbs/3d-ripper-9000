"""A plugin that recognises a file and produces nothing must leave a trace.

The rip used to delete the record - `result.models.remove(r)` with the comment "not this
plugin's file after all".  That is true for a *fallback*, which only ever probes speculatively.
It is false for an ordinary plugin, whose `detect()` said it recognised the format: returning no
scenes is then a fact, and deleting the record made "silently read as empty" indistinguishable
from "nobody claimed it".

That is exactly what hid 89 objects on FIFA 2003 and 247 on Fight Night Round 2 behind a
healthy-looking zero.
"""

from __future__ import annotations

from gcrip.rip import ModelResult


def test_model_result_carries_the_empty_flag():
    r = ModelResult(path="x", out_rel=None, sha1=None)
    assert r.empty is False
    r.empty = True
    assert r.empty is True


def test_empty_is_not_an_error_and_not_an_export():
    """The three outcomes must stay distinct: exported, failed, and claimed-but-empty.

    A skeleton-only EAGL object legitimately has no mesh, so counting it as a failure would be
    wrong - but so is counting it as nothing at all.
    """
    exported = ModelResult(path="a", out_rel="a.gltf", sha1=None, triangles=10)
    failed = ModelResult(path="b", out_rel=None, sha1=None)
    failed.error = "eagl: EaglError: no models"
    empty = ModelResult(path="c", out_rel=None, sha1=None)
    empty.empty = True

    models = [exported, failed, empty]
    assert sum(1 for m in models if m.out_rel) == 1
    assert sum(1 for m in models if m.error) == 1
    assert sum(1 for m in models if m.empty) == 1
    assert empty.error is None, "an empty result must not be reported as a failure"
    assert not empty.out_rel


def test_only_fallbacks_may_vanish_without_a_record():
    """The distinction the fix rests on: `gx` and `generic` probe every file they are offered,
    so a record for each miss would be noise.  Everything else declared it recognised the file.
    """
    from gcrip.plugins import all_plugins, is_fallback

    fallbacks = {getattr(m, "NAME", m.__name__) for m in all_plugins() if is_fallback(m)}
    assert fallbacks == {"gx", "generic"}, (
        "if a new fallback appears it must be added deliberately - every non-fallback plugin "
        "now leaves a claimed-but-empty record instead of vanishing"
    )
