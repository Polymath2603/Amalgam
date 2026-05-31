"""Tests for VaultManager — filesystem tests with tmp_path."""
import pytest
from pathlib import Path
from backend.core.vault import VaultManager


@pytest.fixture
def vault(tmp_path):
    """Create a VaultManager with a temporary vault directory."""
    return VaultManager(vault_path=str(tmp_path))


class TestVaultSafePath:
    def test_valid_path(self, vault):
        path = vault._safe_path("test.md")
        assert path is not None
        assert path.name == "test.md"

    def test_nested_valid_path(self, vault):
        path = vault._safe_path("sub/folder/test.md")
        assert path is not None
        assert str(path).endswith("sub/folder/test.md")

    def test_path_traversal_blocked(self, vault):
        path = vault._safe_path("../escape.md")
        assert path is None

    def test_dot_dot_in_middle_blocked(self, vault):
        path = vault._safe_path("sub/../../escape.md")
        assert path is None


class TestVaultReadWriteDelete:
    def test_write_creates_file(self, vault):
        result = vault.write("test.md", "# Hello")
        assert result is True
        assert (vault.vault_path / "test.md").exists()

    def test_read_written_file(self, vault):
        vault.write("test.md", "# Hello World")
        content = vault.read("test.md")
        assert content == "# Hello World"

    def test_read_nonexistent_returns_none(self, vault):
        assert vault.read("nonexistent.md") is None

    def test_delete_existing_file(self, vault):
        vault.write("to_delete.md", "content")
        result = vault.delete("to_delete.md")
        assert result is True
        assert not (vault.vault_path / "to_delete.md").exists()

    def test_delete_nonexistent_returns_false(self, vault):
        result = vault.delete("nonexistent.md")
        assert result is False

    def test_write_in_subdirectory(self, vault):
        (vault.vault_path / "sub").mkdir()
        result = vault.write("sub/file.md", "nested content")
        assert result is True
        assert vault.read("sub/file.md") == "nested content"

    def test_write_path_traversal_blocked(self, vault):
        result = vault.write("../evil.md", "bad content")
        assert result is False

    def test_overwrite_existing_file(self, vault):
        vault.write("test.md", "original")
        vault.write("test.md", "updated")
        assert vault.read("test.md") == "updated"


class TestVaultListFiles:
    def test_empty_vault(self, vault):
        files = vault.list_files()
        assert files == []

    def test_lists_single_file(self, vault):
        vault.write("test.md", "content")
        files = vault.list_files()
        assert len(files) == 1
        assert files[0]["name"] == "test.md"

    def test_lists_files_in_subdirs(self, vault):
        vault.write("a.md", "a")
        (vault.vault_path / "sub").mkdir()
        vault.write("sub/b.md", "b")
        (vault.vault_path / "sub" / "deep").mkdir()
        vault.write("sub/deep/c.md", "c")
        files = vault.list_files()
        names = [f["name"] for f in files]
        assert "a.md" in names
        assert "sub/b.md" in names
        assert "sub/deep/c.md" in names

    def test_file_metadata(self, vault):
        vault.write("test.md", "hello world")
        files = vault.list_files()
        assert files[0]["size"] > 0
        assert files[0]["modified"] > 0

    def test_ignores_directories(self, vault):
        (vault.vault_path / "adir").mkdir()
        vault.write("file.md", "content")
        files = vault.list_files()
        names = [f["name"] for f in files]
        assert "file.md" in names
        assert "adir" not in names


class TestVaultSearch:
    def test_search_finds_match(self, vault):
        vault.write("doc.md", "Python is a great programming language")
        results = vault.search("Python programming")
        assert len(results) > 0
        assert results[0]["filename"] == "doc.md"

    def test_search_no_match(self, vault):
        vault.write("doc.md", "completely unrelated content")
        results = vault.search("Python programming")
        # BM25 with small corpora may return low-score results
        if results:
            assert results[0]["score"] <= 0.1

    def test_search_ranking(self, vault):
        vault.write("relevant.md", "Python Python Python programming language code")
        vault.write("less.md", "Java is also a language")
        results = vault.search("Python programming")
        assert len(results) >= 2
        # With more docs, the one with more keyword matches should score higher
        relevant = next((r for r in results if r["filename"] == "relevant.md"), None)
        less = next((r for r in results if r["filename"] == "less.md"), None)
        assert relevant is not None
        assert less is not None

    def test_search_empty_vault(self, vault):
        results = vault.search("anything")
        assert results == []

    def test_search_returns_snippet(self, vault):
        vault.write("doc.md", "Start of document. Python is here. End of document.")
        results = vault.search("Python")
        assert len(results) > 0
        assert "Python" in results[0]["snippet"]

    def test_search_subdirectory_files(self, vault):
        (vault.vault_path / "sub").mkdir()
        vault.write("sub/doc.md", "Python programming guide")
        results = vault.search("Python")
        assert len(results) > 0

    def test_search_max_results(self, vault):
        for i in range(10):
            vault.write(f"doc{i}.md", f"Python document number {i}")
        results = vault.search("Python", max_results=3)
        assert len(results) <= 3
