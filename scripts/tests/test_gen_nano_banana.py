import importlib.util, pathlib
spec = importlib.util.spec_from_file_location(
    "gen_nano_banana",
    pathlib.Path(__file__).resolve().parent.parent / "gen_nano_banana.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_flatten_prompts_expands_variations():
    data = {
        "campaign": "launch",
        "concepts": [
            {"slug": "hero", "variations": ["prompt a", "prompt b"]},
        ],
    }
    out = mod.flatten_prompts(data)
    assert [p["name"] for p in out] == ["01_hero", "02_hero"]
    assert out[0]["campaign"] == "launch"
    assert out[1]["prompt"] == "prompt b"
