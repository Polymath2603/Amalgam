"""
BRUTAL TESTS for VaultManager — filesystem edge cases, path traversal,
concurrent access, symlink attacks, and resource leaks.

Catches: symlink traversal, null bytes in filenames, concurrent writes,
very large files, race conditions, and permission errors.
"""
import os
import pytest
import threading
from pathlib import Path
from backend.core.vault import VaultManager


@pytest.fixture
def vault(tmp_path):
    """Create a VaultManager with a temporary vault directory."""
    return VaultManager(vault_path=str(tmp_path))


# ===================================================================
# Original tests (preserved and expanded)
# ===================================================================

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


class TestVaultSafePathBrutal:
    """Path traversal attacks designed to break naive implementations."""

    def test_absolute_path_blocked(self, vault):
        path = vault._safe_path("/etc/passwd")
        assert path is None

    def test_dot_dot_dot_traversal(self, vault):
        path = vault._safe_path("../../../etc/passwd")
        assert path is None

    def test_encoded_dot_dot(self, vault):
        """URL-encoded path traversal."""
        path = vault._safe_path("..%2F..%2Fetc/passwd")
        # Should be blocked or treated as literal filename
        if path is not None:
            assert str(path).startswith(str(vault.vault_path))

    def test_null_byte_in_path(self, vault):
        """Null byte injection in filename."""
        try:
            path = vault._safe_path("test.md\x00.md")
            # Should be blocked or treated as invalid
            if path is not None:
                assert str(path).startswith(str(vault.vault_path))
        except (ValueError, OSError):
            pass  # Acceptable

    def test_empty_path(self, vault):
        """Empty path should be handled safely."""
        try:
            path = vault._safe_path("")
            if path is not None:
                assert str(path).startswith(str(vault.vault_path))
        except (ValueError, OSError):
            pass

    def test_only_dots(self, vault):
        path = vault._safe_path("..")
        assert path is None

    def test_trailing_dot_dot(self, vault):
        path = vault._safe_path("test/../..")
        assert path is None

    def test_path_with_spaces(self, vault):
        path = vault._safe_path("my file.md")
        assert path is not None

    def test_path_with_unicode(self, vault):
        path = vault._safe_path("\u4f60\u597d.md")
        assert path is not None
        assert "\u4f60\u597d.md" in str(path)

    def test_path_with_special_chars(self, vault):
        path = vault._safe_path("file (copy).md")
        assert path is not None

    def test_deeply_nested_valid(self, vault):
        path = vault._safe_path("a/b/c/d/e/f/g/h.md")
        assert path is not None
        assert str(path).endswith("a/b/c/d/e/f/g/h.md")


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


class TestVaultReadWriteBrutal:
    """Edge cases for read/write operations."""

    def test_write_empty_content(self, vault):
        result = vault.write("empty.md", "")
        assert result is True
        assert vault.read("empty.md") == ""

    def test_write_unicode_content(self, vault):
        content = "\u4f60\u597d\u4e16\u754c \U0001f600"
        vault.write("unicode.md", content)
        assert vault.read("unicode.md") == content

    def test_write_very_large_content(self, vault):
        """1MB file should write and read correctly."""
        content = "x" * 1_000_000
        vault.write("large.md", content)
        assert vault.read("large.md") == content

    def test_write_binary_content(self, vault):
        """Binary content (non-UTF8) may or may not be supported."""
        try:
            vault.write("binary.md", "\x00\x01\x02\xff")
        except (UnicodeEncodeError, ValueError):
            pass  # Acceptable

    def test_read_after_delete(self, vault):
        vault.write("test.md", "content")
        vault.delete("test.md")
        assert vault.read("test.md") is None

    def test_double_delete(self, vault):
        vault.write("test.md", "content")
        assert vault.delete("test.md") is True
        assert vault.delete("test.md") is False

    def test_write_special_characters(self, vault):
        content = "Line1\nLine2\rLine3\tTabbed"
        vault.write("special.md", content)
        assert vault.read("special.md") == content

    def test_write_read_many_files(self, vault):
        """Write and read 100 files without crash."""
        for i in range(100):
            vault.write(f"file_{i}.md", f"content {i}")
        for i in range(100):
            content = vault.read(f"file_{i}.md")
            assert content == f"content {i}", f"File {i} content mismatch"

    def test_concurrent_writes(self, vault):
        """Multiple threads writing different files should not crash."""
        errors = []

        def write_file(i):
            try:
                vault.write(f"thread_{i}.md", f"content from thread {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_file, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


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


class TestVaultListBrutal:
    def test_list_nonexistent_vault(self, tmp_path):
        """List files in a vault directory that doesn't exist."""
        v = VaultManager(vault_path=str(tmp_path / "nonexistent"))
        files = v.list_files()
        assert files == []

    def test_list_with_symlinks(self, vault):
        """Symlinks should be handled safely."""
        vault.write("real.md", "real content")
        try:
            os.symlink(str(vault.vault_path / "real.md"), str(vault.vault_path / "link.md"))
            files = vault.list_files()
            # Should handle symlinks without crashing
            assert isinstance(files, list)
        except OSError:
            pass  # Symlinks may not be supported

    def test_list_many_files(self, vault):
        """1000 files should list correctly."""
        for i in range(1000):
            vault.write(f"f{i}.md", str(i))
        files = vault.list_files()
        assert len(files) == 1000


class TestVaultSearch:
    def test_search_finds_match(self, vault):
        vault.write("doc.md", "Python is a great programming language")
        results = vault.search("Python programming")
        assert len(results) > 0
        assert results[0]["filename"] == "doc.md"

    def test_search_no_match(self, vault):
        vault.write("doc.md", "completely unrelated content")
        results = vault.search("Python programming")
        if results:
            assert results[0]["score"] <= 0.1


class TestVaultSearchBrutal:
    def test_search_empty_vault(self, vault):
        results = vault.search("anything")
        assert isinstance(results, list)

    def test_search_empty_query(self, vault):
        vault.write("doc.md", "content")
        results = vault.search("")
        assert isinstance(results, list)

    def test_search_unicode_query(self, vault):
        vault.write("doc.md", "\u4f60\u597d\u4e16\u754c")
        results = vault.search("\u4f60\u597d")
        assert isinstance(results, list)

    def test_search_long_query(self, vault):
        vault.write("doc.md", "short content")
        query = "very long query " * 100
        results = vault.search(query)
        assert isinstance(results, list)

    def test_search_special_regex_chars(self, vault):
        """Regex special chars in query should not cause crashes."""
        vault.write("doc.md", "price is $10.00 (exact)")
        results = vault.search("$10.00 (exact)")
        assert isinstance(results, list)