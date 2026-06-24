import os
import io
from abc import ABC, abstractmethod
from PIL import Image, ImageOps
import pillow_heif

# Register HEIF opener to support HEIC files
pillow_heif.register_heif_opener()


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


class LocalStorageDriver(StorageDriver):
    def __init__(self, base_dir: str = "/app"):
        self.base_dir = base_dir

    def _get_absolute_path(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.base_dir, path))

    def save(self, path: str, content: bytes) -> str:
        abs_path = self._get_absolute_path(path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "wb") as f:
            f.write(content)
        return path

    def get(self, path: str) -> bytes:
        abs_path = self._get_absolute_path(path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(abs_path, "rb") as f:
            return f.read()

    def delete(self, path: str) -> None:
        abs_path = self._get_absolute_path(path)
        if os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except Exception:
                pass


class GCSStorageDriver(StorageDriver):
    def __init__(self, bucket_name: str = None):
        self._bucket_name = bucket_name or os.getenv("GCS_BUCKET_NAME")
        self._client = None
        self._bucket = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import storage
            self._client = storage.Client()
        return self._client

    @property
    def bucket(self):
        if self._bucket is None:
            if not self._bucket_name:
                raise ValueError("GCS_BUCKET_NAME environment variable is not set")
            self._bucket = self.client.bucket(self._bucket_name)
        return self._bucket

    def save(self, path: str, content: bytes) -> str:
        # Strip leading slash if any for GCS blob names
        blob_name = path.lstrip("/")
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content)
        return path

    def get(self, path: str) -> bytes:
        blob_name = path.lstrip("/")
        blob = self.bucket.blob(blob_name)
        if not blob.exists():
            raise FileNotFoundError(f"File not found in GCS bucket: {path}")
        return blob.download_as_bytes()

    def delete(self, path: str) -> None:
        blob_name = path.lstrip("/")
        blob = self.bucket.blob(blob_name)
        if blob.exists():
            try:
                blob.delete()
            except Exception:
                pass


class S3StorageDriver(StorageDriver):
    def __init__(
        self,
        bucket_name: str = None,
        endpoint_url: str = None,
        access_key: str = None,
        secret_key: str = None,
        region_name: str = None,
    ):
        self._bucket_name = bucket_name or os.getenv("S3_BUCKET_NAME") or os.getenv("AWS_BUCKET_NAME")
        self._endpoint_url = endpoint_url or os.getenv("S3_ENDPOINT_URL")
        self._access_key = access_key or os.getenv("AWS_ACCESS_KEY_ID")
        self._secret_key = secret_key or os.getenv("AWS_SECRET_ACCESS_KEY")
        self._region_name = region_name or os.getenv("AWS_REGION_NAME")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            kwargs = {}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key
            if self._region_name:
                kwargs["region_name"] = self._region_name
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def save(self, path: str, content: bytes) -> str:
        if not self._bucket_name:
            raise ValueError("S3_BUCKET_NAME or AWS_BUCKET_NAME is not set")
        object_name = path.lstrip("/")
        self.client.put_object(
            Bucket=self._bucket_name,
            Key=object_name,
            Body=content
        )
        return path

    def get(self, path: str) -> bytes:
        if not self._bucket_name:
            raise ValueError("S3_BUCKET_NAME or AWS_BUCKET_NAME is not set")
        object_name = path.lstrip("/")
        try:
            response = self.client.get_object(
                Bucket=self._bucket_name,
                Key=object_name
            )
            return response["Body"].read()
        except Exception as e:
            # Check for NoSuchKey in standard boto3/botocore ClientError response
            if hasattr(e, "response") and e.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise FileNotFoundError(f"File not found in S3 bucket: {path}")
            raise

    def delete(self, path: str) -> None:
        if not self._bucket_name:
            raise ValueError("S3_BUCKET_NAME or AWS_BUCKET_NAME is not set")
        object_name = path.lstrip("/")
        try:
            self.client.delete_object(
                Bucket=self._bucket_name,
                Key=object_name
            )
        except Exception:
            pass


def preprocess_image(content: bytes) -> bytes:
    """
    Decodes an image from bytes (PNG, JPG, HEIC, WebP, etc.),
    scales it down to fit within a 1200x1200px bounding box while preserving aspect ratio,
    and compresses it to WebP format with exactly 80% quality.
    """
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image)
    except Exception as e:
        raise ValueError(f"Invalid image format or corrupt file: {e}")

    # Convert to RGB mode if not already (handles alpha channels/transparency by converting to RGB)
    if image.mode != "RGB":
        image = image.convert("RGB")

    # Aspect-ratio-preserving downscaling to fit inside 1200x1200px
    image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

    # Compress to WebP with exactly 80% quality
    output = io.BytesIO()
    image.save(output, format="WEBP", quality=80)
    return output.getvalue()


def get_storage_driver() -> StorageDriver:
    driver_type = os.getenv("STORAGE_DRIVER", "LOCAL").upper()
    if driver_type == "GCS":
        return GCSStorageDriver()
    elif driver_type == "S3":
        return S3StorageDriver()
    elif driver_type == "MOCK":
        return MockStorageDriver()
    else:
        return LocalStorageDriver()

