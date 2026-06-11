import pytest
import io
import os
from unittest.mock import MagicMock, patch
from PIL import Image
from app.services.storage import (
    StorageDriver,
    MockStorageDriver,
    LocalStorageDriver,
    GCSStorageDriver,
    preprocess_image,
    get_storage_driver,
)


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


class TestLocalStorageDriver:
    """Verify LocalStorageDriver functionality."""

    def test_save_and_get_roundtrip(self, tmp_path):
        driver = LocalStorageDriver(base_dir=str(tmp_path))
        path = "uploads/test.txt"
        content = b"Local file storage test content"

        saved_path = driver.save(path, content)
        assert saved_path == path

        # Check file exists on disk at expected location
        expected_file = tmp_path / "uploads" / "test.txt"
        assert expected_file.exists()
        assert expected_file.read_bytes() == content

        # Retrieve content
        retrieved_content = driver.get(path)
        assert retrieved_content == content

    def test_get_nonexistent_file_raises_error(self, tmp_path):
        driver = LocalStorageDriver(base_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            driver.get("nonexistent.txt")

    def test_delete_existing_file(self, tmp_path):
        driver = LocalStorageDriver(base_dir=str(tmp_path))
        path = "uploads/delete_me.txt"
        content = b"delete this"

        driver.save(path, content)
        expected_file = tmp_path / "uploads" / "delete_me.txt"
        assert expected_file.exists()

        driver.delete(path)
        assert not expected_file.exists()

    def test_delete_nonexistent_file_is_idempotent(self, tmp_path):
        driver = LocalStorageDriver(base_dir=str(tmp_path))
        try:
            driver.delete("nonexistent.txt")
        except Exception as e:
            pytest.fail(f"LocalStorageDriver.delete() raised an unexpected exception: {e}")


class TestGCSStorageDriver:
    """Verify GCSStorageDriver functionality using mocks."""

    @patch("google.cloud.storage.Client")
    def test_save_and_get_roundtrip(self, mock_client_class):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob

        driver = GCSStorageDriver(bucket_name="test-bucket")

        # Test save
        path = "uploads/file.webp"
        content = b"fake-webp-data"
        saved_path = driver.save(path, content)

        assert saved_path == path
        mock_client.bucket.assert_called_with("test-bucket")
        mock_bucket.blob.assert_called_with("uploads/file.webp")
        mock_blob.upload_from_string.assert_called_with(content)

        # Test get
        mock_blob.exists.return_value = True
        mock_blob.download_as_bytes.return_value = content
        retrieved = driver.get(path)
        assert retrieved == content

    @patch("google.cloud.storage.Client")
    def test_get_nonexistent_file_raises_error(self, mock_client_class):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = False

        driver = GCSStorageDriver(bucket_name="test-bucket")
        with pytest.raises(FileNotFoundError):
            driver.get("nonexistent.txt")

    @patch("google.cloud.storage.Client")
    def test_delete_existing_file(self, mock_client_class):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = True

        driver = GCSStorageDriver(bucket_name="test-bucket")
        driver.delete("uploads/file.webp")
        mock_blob.delete.assert_called_once()

    @patch("google.cloud.storage.Client")
    def test_delete_nonexistent_file_is_idempotent(self, mock_client_class):
        mock_client = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()

        mock_client_class.return_value = mock_client
        mock_client.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_blob.exists.return_value = False

        driver = GCSStorageDriver(bucket_name="test-bucket")
        try:
            driver.delete("nonexistent.txt")
        except Exception as e:
            pytest.fail(f"GCSStorageDriver.delete() raised an unexpected exception: {e}")


class TestImagePreprocessingPipeline:
    """Verify image preprocessing rules: format conversion, dimension bounds, aspect-ratio preservation, compression."""

    def test_preprocess_large_png_scales_down_and_converts_to_webp(self):
        # Create a 2000x1000 PNG image in memory (2:1 aspect ratio)
        img = Image.new("RGBA", (2000, 1000), color="red")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")
        png_data = img_bytes.getvalue()

        # Process the image
        webp_data = preprocess_image(png_data)

        # Verify output WebP format, scaling, and aspect-ratio preservation
        out_img = Image.open(io.BytesIO(webp_data))
        assert out_img.format == "WEBP"
        # Bounding box is 1200x1200px. With 2000x1000 (2:1), it scales to 1200x600px.
        assert out_img.size == (1200, 600)

    def test_preprocess_small_jpeg_does_not_scale_up_but_converts_to_webp(self):
        # Create a 500x300 JPEG image in memory
        img = Image.new("RGB", (500, 300), color="blue")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="JPEG")
        jpeg_data = img_bytes.getvalue()

        # Process the image
        webp_data = preprocess_image(jpeg_data)

        # Verify output WebP format and dimensions (should not scale up)
        out_img = Image.open(io.BytesIO(webp_data))
        assert out_img.format == "WEBP"
        assert out_img.size == (500, 300)

    def test_preprocess_heic_scales_down_and_converts_to_webp(self):
        # Create a dummy image and save it as HEIF (to simulate HEIC upload via pillow-heif)
        img = Image.new("RGB", (1600, 1200), color="green")
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="HEIF")
        heic_data = img_bytes.getvalue()

        # Process the image
        webp_data = preprocess_image(heic_data)

        # Verify output format and dimensions (1600x1200 -> 1200x900)
        out_img = Image.open(io.BytesIO(webp_data))
        assert out_img.format == "WEBP"
        assert out_img.size == (1200, 900)

    def test_preprocess_invalid_image_raises_value_error(self):
        with pytest.raises(ValueError):
            preprocess_image(b"invalid corrupt raw data")


class TestGetStorageDriver:
    """Verify get_storage_driver correctly instantiates drivers based on environment variables."""

    @patch.dict(os.environ, {"STORAGE_DRIVER": "LOCAL"})
    def test_get_storage_driver_local(self):
        driver = get_storage_driver()
        assert isinstance(driver, LocalStorageDriver)

    @patch.dict(os.environ, {"STORAGE_DRIVER": "GCS", "GCS_BUCKET_NAME": "my-bucket"})
    @patch("google.cloud.storage.Client")
    def test_get_storage_driver_gcs(self, mock_client_class):
        driver = get_storage_driver()
        assert isinstance(driver, GCSStorageDriver)
        assert driver._bucket_name == "my-bucket"

    @patch.dict(os.environ, {"STORAGE_DRIVER": "MOCK"})
    def test_get_storage_driver_mock(self):
        driver = get_storage_driver()
        assert isinstance(driver, MockStorageDriver)

