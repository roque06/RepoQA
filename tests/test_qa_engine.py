import unittest
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Api_QA.qa_engine import (
    analyze_document_structure,
    classify_document_type,
    parse_gemini_json_response,
    validate_and_prepare_scenarios,
)
from Api_QA.utils_ingest import preserve_document_structure, segment_document_text


class TestQaEngine(unittest.TestCase):
    def test_classify_document_type_api(self):
        text = "API de transferencias. Endpoint POST /payments valida token, request JSON y response HTTP 201."
        self.assertEqual(classify_document_type(text), "API")

    def test_analyze_document_structure_extracts_core_signals(self):
        text = """
        Módulo: Pagos internacionales
        Actor: Usuario y Administrador
        El sistema debe validar monto obligatorio y formato de moneda.
        La integración con servicio externo puede fallar por timeout.
        El cálculo del total debe incluir comisión.
        """
        analysis = analyze_document_structure(text)
        self.assertEqual(analysis["document_type"], "Mixto")
        self.assertTrue(any("validar monto obligatorio" in item.lower() for item in analysis["validations"]))
        self.assertTrue(any("timeout" in item.lower() for item in analysis["risks"]))
        self.assertTrue(any("comisión" in item.lower() or "comision" in item.lower() for item in analysis["calculations"]))

    def test_parse_and_validate_json_response_filters_duplicates_and_invalid_cases(self):
        payload = parse_gemini_json_response(
            '''```json
            {
              "document_type": "UI/Formulario",
              "functional_summary": {},
              "test_scenarios": [
                {
                  "title": "Registro de solicitud",
                  "preconditions": "1. Usuario autenticado\n2. Formulario disponible",
                  "steps": "1. Ingresar datos válidos\n2. Confirmar la acción\n3. Enviar la solicitud\n4. Consultar el resultado",
                  "expected_result": "El sistema registra la solicitud y muestra confirmación visible",
                  "type": "Funcional",
                  "priority": "Alta",
                  "source_basis": "explicito",
                  "assumption": ""
                },
                {
                  "title": "Registro de solicitud",
                  "preconditions": "1. Usuario autenticado\n2. Formulario disponible",
                  "steps": "1. Ingresar datos válidos\n2. Confirmar la acción\n3. Enviar la solicitud\n4. Consultar el resultado",
                  "expected_result": "El sistema registra la solicitud y muestra confirmación visible",
                  "type": "Funcional",
                  "priority": "Alta",
                  "source_basis": "explicito",
                  "assumption": ""
                },
                {
                  "title": "Consulta y aprobación",
                  "preconditions": "1. Usuario autenticado",
                  "steps": "1. Abrir pantalla\n2. Consultar",
                  "expected_result": "Correcto",
                  "type": "Funcional",
                  "priority": "Media",
                  "source_basis": "inferido",
                  "assumption": "Existe un flujo de aprobación"
                }
              ]
            }
            ```'''
        )
        df, metadata = validate_and_prepare_scenarios(payload)
        self.assertIsInstance(df, pd.DataFrame)
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["source_basis"], "explicito")
        self.assertEqual(len(metadata["dropped"]), 2)

    def test_ingest_helpers_preserve_structure_and_segment(self):
        text = "# Encabezado\nCampo,Valor\nMonto,100\n\n" + ("Detalle operativo. " * 1200)
        structured = preserve_document_structure(text)
        self.assertIn("[linea_seccion] # Encabezado", structured)
        segments = segment_document_text(structured, max_chars=1200, overlap=100)
        self.assertGreater(len(segments), 1)


if __name__ == "__main__":
    unittest.main()
