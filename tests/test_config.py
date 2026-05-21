import os
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from config import Settings, get_settings

CONFIG_ENV_VARS = [
    "PAPRA_BASE_URL",
    "PAPRA_API_TOKEN",
    "PAPRA_WEBHOOK_SECRET",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "LOG_LEVEL",
    "PAPRA_AI_TAG_COLOR",
    "PAPRA_AI_ENV_FILE",
]


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {key: os.environ.get(key) for key in CONFIG_ENV_VARS}

        for key in CONFIG_ENV_VARS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key in CONFIG_ENV_VARS:
            os.environ.pop(key, None)

        for key, value in self.original_env.items():
            if value is not None:
                os.environ[key] = value

    def test_settings_loads_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "PAPRA_BASE_URL=http://papra.local:1221",
                        "PAPRA_API_TOKEN=from-file",
                        "PAPRA_WEBHOOK_SECRET=from-file",
                        "OLLAMA_BASE_URL=http://ollama:11434",
                        "OLLAMA_MODEL=llava:latest",
                    ]
                )
            )

            settings = Settings(_env_file=env_path)

            self.assertEqual(settings.papra_base_url, "http://papra.local:1221")
            self.assertEqual(settings.ollama_base_url, "http://ollama:11434")
            self.assertEqual(settings.ollama_model, "llava:latest")

    def test_environment_overrides_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "PAPRA_API_TOKEN=from-file\n"
                "PAPRA_WEBHOOK_SECRET=from-file\n"
                "OLLAMA_MODEL=from-file\n"
            )
            os.environ["OLLAMA_MODEL"] = "from-env"

            settings = Settings(_env_file=env_path)

            self.assertEqual(settings.ollama_model, "from-env")

    def test_get_settings_uses_custom_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "local.env"
            env_path.write_text(
                "PAPRA_API_TOKEN=from-custom-file\nOLLAMA_MODEL=from-custom-file\n"
                "PAPRA_WEBHOOK_SECRET=from-custom-file\n"
            )
            os.environ["PAPRA_AI_ENV_FILE"] = str(env_path)

            settings = get_settings()

            self.assertEqual(settings.ollama_model, "from-custom-file")

    def test_tag_color_is_validated(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                papra_api_token="token",
                papra_webhook_secret="secret",
                papra_ai_tag_color="blue",
            )

    def test_papra_api_token_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(papra_webhook_secret="secret", _env_file=None)

    def test_papra_webhook_secret_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(papra_api_token="token", _env_file=None)


if __name__ == "__main__":
    unittest.main()
