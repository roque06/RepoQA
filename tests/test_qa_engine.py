import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Api_QA.qa_engine import (
    TESTRAIL_EXPORT_COLUMNS,
    analyze_document_structure,
    build_testrail_export_dataframe,
    classify_document_type,
    estimate_scenario_volume,
    parse_gemini_json_response,
    prepare_extended_export,
    prepare_testrail_export,
    validate_and_prepare_scenarios,
)
from Api_QA.utils_ingest import preserve_document_structure, segment_document_text


class TestQaEngine(unittest.TestCase):
    def test_classify_document_type_ui(self):
        text = "Historia de usuario web: el formulario de registro debe validar campos obligatorios y mostrar mensajes en pantalla."
        self.assertEqual(classify_document_type(text), "UI/Formulario")

    def test_classify_document_type_api(self):
        text = "API REST de usuarios. Endpoint POST /users valida token, payload JSON y responde HTTP 201."
        self.assertEqual(classify_document_type(text), "API")

    def test_classify_document_type_workflow(self):
        text = "Flujo de aprobación de solicitudes con estados, aprobación, rechazo y actualización visible del estado."
        self.assertEqual(classify_document_type(text), "Workflow/Proceso")

    def test_classify_document_type_financial(self):
        text = "Proceso financiero con cálculo de comisiones, redondeos, reversos y consistencia contable."
        self.assertEqual(classify_document_type(text), "Financiero/Contable")

    def test_analyze_document_structure_detects_blocks_and_is_not_finance_biased(self):
        text = """
        1. Registro web
        El sistema debe permitir registrar usuarios nuevos mediante formulario.

        2. Login web
        El sistema debe autenticar usuarios y bloquear credenciales inválidas.

        3. Reporte
        El usuario puede consultar reportes filtrados por fecha y exportarlos.
        """
        analysis = analyze_document_structure(text)
        self.assertEqual(analysis["document_type"], "Mixto")
        self.assertIn("registro", analysis["functional_blocks"])
        self.assertIn("login", analysis["functional_blocks"])
        self.assertIn("reporte", analysis["functional_blocks"])
        self.assertFalse(any("revers" in item.lower() for item in analysis["coverage_targets"]))

    def test_estimate_scenario_volume_scales_with_multiple_blocks(self):
        text = """
        Registro de usuario
        Login de usuario
        CRUD de clientes
        Flujo de aprobación de solicitudes
        Reporte exportable
        """
        analysis = analyze_document_structure(text)
        minimum, target = estimate_scenario_volume(text, analysis)
        self.assertGreaterEqual(target, 12)
        self.assertGreaterEqual(minimum, 6)
        self.assertGreater(target, minimum)

    def test_analyze_document_structure_detects_crud_simple_as_functional_scope(self):
        text = """
        Mantenimiento de clientes
        Crear cliente
        Editar cliente
        Eliminar cliente
        Consultar cliente
        """
        analysis = analyze_document_structure(text)
        self.assertIn("consulta", analysis["functional_blocks"])
        self.assertTrue(any(block in analysis["functional_blocks"] for block in ["registro", "mantenimiento"]))

    def test_parse_and_validate_json_response_enhances_expected_results(self):
        analysis = analyze_document_structure("Formulario de registro web con validaciones y persistencia.")
        payload = parse_gemini_json_response(
            '''```json
            {
              "document_type": "UI/Formulario",
              "functional_summary": {},
              "test_scenarios": [
                {
                  "title": "Registro de usuario",
                  "preconditions": "1. Usuario en la pantalla de registro\n2. Servicio disponible",
                  "steps": "1. Completar campos obligatorios\n2. Ingresar datos válidos\n3. Enviar el formulario\n4. Revisar la respuesta del sistema",
                  "expected_result": "Correcto",
                  "type": "Funcional",
                  "priority": "Alta",
                  "source_basis": "explicito",
                  "assumption": ""
                }
              ]
            }
            ```'''
        )
        df, metadata = validate_and_prepare_scenarios(payload, analysis=analysis)
        self.assertEqual(len(df), 1)
        self.assertIn("persiste", df.iloc[0]["Expected Result"].lower())
        self.assertEqual(metadata["accepted"], 1)

    def test_prepare_testrail_export_excludes_internal_columns_and_orders_output(self):
        df = pd.DataFrame(
            [
                {
                    "✓": True,
                    "Priority": "Alta",
                    "Title": "Login exitoso",
                    "source_basis": "explicito",
                    "Expected Result": "El sistema autentica al usuario y muestra el inicio",
                    "assumption": "",
                    "Type": "Funcional",
                    "Estado": "Listo",
                    "Steps": "1. Ingresar credenciales\n2. Enviar",
                    "Preconditions": "1. Usuario registrado",
                }
            ]
        )
        export_df = build_testrail_export_dataframe(df)
        self.assertEqual(list(export_df.columns), TESTRAIL_EXPORT_COLUMNS)
        self.assertNotIn("✓", export_df.columns)
        self.assertNotIn("source_basis", export_df.columns)
        self.assertNotIn("assumption", export_df.columns)
        self.assertNotIn("quality_notes", export_df.columns)

    def test_build_testrail_export_dataframe_enforces_exact_7_columns_contract(self):
        df = pd.DataFrame([{"Title": "Caso", "Expected Result": "Texto", "Estado": "Pendiente", "extra": "x"}])
        export_df = build_testrail_export_dataframe(df)
        self.assertEqual(export_df.shape[1], 7)
        self.assertEqual(list(export_df.columns), TESTRAIL_EXPORT_COLUMNS)
        self.assertEqual(export_df.iloc[0]["Preconditions"], "")
        self.assertEqual(export_df.iloc[0]["Steps"], "")

    def test_prepare_extended_export_keeps_traceability_outside_default_mode(self):
        df = pd.DataFrame(
            [{
                "Title": "API válida",
                "Preconditions": "1. Token válido",
                "Steps": "1. Enviar request\n2. Revisar response",
                "Expected Result": "El sistema responde con código HTTP esperado",
                "Type": "Integracion",
                "Priority": "Alta",
                "Estado": "Pendiente",
                "source_basis": "inferido",
                "assumption": "Existe endpoint activo",
            }]
        )
        export_df = prepare_extended_export(df)
        self.assertIn("source_basis", export_df.columns)
        self.assertIn("assumption", export_df.columns)
        self.assertEqual(export_df.iloc[0]["source_basis"], "inferido")

    def test_validate_pipeline_does_not_truncate_expected_result(self):
        analysis = analyze_document_structure("Workflow de aprobación de solicitudes.")
        long_expected = (
            "El sistema actualiza el estado de la solicitud a Aprobada, refleja el cambio en la bandeja del aprobador, "
            "muestra un mensaje de confirmación visible y persiste la transición para consulta posterior."
        )
        payload = {
            "test_scenarios": [
                {
                    "title": "Aprobación de solicitud",
                    "preconditions": "1. Solicitud en estado pendiente\\n2. Aprobador con permisos",
                    "steps": "1. Abrir solicitud\\n2. Revisar datos\\n3. Aprobar\\n4. Confirmar operación",
                    "expected_result": long_expected,
                    "type": "Funcional",
                    "priority": "Alta",
                    "source_basis": "explicito",
                    "assumption": "",
                }
            ]
        }
        df, _ = validate_and_prepare_scenarios(payload, analysis=analysis)
        self.assertEqual(df.iloc[0]["Expected Result"], long_expected)

    def test_ingest_helpers_preserve_structure_and_segment(self):
        text = "# Encabezado\nCampo,Valor\nMonto,100\n\n" + ("Detalle operativo. " * 1200)
        structured = preserve_document_structure(text)
        self.assertIn("[linea_seccion] # Encabezado", structured)
        segments = segment_document_text(structured, max_chars=1200, overlap=100)
        self.assertGreater(len(segments), 1)


if __name__ == "__main__":
    unittest.main()
