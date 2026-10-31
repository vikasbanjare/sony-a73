"""Runs the full end-to-end simulation (``a7iii sim``) as part of the test suite."""

import json

import pytest

from a7iii.sim.scenarios import run_all, scenario_keys

EXPECTED_NOT_PASS = {"nvram_locked": "BLOCKED", "tier4_limits": "LIMIT"}


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    out = tmp_path_factory.mktemp("sim")
    return out, {r.key: r for r in run_all(out)}


@pytest.mark.parametrize("key", scenario_keys())
def test_scenario(results, key):
    _, res = results
    r = res[key]
    expected = EXPECTED_NOT_PASS.get(key, "PASS")
    assert r.status == expected, f"{r.title}: {r.status}\n{json.dumps(r.metrics, indent=1)}\n{r.detail}"


def test_report_written(results):
    out, res = results
    report = (out / "report.md").read_text()
    assert f"{sum(r.status == 'PASS' for r in res.values())} passed" in report
    assert len(json.loads((out / "report.json").read_text())) == len(res)
    for r in res.values():
        for a in r.artifacts:
            assert (out / a).exists(), a
