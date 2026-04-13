import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def load_utils_gemini():
    module_name = "test_utils_gemini_module"
    module_path = Path(__file__).resolve().parents[1] / "Api_QA" / "utils_gemini.py"

    fake_streamlit = types.SimpleNamespace(secrets={}, warning=lambda *args, **kwargs: None)

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, {"streamlit": fake_streamlit, "qa_engine": types.SimpleNamespace(summarize_analysis_for_prompt=lambda *_: "") }):
        spec.loader.exec_module(module)
    return module


class TestUtilsGemini(unittest.TestCase):
    def test_construye_mensaje_amigable_para_503_high_demand(self):
        module = load_utils_gemini()
        raw = "Error HTTP al invocar Gemini (503): This model is currently experiencing high demand."
        msg = module.construir_mensaje_error_gemini(raw)
        self.assertIn("temporalmente saturado", msg)
        self.assertIn("503", msg)

    def test_conserva_texto_original_para_errores_desconocidos(self):
        module = load_utils_gemini()
        raw = "Error HTTP al invocar Gemini (400): Bad request"
        msg = module.construir_mensaje_error_gemini(raw)
        self.assertEqual(msg, raw)


if __name__ == "__main__":
    unittest.main()
