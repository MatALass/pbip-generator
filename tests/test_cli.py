from __future__ import annotations

from pbip_generator.cli import main


def test_cli_build_and_init_config(example_data, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(example_data), "-o", str(out), "--data-folder", "C:\\pbi\\data"]) == 0
    assert (out / "Data" / "Data.pbip").exists() or any(out.glob("*/*.pbip"))
    text = capsys.readouterr().out
    assert "fact      Ventes" in text and "C:\\pbi\\data\\" in text

    assert main(["build", str(example_data), "-o", str(out)]) == 1  # exists, no --overwrite

    cfg = tmp_path / "cfg.yaml"
    assert main(["init-config", str(example_data), "-o", str(cfg)]) == 0
    assert "Ventes[ClientID] -> Clients[ClientID]" in cfg.read_text(encoding="utf-8")
    assert main(["build", str(example_data), "-o", str(out), "-c", str(cfg), "--overwrite"]) == 0
