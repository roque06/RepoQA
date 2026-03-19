import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


def load_utils_testrail():
    module_name = "test_utils_testrail_module"
    module_path = Path(__file__).resolve().parents[1] / "Api_QA" / "utils_testrail.py"

    fake_streamlit = types.SimpleNamespace(
        secrets={
            "testrail_url": "https://testrail.example.com",
            "testrail_email": "qa@example.com",
            "testrail_api_key": "secret",
        },
        error=lambda *args, **kwargs: None,
    )

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    sys.modules.pop(module_name, None)
    with patch.dict(sys.modules, {"streamlit": fake_streamlit}):
        spec.loader.exec_module(module)
    return module


class TestUtilsTestRail(unittest.TestCase):
    def test_refs_se_envia_vacio_cuando_no_existe_columna(self):
        module = load_utils_testrail()
        dataframe = pd.DataFrame(
            [
                {
                    "Title": "Validar login",
                    "Preconditions": "Usuario habilitado",
                    "Steps": "Ingresar credenciales válidas",
                    "Expected Result": "El usuario accede al sistema",
                    "Type": "Funcional",
                    "Priority": "Alta",
                }
            ]
        )

        with patch.object(module.requests, "post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.text = ""

            resultado = module.enviar_a_testrail(321, dataframe)

        self.assertTrue(resultado["exito"])
        enviado = mock_post.call_args.kwargs["json"]
        self.assertIn("refs", enviado)
        self.assertEqual(enviado["refs"], "")

    def test_refs_toma_valor_desde_columna_opcional(self):
        module = load_utils_testrail()
        dataframe = pd.DataFrame(
            [
                {
                    "Title": "Validar checkout",
                    "Preconditions": "Carrito con productos",
                    "Steps": "Confirmar pago",
                    "Expected Result": "Se genera la orden",
                    "Type": "Integración",
                    "Priority": "Media",
                    "References": "JIRA-123,REQ-88",
                }
            ]
        )

        with patch.object(module.requests, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.text = ""

            module.enviar_a_testrail(654, dataframe)

        enviado = mock_post.call_args.kwargs["json"]
        self.assertEqual(enviado["refs"], "JIRA-123,REQ-88")


if __name__ == "__main__":
    unittest.main()
