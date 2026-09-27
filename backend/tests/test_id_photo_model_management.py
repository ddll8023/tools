"""验证证件照模型下载状态、资源写入和删除边界。"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from toolbox_backend.core.errors import ServiceException
from toolbox_backend.modules.id_photo import model_management


class _FakeResponse:
    def __init__(self, body: bytes, content_length: int | None = None) -> None:
        self._body = io.BytesIO(body)
        self.headers = {
            "Content-Length": str(content_length if content_length is not None else len(body))
        }

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self._body.close()


class IdPhotoModelManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.model_dir = Path(self.temp_dir.name) / "resources" / "id_photo"
        self.model_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_managed_missing_model_is_downloadable(self) -> None:
        missing_reason = "缺少人像抠图模型，当前资源目录需包含：hivision_modnet.onnx"
        with (
            patch.object(model_management, "get_model_status", return_value=(False, missing_reason)),
            patch.object(model_management, "_model_directory", return_value=str(self.model_dir)),
            patch.object(model_management, "_managed_model_directory", return_value=str(self.model_dir)),
            patch.object(model_management, "_find_matte_model", return_value=None),
            patch.object(model_management, "_mtcnn_weight_paths", return_value={"pnet": str(self.model_dir / "pnet.onnx")}),
            patch.object(model_management, "_photo_delete_state", return_value=(False, "没有可删除的用户数据模型")),
            patch.object(model_management, "_ACTIVE_DOWNLOAD", None),
            patch.object(model_management, "_LAST_DOWNLOAD", None),
        ):
            status = model_management.get_model_management_status()

        self.assertEqual(status["status"], "incomplete")
        self.assertTrue(status["can_download"])

    def test_non_managed_model_path_is_not_downloadable(self) -> None:
        missing_reason = "缺少人像抠图模型，当前资源目录需包含：hivision_modnet.onnx"
        with (
            patch.object(model_management, "get_model_status", return_value=(False, missing_reason)),
            patch.object(model_management, "_model_directory", return_value=str(self.model_dir)),
            patch.object(model_management, "_managed_model_directory", return_value=None),
            patch.object(model_management, "_find_matte_model", return_value=None),
            patch.object(model_management, "_mtcnn_weight_paths", return_value={"pnet": str(self.model_dir / "pnet.onnx")}),
            patch.object(model_management, "_photo_delete_state", return_value=(False, "模型位于应用内置或自定义目录，不能从设置中删除")),
            patch.object(model_management, "_ACTIVE_DOWNLOAD", None),
            patch.object(model_management, "_LAST_DOWNLOAD", None),
            patch.object(model_management.settings, "ID_PHOTO_MODEL_PATH", ""),
            patch.object(model_management.settings, "ROOT_PATH", self.temp_dir.name),
        ):
            status = model_management.get_model_management_status()

        self.assertFalse(status["can_download"])

    def test_modnet_download_installs_complete_file_atomically(self) -> None:
        job = model_management._IdPhotoDownloadJob(job_id="download-test")
        body = b"model-data"
        response = _FakeResponse(body)
        with (
            patch.object(model_management, "_ACTIVE_DOWNLOAD", job),
            patch("toolbox_backend.modules.id_photo.model_management.urllib.request.urlopen", return_value=response),
        ):
            model_management._download_modnet_model(job.job_id, self.model_dir)

        target = self.model_dir / model_management.MATTE_MODEL_CANDIDATES[0]
        self.assertEqual(target.read_bytes(), body)
        self.assertFalse(target.with_name(f".{target.name}.{job.job_id}.download").exists())

    def test_incomplete_modnet_download_is_not_installed(self) -> None:
        job = model_management._IdPhotoDownloadJob(job_id="download-test")
        response = _FakeResponse(b"partial", content_length=20)
        with (
            patch.object(model_management, "_ACTIVE_DOWNLOAD", job),
            patch("toolbox_backend.modules.id_photo.model_management.urllib.request.urlopen", return_value=response),
            self.assertRaises(OSError),
        ):
            model_management._download_modnet_model(job.job_id, self.model_dir)

        target = self.model_dir / model_management.MATTE_MODEL_CANDIDATES[0]
        self.assertFalse(target.exists())

    def test_mtcnn_weights_are_copied_from_installed_package(self) -> None:
        package_root = Path(self.temp_dir.name) / "mtcnnruntime"
        weights_dir = package_root / "weights"
        weights_dir.mkdir(parents=True)
        for filename in model_management.MTCNN_WEIGHT_NAMES:
            (weights_dir / filename).write_bytes(filename.encode("utf-8"))

        job = model_management._IdPhotoDownloadJob(job_id="download-test")
        runtime_module = SimpleNamespace(__file__=str(package_root / "__init__.py"))
        with (
            patch.object(model_management, "_ACTIVE_DOWNLOAD", job),
            patch.dict(sys.modules, {"mtcnnruntime": runtime_module}),
        ):
            model_management._copy_mtcnn_weights(job.job_id, self.model_dir)

        for filename in model_management.MTCNN_WEIGHT_NAMES:
            target = self.model_dir / "mtcnn" / filename
            self.assertEqual(target.read_bytes(), filename.encode("utf-8"))

    def test_cleanup_removes_only_known_stale_download_parts(self) -> None:
        stale_modnet = self.model_dir / f".{model_management.MATTE_MODEL_CANDIDATES[0]}.old.download"
        stale_mtcnn_dir = self.model_dir / "mtcnn"
        stale_mtcnn_dir.mkdir()
        stale_mtcnn = stale_mtcnn_dir / f".{model_management.MTCNN_WEIGHT_NAMES[0]}.old.download"
        unrelated = self.model_dir / "notes.download"
        for path in (stale_modnet, stale_mtcnn, unrelated):
            path.write_text("partial", encoding="utf-8")

        model_management._cleanup_stale_download_parts(self.model_dir)

        self.assertFalse(stale_modnet.exists())
        self.assertFalse(stale_mtcnn.exists())
        self.assertTrue(unrelated.exists())

    def test_model_cannot_be_deleted_during_download(self) -> None:
        job = model_management._IdPhotoDownloadJob(job_id="download-test")
        with (
            patch.object(model_management, "_managed_model_directory", return_value=str(self.model_dir)),
            patch.object(model_management, "_ACTIVE_DOWNLOAD", job),
            self.assertRaises(ServiceException),
        ):
            model_management.delete_id_photo_model()


if __name__ == "__main__":
    unittest.main()
