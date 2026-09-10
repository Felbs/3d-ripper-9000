"""The batch runner's state file (batch_results.jsonl)."""

from gcrip import batch as batch_mod

def test_load_jsonl_survives_a_utf8_bom(tmp_path):
    """batch_results.jsonl is the run's memory; a BOM (what PowerShell's `Set-Content
    -Encoding utf8` writes) must not make every later rip die on line 1."""
    p = tmp_path / "batch_results.jsonl"
    p.write_bytes(b'\xef\xbb\xbf{"file": "a.iso"}\r\n{"file": "b.iso"}\n\n')
    assert [r["file"] for r in batch_mod._load_jsonl(p)] == ["a.iso", "b.iso"]
