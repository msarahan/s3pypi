from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import indent
from typing import Dict, Optional


@dataclass
class Hash:
    name: str
    value: str

    @classmethod
    def of(cls, name: str, path: Path) -> Hash:
        h = hashlib.new(name)
        with open(path, "rb") as file:
            while True:
                block = file.read(65536)
                if not block:
                    break
                h.update(block)
        return cls(name, h.hexdigest())


@dataclass
class Index:
    filenames: Dict[str, Optional[Hash]] = field(default_factory=dict)

    @classmethod
    def parse(cls, html: str) -> Index:
        matches = re.findall(r'<a href=".+?((\w+)=(\w+))?">(.+)</a>', html)
        filenames = {
            fname: Hash(hash_name, hash_value) if hash_name else None
            for _, hash_name, hash_value, fname in matches
        }
        return cls(filenames)

    def to_html(self) -> str:
        links = "<br>\n".join(
            f'<a href="{urllib.parse.quote(fname)}'
            + (f"#{hash_.name}={hash_.value}" if hash_ else "")
            + f'">{fname.rstrip("/")}</a>'
            for fname, hash_ in sorted(self.filenames.items())
        )
        return index_html.format(body=indent(links, " " * 4))

    def to_json(self, api_version: str = "1.0") -> str:
        """Generate PEP 691 compliant JSON index."""
        if not self.filenames:
            # Empty index
            data = {
                "api-version": api_version,
                "files": []
            }
        elif all(fname.endswith("/") for fname in self.filenames):
            # Root index with project names
            data = {
                "api-version": api_version,
                "projects": [
                    {"name": fname.rstrip("/")}
                    for fname in sorted(self.filenames.keys())
                ]
            }
        else:
            # Package index with files
            files = []
            for fname, hash_ in sorted(self.filenames.items()):
                file_entry = {
                    "filename": fname,
                    "url": urllib.parse.quote(fname)
                }
                if hash_:
                    file_entry["hashes"] = {hash_.name: hash_.value}
                files.append(file_entry)
            
            data = {
                "api-version": api_version,
                "files": files
            }
        
        return json.dumps(data, indent=2)

    @classmethod
    def parse_json(cls, json_str: str) -> Index:
        """Parse PEP 691 JSON index format."""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return cls()
        
        filenames = {}
        
        # Handle root index format (projects list)
        if "projects" in data:
            for project in data["projects"]:
                project_name = project["name"]
                filenames[f"{project_name}/"] = None
        
        # Handle package index format (files list)
        elif "files" in data:
            for file_info in data["files"]:
                filename = file_info["filename"]
                hashes = file_info.get("hashes", {})
                
                if hashes:
                    # Take the first hash (usually sha256)
                    hash_name, hash_value = next(iter(hashes.items()))
                    filenames[filename] = Hash(hash_name, hash_value)
                else:
                    filenames[filename] = None
        
        return cls(filenames)


index_html = """
<!DOCTYPE html>
<html>
  <head>
    <meta charset="UTF-8">
    <title>Package Index</title>
  </head>
  <body>
{body}
  </body>
</html>
""".strip()
