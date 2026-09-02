

def test_buffer_name_avoids_a_container_directory():
    """A container named `pl01.bin` expands into a directory of that name, and the glTF buffer
    for a model called `pl01` wants the same path.  Writing a file where a directory sits is a
    PermissionError on Windows, and it killed the whole export (`pl01.tpl` on Viewtiful Joe).
    """
    import json
    import tempfile
    from pathlib import Path

    import numpy as np

    from ripcore import gltf
    from ripcore.scene import MaterialDef, Primitive, Scene

    d = Path(tempfile.mkdtemp())
    (d / "pl01.bin").mkdir()
    s = Scene(name="pl01")
    s.materials.append(MaterialDef("m", None))
    s.primitives.append(
        Primitive(
            material=0,
            positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "f4"),
            indices=np.array([0, 1, 2], "i4"),
        )
    )
    gltf.export(s, d / "pl01")
    doc = json.loads((d / "pl01.gltf").read_text(encoding="utf-8"))
    uri = doc["buffers"][0]["uri"]
    assert uri != "pl01.bin"
    # and the URI must name the file that was actually written, or the glTF is broken
    assert (d / uri).is_file()
    assert (d / uri).stat().st_size == doc["buffers"][0]["byteLength"]
