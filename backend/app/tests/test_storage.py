import pytest
from app.services.storage import StorageDriver, MockStorageDriver

class TestStorageDriverAbstract:
    """Verify that StorageDriver is an abstract base class."""

    def test_cannot_instantiate_abstract_class(self):
        with pytest.raises(TypeError):
            StorageDriver()  # type: ignore


class TestMockStorageDriver:
    """Verify MockStorageDriver functionality."""

    def test_save_and_get_roundtrip(self):
        driver = MockStorageDriver()
        path = "test/path/file.txt"
        content = b"Hello, World!"
        
        saved_path = driver.save(path, content)
        assert saved_path == path
        
        retrieved_content = driver.get(path)
        assert retrieved_content == content

    def test_get_nonexistent_file_raises_error(self):
        driver = MockStorageDriver()
        with pytest.raises(FileNotFoundError):
            driver.get("nonexistent.txt")

    def test_delete_existing_file(self):
        driver = MockStorageDriver()
        path = "test/delete.txt"
        content = b"delete me"
        
        driver.save(path, content)
        assert driver.get(path) == content
        
        driver.delete(path)
        with pytest.raises(FileNotFoundError):
            driver.get(path)

    def test_delete_nonexistent_file_is_idempotent(self):
        driver = MockStorageDriver()
        # Deleting a nonexistent file should not raise any error
        try:
            driver.delete("nonexistent.txt")
        except Exception as e:
            pytest.fail(f"delete() raised an unexpected exception: {e}")
