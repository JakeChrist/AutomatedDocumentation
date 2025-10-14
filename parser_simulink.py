"""Parser for Simulink model files used by DocGen-LM."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile


@dataclass
class _SimulinkEndpoint:
    block: str
    port: str | None = None

    def format(self) -> str:
        if self.port:
            return f"{self.block}:{self.port}"
        return self.block


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_parameters(block_element: ET.Element) -> List[Dict[str, str]]:
    params: List[Dict[str, str]] = []
    for child in block_element:
        if _strip_namespace(child.tag) != "P":
            continue
        name = child.attrib.get("Name")
        value = (child.text or "").strip()
        if not name:
            continue
        if value:
            params.append({"name": name, "value": value})
    return params


def _parse_blockdiagram_xml(xml_text: str) -> Dict[str, Any]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:  # pragma: no cover - defensive, validated in tests
        raise SyntaxError(f"Invalid Simulink XML: {exc}") from exc

    def _iter_blocks():
        for elem in root.iter():
            if _strip_namespace(elem.tag) == "Block":
                yield elem

    blocks: List[Dict[str, Any]] = []
    for block in _iter_blocks():
        block_info: Dict[str, Any] = {
            "name": block.attrib.get("Name") or "Unnamed block",
            "type": block.attrib.get("BlockType") or block.attrib.get("BlockTypeEnum") or "Unknown",
        }
        params = _parse_parameters(block)
        if params:
            block_info["parameters"] = params
        blocks.append(block_info)

    connections: List[Dict[str, str]] = []
    for elem in root.iter():
        if _strip_namespace(elem.tag) != "Line":
            continue
        src_elem = elem.find("./Src")
        dst_elem = elem.find("./Dst")
        if src_elem is None or dst_elem is None:
            continue
        src = _SimulinkEndpoint(src_elem.attrib.get("Block", "?"), src_elem.attrib.get("Port"))
        dst = _SimulinkEndpoint(dst_elem.attrib.get("Block", "?"), dst_elem.attrib.get("Port"))
        connections.append({"source": src.format(), "target": dst.format()})

    model_name = root.attrib.get("Name") or root.findtext(".//ModelInformation/ModelName")

    return {
        "name": model_name or "SimulinkModel",
        "blocks": blocks,
        "connections": connections,
    }


def _read_slx_blockdiagram(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            for name in archive.namelist():
                if name.lower().endswith("blockdiagram.xml"):
                    with archive.open(name) as stream:
                        return stream.read().decode("utf-8", errors="ignore")
    except BadZipFile as exc:  # pragma: no cover - defensive
        raise SyntaxError(f"Invalid SLX archive: {exc}") from exc
    raise SyntaxError("SLX archive does not contain a block diagram XML file")


def _parse_mdl_text(text: str) -> Dict[str, Any]:
    block_pattern = re.compile(
        r"Block\s*\{(?P<body>.*?)\n\s*\}", re.DOTALL
    )
    name_pattern = re.compile(r'\bName\s+"(?P<name>[^\"]+)"')
    type_pattern = re.compile(r'\bBlockType\s+"(?P<type>[^\"]+)"')
    param_pattern = re.compile(r'\b(?P<key>[A-Za-z0-9_]+)\s+"(?P<value>[^\"]*)"')

    blocks: List[Dict[str, Any]] = []
    for match in block_pattern.finditer(text):
        body = match.group("body")
        name_match = name_pattern.search(body)
        type_match = type_pattern.search(body)
        block_info: Dict[str, Any] = {
            "name": name_match.group("name") if name_match else "Unnamed block",
            "type": type_match.group("type") if type_match else "Unknown",
        }
        params = []
        for param in param_pattern.finditer(body):
            key = param.group("key")
            if key in {"Name", "BlockType"}:
                continue
            value = param.group("value").strip()
            if value:
                params.append({"name": key, "value": value})
        if params:
            block_info["parameters"] = params
        blocks.append(block_info)

    model_match = re.search(r'Model\s+\{\s*Name\s+"(?P<name>[^\"]+)"', text)
    model_name = model_match.group("name") if model_match else "SimulinkModel"

    return {
        "name": model_name,
        "blocks": blocks,
        "connections": [],
    }


def _model_overview(model: Dict[str, Any]) -> str:
    lines = [f"Simulink model: {model.get('name', 'SimulinkModel')}"]
    blocks = model.get("blocks", [])
    if blocks:
        lines.append("")
        lines.append("Blocks:")
        for block in blocks:
            label = block.get("name", "Unnamed block")
            btype = block.get("type", "Unknown")
            params = block.get("parameters", [])
            if params:
                param_text = ", ".join(f"{p['name']}={p['value']}" for p in params)
                lines.append(f"- {label} [{btype}] ({param_text})")
            else:
                lines.append(f"- {label} [{btype}]")
    connections = model.get("connections", [])
    if connections:
        lines.append("")
        lines.append("Connections:")
        for conn in connections:
            lines.append(f"- {conn['source']} -> {conn['target']}")
    return "\n".join(lines)


def parse_simulink_file(path: str) -> Dict[str, Any]:
    """Parse a Simulink ``.slx`` or ``.mdl`` file into a structured summary."""

    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".slx":
        xml_text = _read_slx_blockdiagram(file_path)
        model = _parse_blockdiagram_xml(xml_text)
        return {"model": model, "module_docstring": _model_overview(model), "source_text": xml_text}
    if suffix == ".mdl":
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        model = _parse_mdl_text(text)
        return {"model": model, "module_docstring": _model_overview(model), "source_text": text}
    raise SyntaxError(f"Unsupported Simulink file type: {file_path.suffix}")
