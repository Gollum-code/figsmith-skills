import base64
import json
import sys
import tempfile
import urllib.parse
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backends.drawio import mxfile_to_ir

XML = (
    '<mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1" '
    'pageWidth="850" pageHeight="1100"><root>'
    '<mxCell id="0"/><mxCell id="1" parent="0"/>'
    '<mxCell id="a" value="Client" style="rounded=1;whiteSpace=wrap;" vertex="1" parent="1">'
    '<mxGeometry x="80" y="60" width="140" height="50" as="geometry"/></mxCell>'
    '<mxCell id="b" value="Server" style="rounded=1;whiteSpace=wrap;" vertex="1" parent="1">'
    '<mxGeometry x="80" y="220" width="140" height="50" as="geometry"/></mxCell>'
    '<mxCell id="z" value="Data" style="rounded=0;whiteSpace=wrap;container=1;" vertex="1" parent="1">'
    '<mxGeometry x="40" y="360" width="240" height="120" as="geometry"/></mxCell>'
    '<mxCell id="e0" value="request" style="edgeStyle=orthogonalEdgeStyle;" edge="1" '
    'parent="1" source="a" target="b"><mxGeometry relative="1" as="geometry"/></mxCell>'
    '</root></mxGraphModel>'
)

# draw.io's compressed form: raw DEFLATE (no zlib header) then base64 then URL-encode.
compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
body = compressor.compress(XML.encode("utf-8")) + compressor.flush()
b64 = base64.b64encode(body).decode("ascii").rstrip("=")
# base64url with padding stripped, exactly like draw.io writes it
encoded = urllib.parse.quote(b64, safe="")
mxfile = (
    '<mxfile host="app" version="24.0.0">'
    f'<diagram id="x" name="comp">{encoded}</diagram></mxfile>'
)

tmp = Path(tempfile.gettempdir())
(tmp / "comp.drawio").write_text(mxfile, encoding="utf-8")

ir = mxfile_to_ir(mxfile, "academic")
ids = [n["id"] for n in ir["topology"]["nodes"]]
kinds = {n["id"]: n["kind"] for n in ir["topology"]["nodes"]}
edges = [(e["from"], e["to"], e.get("label")) for e in ir["topology"]["edges"]]
labels = {k: v for k, v in ir["content"]["labels"].items()}

assert ids == ["a", "b", "z"], ids
assert kinds["z"] == "band", kinds
assert edges == [("a", "b", "el_0")], edges
assert labels["a"] == "Client" and labels["b"] == "Server", labels
assert labels["el_0"] == "request", labels

print("OK compressed drawio -> IR")
print("  nodes:", [(n["id"], n["kind"]) for n in ir["topology"]["nodes"]])
print("  edges:", edges)
print("  labels:", labels)
print("  geometry kept:", sorted(ir["layout"]["nodes"]))
