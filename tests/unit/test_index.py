import json
import pytest

from s3pypi.index import Hash, Index


@pytest.fixture(
    scope="function",
    params=[
        (
            "s3pypi",
            [
                f"s3pypi-{version}{suffix}"
                for version in (
                    "0",
                    "0!0",
                    "0+local",
                    "0.0",
                    "0.1.1",
                    "0.1.2",
                    "0.dev0",
                    "0.post0",
                    "0a0",
                    "0rc0",
                )
                for suffix in (
                    ".tar.gz",
                    "-py2-none-any.whl",
                )
            ],
            [Hash("sha256", "1234" * 16) if i % 3 == 0 else None for i in range(0, 20)],
        )
    ],
)
def index_html(request, data_dir):
    index_name, names, hashes = request.param
    filenames = dict(zip(names, hashes))
    with open(data_dir / "index" / f"{index_name}.html") as f:
        html = f.read().strip()
        yield html, filenames


def test_parse_index(index_html):
    html, expected_filenames = index_html
    index = Index.parse(html)
    assert index.filenames == expected_filenames


def test_render_index(index_html):
    expected_html, filenames = index_html
    html = Index(filenames).to_html()
    assert html == expected_html


def test_json_package_index():
    """Test JSON generation for package index with files."""
    filenames = {
        "hello-world-0.1.0.tar.gz": Hash("sha256", "abc123"),
        "hello_world-0.1.0-py3-none-any.whl": Hash("sha256", "def456"),
        "hello-world-0.2.0.tar.gz": None,  # No hash
    }
    index = Index(filenames)
    json_str = index.to_json()
    
    data = json.loads(json_str)
    assert data["api-version"] == "1.0"
    assert "files" in data
    assert len(data["files"]) == 3
    
    # Check first file with hash
    file1 = next(f for f in data["files"] if f["filename"] == "hello-world-0.1.0.tar.gz")
    assert file1["url"] == "hello-world-0.1.0.tar.gz"
    assert file1["hashes"]["sha256"] == "abc123"
    
    # Check file without hash
    file3 = next(f for f in data["files"] if f["filename"] == "hello-world-0.2.0.tar.gz")
    assert "hashes" not in file3


def test_json_root_index():
    """Test JSON generation for root index with project names."""
    filenames = {
        "hello-world/": None,
        "my-package/": None,
        "another-pkg/": None,
    }
    index = Index(filenames)
    json_str = index.to_json()
    
    data = json.loads(json_str)
    assert data["api-version"] == "1.0"
    assert "projects" in data
    assert len(data["projects"]) == 3
    
    project_names = [p["name"] for p in data["projects"]]
    assert "hello-world" in project_names
    assert "my-package" in project_names
    assert "another-pkg" in project_names


def test_json_empty_index():
    """Test JSON generation for empty index."""
    index = Index()
    json_str = index.to_json()
    
    data = json.loads(json_str)
    assert data["api-version"] == "1.0"
    assert data["files"] == []


def test_parse_json_package_index():
    """Test parsing JSON package index."""
    json_data = {
        "api-version": "1.0",
        "files": [
            {
                "filename": "hello-world-0.1.0.tar.gz",
                "url": "hello-world-0.1.0.tar.gz",
                "hashes": {"sha256": "abc123"}
            },
            {
                "filename": "hello-world-0.2.0.tar.gz",
                "url": "hello-world-0.2.0.tar.gz"
            }
        ]
    }
    
    index = Index.parse_json(json.dumps(json_data))
    assert len(index.filenames) == 2
    assert index.filenames["hello-world-0.1.0.tar.gz"].value == "abc123"
    assert index.filenames["hello-world-0.2.0.tar.gz"] is None


def test_parse_json_root_index():
    """Test parsing JSON root index."""
    json_data = {
        "api-version": "1.0",
        "projects": [
            {"name": "hello-world"},
            {"name": "my-package"}
        ]
    }
    
    index = Index.parse_json(json.dumps(json_data))
    assert len(index.filenames) == 2
    assert "hello-world/" in index.filenames
    assert "my-package/" in index.filenames
    assert index.filenames["hello-world/"] is None


def test_parse_invalid_json():
    """Test parsing invalid JSON returns empty index."""
    index = Index.parse_json("invalid json")
    assert len(index.filenames) == 0


def test_json_api_version():
    """Test custom API version in JSON output."""
    index = Index({"test.whl": None})
    json_str = index.to_json(api_version="2.0")
    
    data = json.loads(json_str)
    assert data["api-version"] == "2.0"
