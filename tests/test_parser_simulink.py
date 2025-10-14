from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from parser_simulink import parse_simulink_file


def _create_slx(tmp_path: Path) -> Path:
    xml = """<?xml version='1.0' encoding='utf-8'?>
<BlockDiagram Name="simple">
  <System>
    <Block Name="Gain" BlockType="Gain">
      <P Name="Gain">5</P>
    </Block>
    <Block Name="Constant" BlockType="Constant">
      <P Name="Value">10</P>
    </Block>
    <Line>
      <Src Block="Constant" Port="1" />
      <Dst Block="Gain" Port="1" />
    </Line>
  </System>
</BlockDiagram>
"""
    slx_path = tmp_path / "model.slx"
    with ZipFile(slx_path, "w") as archive:
        archive.writestr("simulink/blockdiagram.xml", xml)
    return slx_path


def _create_mdl(tmp_path: Path) -> Path:
    text = """Model {\n  Name "simple"\n}\nBlock {\n  Name "Gain"\n  BlockType "Gain"\n  Gain "5"\n}\nBlock {\n  Name "Constant"\n  BlockType "Constant"\n  Value "10"\n}\n"""
    mdl_path = tmp_path / "model.mdl"
    mdl_path.write_text(text, encoding="utf-8")
    return mdl_path


def test_parse_slx_model(tmp_path: Path) -> None:
    path = _create_slx(tmp_path)
    parsed = parse_simulink_file(str(path))
    model = parsed["model"]

    assert model["name"] == "simple"
    block_names = {block["name"] for block in model["blocks"]}
    assert {"Gain", "Constant"} == block_names
    connections = model["connections"]
    assert connections == [{"source": "Constant:1", "target": "Gain:1"}]
    assert "Simulink model: simple" in parsed["module_docstring"]


def test_parse_mdl_model(tmp_path: Path) -> None:
    path = _create_mdl(tmp_path)
    parsed = parse_simulink_file(str(path))
    model = parsed["model"]

    assert model["name"] == "simple"
    assert any(block["name"] == "Gain" for block in model["blocks"])
    assert not model["connections"]
    assert "Blocks:" in parsed["module_docstring"]


def test_parse_simulink_rejects_unknown_extension(tmp_path: Path) -> None:
    dummy = tmp_path / "model.foo"
    dummy.write_text("test", encoding="utf-8")
    with pytest.raises(SyntaxError):
        parse_simulink_file(str(dummy))
