from abc import ABC, abstractmethod

class StorageDriver(ABC):
    @abstractmethod
    def save(self, path: str, content: bytes) -> str:
        """
        Saves a file with the given content at the specified path.
        Returns the saved file's path or URI.
        """
        pass

    @abstractmethod
    def get(self, path: str) -> bytes:
        """
        Retrieves the content of the file at the specified path.
        Raises FileNotFoundError if the file does not exist.
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> None:
        """
        Deletes the file at the specified path.
        Must be idempotent (deleting a nonexistent file should not raise an error).
        """
        pass


class MockStorageDriver(StorageDriver):
    def __init__(self):
        self.files = {}

    def save(self, path: str, content: bytes) -> str:
        self.files[path] = content
        return path

    def get(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(f"File not found: {path}")
        return self.files[path]

    def delete(self, path: str) -> None:
        if path in self.files:
            del self.files[path]
