import pytest

from aci.evaluate import main, rates, simulate


def test_decaying_meets_targets_and_is_steadier_than_constant():
    dec, con = simulate("decaying", 20_000), simulate("constant", 20_000, scale=0.2)
    rd, rc = rates(dec, start=4_000), rates(con, start=4_000)
    assert rd["normal_not_passed"] == pytest.approx(0.05, abs=0.015)
    assert rd["attack_not_flagged"] <= 0.13
    assert rd["late_threshold_jitter"] < rc["late_threshold_jitter"] / 3


def test_command_line_with_plot(tmp_path):
    pytest.importorskip("matplotlib")
    out = tmp_path / "aci.png"
    assert main(["--n", "3000", "--drift", "--plot", str(out)]) == 0
    assert out.read_bytes()[:4] == b"\x89PNG"
