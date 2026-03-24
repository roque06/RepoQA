from __future__ import annotations

import json
import math
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

if __package__:
    from .utils_csv import limpiar_texto_qa, normalizar_preconditions, normalizar_steps
else:
    from utils_csv import limpiar_texto_qa, normalizar_preconditions, normalizar_steps

CSV_COLUMNS = ["Title", "Preconditions", "Steps", "Expected Result", "Type", "Priority"]
TESTRAIL_EXPORT_COLUMNS = CSV_COLUMNS + ["Estado"]
INTERNAL_ONLY_COLUMNS = ["source_basis", "assumption", "quality_notes", "score"]
_ALLOWED_TYPES = {"Funcional", "Validacion", "Integracion", "Seguridad", "Usabilidad"}
_ALLOWED_PRIORITIES = {"Alta", "Media", "Baja"}
_TYPE_ALIASES = {
    "ui/formulario": "UI/Formulario",
    "api": "API",
    "workflow/proceso": "Workflow/Proceso",
    "integración": "Integración",
    "integracion": "Integración",
    "reporte/consulta": "Reporte/Consulta",
    "financiero/contable": "Financiero/Contable",
    "mixto": "Mixto",
}
_BLOCK_KEYWORDS = {
    "registro": [r"\bregistro\b", r"\balta\b", r"\bcrear\b", r"\bnuevo\b"],
    "login": [r"\blogin\b", r"\biniciar sesi[oó]n\b", r"\bautentic"],
    "compra": [r"\bcompra\b", r"\bcheckout\b", r"\bpedido\b"],
    "consulta": [r"\bconsulta\b", r"\bconsultar\b", r"\bb[uú]squeda\b", r"\bdetalle\b"],
    "aprobación": [r"\baprobaci[oó]n\b", r"\baprobar\b"],
    "rechazo": [r"\brechazo\b", r"\brechazar\b"],
    "notificación": [r"\bnotific", r"\bcorreo\b", r"\bemail\b", r"\balerta\b"],
    "reporte": [r"\breporte\b", r"\bdashboard\b", r"\bfiltro\b", r"\bexporta"],
    "integración": [r"\bintegraci[oó]n\b", r"\bservicio externo\b", r"\bwebhook\b", r"\bcola\b"],
    "mantenimiento": [r"\bmantenimiento\b", r"\bcat[aá]logo\b", r"\bconfiguraci[oó]n\b"],
    "cálculo": [r"\bc[aá]lculo\b", r"\btasa\b", r"\bcomisi[oó]n\b", r"\bredonde"],
    "liquidación": [r"\bliquidaci[oó]n\b", r"\bcierre\b"],
}


def _split_lines(texto: str) -> List[str]:
    if not isinstance(texto, str):
        return []
    return [line.strip() for line in re.split(r"\r?\n+", texto) if line.strip()]


def _dedupe_keep_order(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        normalized = re.sub(r"\s+", " ", str(value).strip().lower())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(str(value).strip())
    return result


def _classify_scores(texto: str) -> Dict[str, int]:
    txt = (texto or "").lower()
    buckets = {
        "UI/Formulario": [r"\bformulario\b", r"\bpantalla\b", r"\bbot[oó]n\b", r"\bcampo\b", r"\bui\b", r"\bfrontend\b", r"\bweb\b", r"\bmodal\b"],
        "API": [r"\bendpoint\b", r"\bhttp\b", r"\brequest\b", r"\bresponse\b", r"\bjson\b", r"\bapi\b", r"\btoken\b", r"\bauth\b", r"\bschema\b"],
        "Workflow/Proceso": [r"\bproceso\b", r"\bflujo\b", r"\bestado\b", r"\btransici[oó]n\b", r"\baprobaci[oó]n\b", r"\brechazo\b", r"\bworkflow\b"],
        "Integración": [r"\bintegraci[oó]n\b", r"\bservicio externo\b", r"\btimeout\b", r"\bwebhook\b", r"\bcola\b", r"\bservicio no disponible\b"],
        "Reporte/Consulta": [r"\breporte\b", r"\bconsulta\b", r"\bfiltro\b", r"\bexportaci[oó]n\b", r"\bdashboard\b", r"\blistado\b"],
        "Financiero/Contable": [r"\bcontable\b", r"\bfinancier[oa]\b", r"\bmoneda\b", r"\bsaldo\b", r"\binter[eé]s\b", r"\bamortiz", r"\bcomisi[oó]n\b", r"\brevers"],
    }
    return {
        name: sum(1 for pattern in patterns if re.search(pattern, txt, re.IGNORECASE))
        for name, patterns in buckets.items()
    }


def classify_document_type(texto: str) -> str:
    scores = _classify_scores(texto)
    positives = sorted([(name, score) for name, score in scores.items() if score > 0], key=lambda item: item[1], reverse=True)
    if len(positives) >= 2:
        top_name, top_score = positives[0]
        second_name, second_score = positives[1]
        if second_score >= max(1, top_score - 1) and top_name != second_name:
            return "Mixto"
    if positives:
        return positives[0][0]
    return "Workflow/Proceso"


def _extract_sections(texto: str) -> List[Dict[str, str]]:
    lines = _split_lines(texto)
    sections: List[Dict[str, str]] = []
    current_title = "Resumen"
    current_lines: List[str] = []
    heading_pattern = re.compile(
        r"^(?:#{1,6}\s+.+|[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}|\d+(?:\.\d+)*\s+[A-ZÁÉÍÓÚÑ].+|(?:m[oó]dulo|proceso|actor|regla|validaci[oó]n|integraci[oó]n|supuesto|riesgo|reporte|consulta|formulario|api)s?\s*:)\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        if heading_pattern.match(line):
            if current_lines:
                sections.append({"title": current_title, "content": "\n".join(current_lines)})
            current_title = re.sub(r"^#+\s*", "", line).strip(" :") or "Sección"
            current_lines = []
            continue
        current_lines.append(line)
    if current_lines:
        sections.append({"title": current_title, "content": "\n".join(current_lines)})
    return sections[:20]


def _extract_list_by_patterns(texto: str, patterns: Iterable[str], limit: int = 10) -> List[str]:
    matches: List[str] = []
    for line in _split_lines(texto):
        for pattern in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                matches.append(limpiar_texto_qa(line))
                break
    return _dedupe_keep_order(matches)[:limit]


def _extract_actors(texto: str) -> List[str]:
    actor_patterns = [
        r"\busuario(?:s)?\b",
        r"\bcliente(?:s)?\b",
        r"\badministrador(?:es)?\b",
        r"\boperador(?:es)?\b",
        r"\baprobador(?:es)?\b",
        r"\banalista(?:s)?\b",
        r"\bsistema(?:s)?\b",
        r"\bservicio(?:s)? externos?\b",
    ]
    actors: List[str] = []
    txt = texto or ""
    for pattern in actor_patterns:
        for match in re.finditer(pattern, txt, re.IGNORECASE):
            actors.append(match.group(0).strip().capitalize())
    return _dedupe_keep_order(actors)[:10]


def _guess_module_or_process(texto: str, sections: List[Dict[str, str]]) -> str:
    candidates: List[str] = []
    for line in _split_lines(texto)[:50]:
        if re.search(r"\b(m[oó]dulo|proceso|flujo|servicio|pantalla|api|reporte|consulta|historia|formulario)\b", line, re.IGNORECASE):
            candidates.append(limpiar_texto_qa(line))
    for section in sections[:5]:
        if section["title"].lower() != "resumen":
            candidates.append(limpiar_texto_qa(section["title"]))
    return candidates[0] if candidates else "Proceso funcional principal"


def _detect_functional_blocks(texto: str, sections: List[Dict[str, str]]) -> List[str]:
    corpus = [texto or ""] + [section["title"] + "\n" + section["content"] for section in sections]
    blocks: List[str] = []
    for block_name, patterns in _BLOCK_KEYWORDS.items():
        for chunk in corpus:
            if any(re.search(pattern, chunk, re.IGNORECASE) for pattern in patterns):
                blocks.append(block_name)
                break
    if not blocks:
        for section in sections[:6]:
            title = limpiar_texto_qa(section["title"])
            if title and title.lower() != "resumen":
                blocks.append(title)
    return _dedupe_keep_order(blocks)[:12]


def _build_coverage_targets(document_type: str, analysis: Dict) -> List[str]:
    coverage = ["flujo feliz", "errores controlados", "reglas de negocio observables"]
    doc_type = _TYPE_ALIASES.get(document_type.lower(), document_type) if isinstance(document_type, str) else "Workflow/Proceso"

    profiles = {
        "UI/Formulario": ["campos obligatorios", "formato", "longitud", "mensajes de error", "persistencia", "navegación o redirección"],
        "API": ["autenticación", "códigos HTTP", "payload inválido", "campos requeridos", "contrato/schema", "errores controlados", "idempotencia si aplica"],
        "Workflow/Proceso": ["estados", "transiciones", "aprobación/rechazo", "permisos", "restricciones", "actualización visible del estado"],
        "Integración": ["timeout", "servicio no disponible", "datos incompletos", "errores controlados", "reintentos si aplica"],
        "Reporte/Consulta": ["generación", "filtros", "consistencia de datos", "visualización", "exportación si aplica"],
        "Financiero/Contable": ["cálculos", "redondeos", "comisiones", "reversos", "consistencia", "trazabilidad", "impacto en reportes o consultas"],
    }

    if doc_type == "Mixto":
        scores = _classify_scores(json.dumps(analysis, ensure_ascii=False))
        for category, score in scores.items():
            if score > 0 and category in profiles:
                coverage.extend(profiles[category][:4])
    else:
        coverage.extend(profiles.get(doc_type, profiles["Workflow/Proceso"]))

    blocks = analysis.get("functional_blocks", []) or []
    coverage.extend(f"cobertura del bloque {block}" for block in blocks[:8])
    return _dedupe_keep_order(coverage)


def estimate_scenario_volume(texto: str, analysis: Optional[Dict] = None) -> Tuple[int, int]:
    analysis = analysis or {}
    sections = analysis.get("sections", []) or []
    blocks = analysis.get("functional_blocks", []) or []
    document_type = analysis.get("document_type") or classify_document_type(texto)
    base = max(6, min(14, max(1, len((texto or "").splitlines())) // 6))
    complexity = len(blocks) * 2 + len(sections)
    if document_type == "Mixto":
        complexity += 4
    elif document_type in {"API", "Workflow/Proceso", "Integración"}:
        complexity += 2
    elif document_type == "Financiero/Contable":
        complexity += 3
    target = min(48, max(base + complexity, len(blocks) * 3 if blocks else base + 4))
    minimum = min(target, max(6, math.ceil(target * 0.55)))
    return minimum, target


def summarize_analysis_for_prompt(analysis: Dict) -> str:
    items = [
        f"Tipo de documento detectado: {analysis.get('document_type', 'Workflow/Proceso')}",
        f"Módulo o proceso principal: {analysis.get('module_or_process', 'Proceso funcional principal')}",
        "Bloques funcionales detectados: " + ", ".join(analysis.get("functional_blocks", []) or ["No explícitos"]),
        "Actores relevantes: " + ", ".join(analysis.get("actors", []) or ["No explícitos"]),
        "Reglas de negocio: " + "; ".join(analysis.get("business_rules", []) or ["No explícitas"]),
        "Validaciones: " + "; ".join(analysis.get("validations", []) or ["No explícitas"]),
        "Integraciones: " + "; ".join(analysis.get("integrations", []) or ["No explícitas"]),
        "Reportes/consultas: " + "; ".join(analysis.get("reports", []) or ["No explícitos"]),
        "Cálculos: " + "; ".join(analysis.get("calculations", []) or ["No explícitos"]),
        "Riesgos QA: " + "; ".join(analysis.get("risks", []) or ["No explícitos"]),
        "Supuestos: " + "; ".join(analysis.get("assumptions", []) or ["No explícitos"]),
        "Cobertura sugerida: " + "; ".join(analysis.get("coverage_targets", []) or ["Flujo feliz"]),
    ]
    return "\n".join(f"- {item}" for item in items)


def analyze_document_structure(texto: str) -> Dict:
    raw_text = (texto or "").strip()
    limited_text = raw_text[:50000]
    sections = _extract_sections(limited_text)
    document_type = classify_document_type(limited_text)
    analysis = {
        "document_type": document_type,
        "module_or_process": _guess_module_or_process(limited_text, sections),
        "actors": _extract_actors(limited_text),
        "business_rules": _extract_list_by_patterns(limited_text, [r"\bdebe\b", r"\bsolo si\b", r"\bno debe\b", r"\bregla\b", r"\bobligatorio\b", r"\bpermitid[oa]", r"\brestric"], 12),
        "validations": _extract_list_by_patterns(limited_text, [r"\bvalid", r"\bobligatori", r"\bformato\b", r"\blongitud\b", r"\brango\b", r"\bl[ií]mite\b", r"\berror\b"], 12),
        "integrations": _extract_list_by_patterns(limited_text, [r"\bintegraci[oó]n\b", r"\bservicio\b", r"\bapi\b", r"\bwebhook\b", r"\bcola\b", r"\btimeout\b"], 10),
        "reports": _extract_list_by_patterns(limited_text, [r"\breporte\b", r"\bconsulta\b", r"\bfiltro\b", r"\bexporta", r"\bdashboard\b", r"\bvisualiza"], 10),
        "calculations": _extract_list_by_patterns(limited_text, [r"\bc[aá]lcul", r"\binter[eé]s\b", r"\btasa\b", r"\bsaldo\b", r"\btotal\b", r"\bredonde", r"\bcomisi[oó]n\b"], 10),
        "risks": _extract_list_by_patterns(limited_text, [r"\btimeout\b", r"\bfalla\b", r"\brechaz", r"\bduplic", r"\binconsisten", r"\bseguridad\b", r"\bpermiso\b", r"\bservicio no disponible\b"], 10),
        "assumptions": _extract_list_by_patterns(limited_text, [r"\bsupuesto\b", r"\basum", r"\bsi aplica\b", r"\bcuando corresponda\b", r"\bdepende\b"], 8),
        "sections": sections,
        "functional_blocks": _detect_functional_blocks(limited_text, sections),
        "source_excerpt": limited_text[:7000],
    }
    analysis["coverage_targets"] = _build_coverage_targets(document_type, analysis)
    analysis["scenario_volume"] = dict(zip(["minimum", "target"], estimate_scenario_volume(limited_text, analysis)))
    return analysis


def parse_gemini_json_response(texto: str) -> Dict:
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("Gemini devolvió una respuesta vacía.")
    cleaned = texto.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("La respuesta de Gemini no contiene JSON válido.")
    candidate = cleaned[start : end + 1]
    repaired_chars: List[str] = []
    in_string = False
    escaped = False
    for char in candidate:
        if char == '"' and not escaped:
            in_string = not in_string
        if in_string and char in {"\n", "\r"}:
            repaired_chars.append("\\n")
            escaped = False
            continue
        repaired_chars.append(char)
        escaped = (char == "\\") and not escaped
        if char != "\\":
            escaped = False
    try:
        return json.loads("".join(repaired_chars))
    except json.JSONDecodeError as exc:
        raise ValueError(f"No se pudo parsear el JSON de Gemini: {exc}") from exc


def _normalize_type(value: str, title: str = "", analysis: Optional[Dict] = None) -> str:
    txt = limpiar_texto_qa(value or "").lower()
    title_txt = f"{title} {json.dumps(analysis or {}, ensure_ascii=False)}".lower()
    if "segur" in txt or "auth" in txt:
        return "Seguridad"
    if "integr" in txt or re.search(r"timeout|servicio externo|webhook|api", title_txt):
        return "Integracion"
    if "usab" in txt or re.search(r"ui|pantalla|visualiza|mensaje", title_txt):
        return "Usabilidad"
    if "valid" in txt or re.search(r"obligatorio|formato|longitud|inv[aá]lid", title_txt):
        return "Validacion"
    return "Funcional"


def _normalize_priority(value: str, title: str = "", analysis: Optional[Dict] = None) -> str:
    txt = limpiar_texto_qa(value or "").lower()
    combined = f"{txt} {title} {json.dumps(analysis or {}, ensure_ascii=False)}".lower()
    if any(token in combined for token in ["alta", "high", "critical", "critica", "seguridad", "rechazo", "timeout", "integración", "integracion"]):
        return "Alta"
    if any(token in combined for token in ["baja", "low", "visual", "usabilidad"]):
        return "Baja"
    return "Media"


def _split_atomic_statements(texto: str) -> List[str]:
    raw = (texto or "").replace("\\n", "\n")
    items = [
        limpiar_texto_qa(part.strip(" .;-"))
        for part in re.split(r"\n+|;\s+|\.\s+(?=[A-ZÁÉÍÓÚÑ])", raw)
        if part.strip()
    ]
    return [item for item in items if len(item) >= 10]


def _sanitize_expected_result_text(texto: str) -> str:
    """
    Sanitización conservadora para Expected Result: evita recortes agresivos.
    Solo normaliza espacios/saltos y mantiene el contenido funcional completo.
    """
    if not isinstance(texto, str):
        return ""
    cleaned = texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _is_measurable_expected_result(texto: str) -> bool:
    txt = (texto or "").lower()
    return any(token in txt for token in ["muestra", "registra", "genera", "rechaza", "bloquea", "calcula", "retorna", "actualiza", "persiste", "notifica", "permite", "cambia el estado", "responde con"])


def _is_atomic_title(title: str) -> bool:
    txt = (title or "").lower()
    return not any(separator in txt for separator in [" y ", " / ", " & "])


def _scenario_similarity(left: Dict, right: Dict) -> float:
    left_text = " | ".join([str(left.get("Title", "")), str(left.get("Expected Result", "")), str(left.get("Steps", ""))])
    right_text = " | ".join([str(right.get("Title", "")), str(right.get("Expected Result", "")), str(right.get("Steps", ""))])
    return SequenceMatcher(None, left_text.lower(), right_text.lower()).ratio()


def _expected_result_template(title: str, steps: str, scenario_type: str, document_type: str) -> str:
    basis = f"{title} {steps}".lower()
    if document_type == "API" or re.search(r"api|endpoint|http|payload", basis):
        return "El sistema procesa la solicitud, valida el contrato del servicio y responde con el código HTTP y el cuerpo esperado sin exponer errores no controlados"
    if document_type == "UI/Formulario" or re.search(r"formulario|campo|pantalla|guardar|enviar", basis):
        return "El sistema valida los datos ingresados, persiste la información correspondiente y muestra un mensaje visible acorde al resultado de la operación"
    if document_type == "Workflow/Proceso" or re.search(r"aprobar|rechazar|estado|flujo", basis):
        return "El sistema ejecuta la transición solicitada, actualiza el estado visible del proceso y refleja las restricciones y permisos aplicables"
    if document_type == "Integración" or re.search(r"timeout|servicio externo|integraci", basis):
        return "El sistema gestiona la interacción con el servicio dependiente, registra el resultado esperado y muestra una respuesta controlada ante éxito o falla"
    if document_type == "Reporte/Consulta" or re.search(r"reporte|consulta|filtro|export", basis):
        return "El sistema genera la consulta solicitada, muestra datos consistentes según los filtros aplicados y habilita la visualización o exportación cuando corresponde"
    if document_type == "Financiero/Contable" or re.search(r"saldo|comisión|interés|revers", basis):
        return "El sistema aplica la regla financiera correspondiente, actualiza el resultado visible de la operación y conserva consistencia en los datos mostrados"
    if scenario_type == "Validacion":
        return "El sistema bloquea la operación inválida, muestra el mensaje de validación esperado y no persiste cambios no autorizados"
    return "El sistema completa la operación solicitada, refleja el resultado observable esperado y conserva la consistencia funcional de la información"


def _enhance_expected_result(expected: str, title: str, steps: str, scenario_type: str, analysis: Optional[Dict]) -> str:
    analysis = analysis or {}
    document_type = analysis.get("document_type", "Workflow/Proceso")
    cleaned = _sanitize_expected_result_text(expected)
    generic_patterns = [r"^ok$", r"^correcto$", r"^exitoso$", r"^se realiza correctamente$", r"^operación exitosa$"]
    if not cleaned or any(re.fullmatch(pattern, cleaned.lower()) for pattern in generic_patterns) or len(cleaned.split()) < 6:
        return _expected_result_template(title, steps, scenario_type, document_type)
    if not _is_measurable_expected_result(cleaned):
        return _expected_result_template(title, steps, scenario_type, document_type)
    return cleaned


def validate_and_prepare_scenarios(payload: Dict, analysis: Optional[Dict] = None) -> Tuple[pd.DataFrame, Dict]:
    analysis = analysis or {}
    scenarios = payload.get("test_scenarios") or []
    accepted: List[Dict] = []
    dropped: List[Dict] = []

    for raw in scenarios:
        title = limpiar_texto_qa(str(raw.get("title", "")))
        preconditions = normalizar_preconditions(str(raw.get("preconditions", "")))
        steps = normalizar_steps(str(raw.get("steps", "")))
        scenario_type = _normalize_type(str(raw.get("type", "Funcional")), title, analysis)
        priority = _normalize_priority(str(raw.get("priority", "Media")), title, analysis)
        expected = _enhance_expected_result(str(raw.get("expected_result", "")), title, steps, scenario_type, analysis)
        source_basis = limpiar_texto_qa(str(raw.get("source_basis", "explicito"))).lower() or "explicito"
        if source_basis not in {"explicito", "inferido"}:
            source_basis = "inferido" if "infer" in source_basis else "explicito"
        assumption = limpiar_texto_qa(str(raw.get("assumption", "")))
        quality_notes: List[str] = []

        if not title or not steps or not expected:
            quality_notes.append("faltan campos obligatorios")
        if title and not _is_atomic_title(title):
            quality_notes.append("título compuesto")
        if len(_split_atomic_statements(steps)) < 3:
            quality_notes.append("pasos insuficientes")
        if len(_split_atomic_statements(expected)) > 2:
            quality_notes.append("resultado esperado no atómico")
        if not _is_measurable_expected_result(expected):
            quality_notes.append("resultado esperado poco medible")

        candidate = {
            "Title": title,
            "Preconditions": preconditions,
            "Steps": steps,
            "Expected Result": expected,
            "Type": scenario_type if scenario_type in _ALLOWED_TYPES else "Funcional",
            "Priority": priority if priority in _ALLOWED_PRIORITIES else "Media",
            "Estado": limpiar_texto_qa(str(raw.get("Estado", "Pendiente"))) or "Pendiente",
            "source_basis": source_basis,
            "assumption": assumption,
            "quality_notes": "; ".join(quality_notes),
        }

        if quality_notes and any(note in quality_notes for note in ["faltan campos obligatorios", "pasos insuficientes"]):
            dropped.append({"title": title or "(sin título)", "issues": quality_notes})
            continue

        duplicate = next((existing for existing in accepted if _scenario_similarity(existing, candidate) >= 0.9), None)
        if duplicate is not None:
            dropped.append({"title": title or "(sin título)", "issues": ["duplicado semántico"]})
            continue

        accepted.append(candidate)

    export_columns = TESTRAIL_EXPORT_COLUMNS + ["source_basis", "assumption", "quality_notes"]
    if not accepted:
        return pd.DataFrame(columns=export_columns), {"accepted": 0, "dropped": dropped}

    df = pd.DataFrame(accepted)
    for column in export_columns:
        if column not in df.columns:
            df[column] = ""
    df = df[export_columns].copy()
    return df, {"accepted": len(df), "dropped": dropped}


def build_testrail_export_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Contrato estricto de exportación TestRail:
    - SOLO columnas permitidas
    - orden fijo
    - columnas faltantes se crean vacías
    """
    export_df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    for column in TESTRAIL_EXPORT_COLUMNS:
        if column not in export_df.columns:
            export_df[column] = ""
    export_df = export_df[TESTRAIL_EXPORT_COLUMNS].copy()
    for column in TESTRAIL_EXPORT_COLUMNS:
        export_df[column] = export_df[column].fillna("").astype(str)
    # Blindaje final del contrato.
    if list(export_df.columns) != TESTRAIL_EXPORT_COLUMNS:
        export_df = export_df.reindex(columns=TESTRAIL_EXPORT_COLUMNS, fill_value="")
    return export_df


def prepare_testrail_export(df: pd.DataFrame) -> pd.DataFrame:
    # Compatibilidad hacia atrás.
    return build_testrail_export_dataframe(df)


def prepare_extended_export(df: pd.DataFrame) -> pd.DataFrame:
    export_df = build_testrail_export_dataframe(df)
    for column in INTERNAL_ONLY_COLUMNS:
        if column in df.columns:
            export_df[column] = df[column].fillna("").astype(str)
    return export_df


def scenarios_dataframe_to_csv(df: pd.DataFrame, extended: bool = False) -> str:
    export_df = prepare_extended_export(df) if extended else build_testrail_export_dataframe(df)
    return export_df.to_csv(index=False)
