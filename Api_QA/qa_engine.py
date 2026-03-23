from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Tuple

import pandas as pd

if __package__:
    from .utils_csv import limpiar_texto_qa, normalizar_preconditions, normalizar_steps
else:
    from utils_csv import limpiar_texto_qa, normalizar_preconditions, normalizar_steps

CSV_COLUMNS = ["Title", "Preconditions", "Steps", "Expected Result", "Type", "Priority"]
_ALLOWED_TYPES = {"Funcional", "Validacion", "Integracion", "Seguridad", "Usabilidad"}
_ALLOWED_PRIORITIES = {"Alta", "Media", "Baja"}


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


def classify_document_type(texto: str) -> str:
    txt = (texto or "").lower()
    buckets = {
        "API": [r"\bendpoint\b", r"\bhttp\b", r"\bjson\b", r"\brequest\b", r"\bresponse\b", r"\bauthorization\b", r"\btoken\b", r"\bapi\b", r"\bintegraci[oó]n\b", r"\bservicio externo\b"],
        "UI/Formulario": [r"\bformulario\b", r"\bpantalla\b", r"\bbot[oó]n\b", r"\bcampo\b", r"\binterfaz\b", r"\bui\b", r"\bfrontend\b"],
        "Documento financiero/contable": [r"\bcontable\b", r"\basiento\b", r"\bmoneda\b", r"\bsaldo\b", r"\binter[eé]s\b", r"\bamortiz", r"\bcuota\b", r"\brevers"],
        "Proceso de negocio": [r"\bproceso\b", r"\bflujo\b", r"\baprobaci[oó]n\b", r"\bsolicitud\b", r"\bcliente\b", r"\bnegocio\b", r"\boperaci[oó]n\b"],
    }
    scores = {
        name: sum(1 for pattern in patterns if re.search(pattern, txt, re.IGNORECASE))
        for name, patterns in buckets.items()
    }
    positive = sorted(
        [(name, score) for name, score in scores.items() if score > 0],
        key=lambda item: item[1],
        reverse=True,
    )
    if len(positive) >= 2:
        top_name, top_score = positive[0]
        second_name, second_score = positive[1]
        if second_score >= 1 and top_name != second_name:
            return "Mixto"
    if positive:
        return positive[0][0]
    return "Proceso de negocio"


def _extract_sections(texto: str) -> List[Dict[str, str]]:
    lines = _split_lines(texto)
    sections: List[Dict[str, str]] = []
    current_title = "Resumen"
    current_lines: List[str] = []
    heading_pattern = re.compile(r"^(?:#{1,6}\s+.+|[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}|\d+(?:\.\d+)*\s+[A-ZÁÉÍÓÚÑ].+|(?:m[oó]dulo|proceso|actor|regla|validaci[oó]n|integraci[oó]n|supuesto|riesgo|c[aá]lculo)s?\s*:)\s*$", re.IGNORECASE)

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
    return sections[:12]


def _extract_list_by_patterns(texto: str, patterns: Iterable[str], limit: int = 8) -> List[str]:
    matches: List[str] = []
    for line in _split_lines(texto):
        for pattern in patterns:
            if re.search(pattern, line, re.IGNORECASE):
                matches.append(limpiar_texto_qa(line))
                break
    return _dedupe_keep_order(matches)[:limit]


def _guess_module_or_process(texto: str, sections: List[Dict[str, str]]) -> str:
    candidates: List[str] = []
    for line in _split_lines(texto)[:40]:
        if re.search(r"\b(m[oó]dulo|proceso|flujo|servicio|pantalla|api|reporte|caso de uso|historia)\b", line, re.IGNORECASE):
            candidates.append(limpiar_texto_qa(line))
    for section in sections[:3]:
        if section["title"].lower() != "resumen":
            candidates.append(limpiar_texto_qa(section["title"]))
    return candidates[0] if candidates else "Proceso funcional principal"


def _extract_actors(texto: str) -> List[str]:
    actor_patterns = [
        r"\busuario(?:s)?\b",
        r"\bcliente(?:s)?\b",
        r"\boperador(?:es)?\b",
        r"\badministrador(?:es)?\b",
        r"\bsistema(?:s)?\b",
        r"\bservicio(?:s)? externos?\b",
        r"\baprobador(?:es)?\b",
        r"\bcaja(?:s)?\b",
    ]
    actors: List[str] = []
    txt = texto or ""
    for pattern in actor_patterns:
        for match in re.finditer(pattern, txt, re.IGNORECASE):
            actors.append(match.group(0).strip().capitalize())
    return _dedupe_keep_order(actors)[:8]


def _coverage_for_document_type(document_type: str, analysis: Dict) -> List[str]:
    coverage = ["flujo feliz", "reglas de negocio", "errores controlados"]
    txt = json.dumps(analysis, ensure_ascii=False).lower()
    if document_type in {"UI/Formulario", "Mixto"}:
        coverage.extend(["validaciones de campos", "mensajes visibles", "persistencia de datos"])
    if document_type in {"API", "Mixto"}:
        coverage.extend(["códigos HTTP", "schema de respuesta", "autenticación y autorización"])
    if document_type == "Documento financiero/contable" or re.search(r"saldo|inter[eé]s|cuota|amortiz|contable", txt):
        coverage.extend(["cálculos", "redondeos", "reversos y consistencia contable"])
    if re.search(r"integraci[oó]n|servicio|timeout|cola|webhook", txt):
        coverage.extend(["errores de integración", "timeouts", "reintentos y degradación controlada"])
    if re.search(r"reporte|consulta|filtro|dashboard", txt):
        coverage.extend(["filtros", "consistencia del reporte", "orden y paginación"])
    return _dedupe_keep_order(coverage)


def summarize_analysis_for_prompt(analysis: Dict) -> str:
    items = [
        f"Tipo de documento detectado: {analysis.get('document_type', 'Proceso de negocio')}",
        f"Módulo o proceso principal: {analysis.get('module_or_process', 'Proceso funcional principal')}",
        "Actores relevantes: " + ", ".join(analysis.get("actors", []) or ["No explícitos"]),
        "Reglas de negocio: " + "; ".join(analysis.get("business_rules", []) or ["No explícitas"]),
        "Validaciones: " + "; ".join(analysis.get("validations", []) or ["No explícitas"]),
        "Integraciones: " + "; ".join(analysis.get("integrations", []) or ["No explícitas"]),
        "Cálculos: " + "; ".join(analysis.get("calculations", []) or ["No explícitos"]),
        "Riesgos QA: " + "; ".join(analysis.get("risks", []) or ["No explícitos"]),
        "Supuestos: " + "; ".join(analysis.get("assumptions", []) or ["No explícitos"]),
        "Cobertura sugerida: " + "; ".join(analysis.get("coverage_targets", []) or ["Flujo feliz"]),
    ]
    return "\n".join(f"- {item}" for item in items)


def analyze_document_structure(texto: str) -> Dict:
    raw_text = (texto or "").strip()
    limited_text = raw_text[:30000]
    sections = _extract_sections(limited_text)
    document_type = classify_document_type(limited_text)
    analysis = {
        "document_type": document_type,
        "module_or_process": _guess_module_or_process(limited_text, sections),
        "actors": _extract_actors(limited_text),
        "business_rules": _extract_list_by_patterns(limited_text, [r"\bdebe\b", r"\bsolo si\b", r"\bno debe\b", r"\bregla\b", r"\bobligatorio\b", r"\bpermitid[oa]"], 10),
        "validations": _extract_list_by_patterns(limited_text, [r"\bvalid", r"\bobligatori", r"\bformato\b", r"\brango\b", r"\bl[ií]mite\b", r"\berror\b"], 10),
        "integrations": _extract_list_by_patterns(limited_text, [r"\bintegraci[oó]n\b", r"\bservicio\b", r"\bapi\b", r"\bwebhook\b", r"\bcola\b", r"\barchivo\b"], 8),
        "calculations": _extract_list_by_patterns(limited_text, [r"\bc[aá]lcul", r"\binter[eé]s\b", r"\btasa\b", r"\bsaldo\b", r"\btotal\b", r"\bredonde"], 8),
        "risks": _extract_list_by_patterns(limited_text, [r"\btimeout\b", r"\bfalla\b", r"\brechaz", r"\bduplic", r"\binconsisten", r"\bseguridad\b", r"\bpermiso\b"], 8),
        "assumptions": _extract_list_by_patterns(limited_text, [r"\bsupuesto\b", r"\basum", r"\bsi aplica\b", r"\bcuando corresponda\b", r"\bdepende\b"], 8),
        "sections": sections,
        "source_excerpt": limited_text[:5000],
    }
    analysis["coverage_targets"] = _coverage_for_document_type(document_type, analysis)
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
    candidate = "".join(repaired_chars)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"No se pudo parsear el JSON de Gemini: {exc}") from exc


def _normalize_type(value: str) -> str:
    txt = limpiar_texto_qa(value or "").lower()
    if "integr" in txt:
        return "Integracion"
    if "segur" in txt or "auth" in txt:
        return "Seguridad"
    if "usab" in txt or "ux" in txt:
        return "Usabilidad"
    if "valid" in txt or "error" in txt:
        return "Validacion"
    return "Funcional"


def _normalize_priority(value: str) -> str:
    txt = limpiar_texto_qa(value or "").lower()
    if any(token in txt for token in ["alta", "high", "critical", "critica"]):
        return "Alta"
    if any(token in txt for token in ["baja", "low"]):
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


def _is_measurable_expected_result(texto: str) -> bool:
    txt = (texto or "").lower()
    return any(token in txt for token in ["muestra", "registra", "genera", "rechaza", "bloquea", "calcula", "retorna", "actualiza", "persiste", "notifica", "permite"])


def _is_atomic_title(title: str) -> bool:
    txt = (title or "").lower()
    separators = [" y ", " / ", " & "]
    return not any(sep in txt for sep in separators)


def _scenario_similarity(left: Dict, right: Dict) -> float:
    left_text = " | ".join([str(left.get("Title", "")), str(left.get("Expected Result", "")), str(left.get("Steps", ""))])
    right_text = " | ".join([str(right.get("Title", "")), str(right.get("Expected Result", "")), str(right.get("Steps", ""))])
    return SequenceMatcher(None, left_text.lower(), right_text.lower()).ratio()


def validate_and_prepare_scenarios(payload: Dict) -> Tuple[pd.DataFrame, Dict]:
    scenarios = payload.get("test_scenarios") or []
    accepted: List[Dict] = []
    dropped: List[Dict] = []

    for raw in scenarios:
        title = limpiar_texto_qa(str(raw.get("title", "")))
        preconditions = normalizar_preconditions(str(raw.get("preconditions", "")))
        steps = normalizar_steps(str(raw.get("steps", "")))
        expected = limpiar_texto_qa(str(raw.get("expected_result", "")))
        scenario_type = _normalize_type(str(raw.get("type", "Funcional")))
        priority = _normalize_priority(str(raw.get("priority", "Media")))
        source_basis = limpiar_texto_qa(str(raw.get("source_basis", "explicito"))).lower() or "explicito"
        if source_basis not in {"explicito", "inferido"}:
            source_basis = "inferido" if "infer" in source_basis else "explicito"
        assumption = limpiar_texto_qa(str(raw.get("assumption", "")))

        issues = []
        if not title or not steps or not expected:
            issues.append("faltan campos obligatorios")
        if title and not _is_atomic_title(title):
            issues.append("título compuesto")
        step_items = _split_atomic_statements(steps)
        if len(step_items) < 3:
            issues.append("pasos insuficientes")
        expected_items = _split_atomic_statements(expected)
        if len(expected_items) > 2:
            issues.append("resultado esperado no atómico")
        if expected and not _is_measurable_expected_result(expected):
            issues.append("resultado esperado poco medible")
        if scenario_type not in _ALLOWED_TYPES:
            scenario_type = "Funcional"
        if priority not in _ALLOWED_PRIORITIES:
            priority = "Media"

        candidate = {
            "Title": title,
            "Preconditions": preconditions,
            "Steps": steps,
            "Expected Result": expected,
            "Type": scenario_type,
            "Priority": priority,
            "source_basis": source_basis,
            "assumption": assumption,
        }

        if issues:
            dropped.append({"title": title or "(sin título)", "issues": issues})
            continue

        duplicate = next((existing for existing in accepted if _scenario_similarity(existing, candidate) >= 0.9), None)
        if duplicate is not None:
            dropped.append({"title": title, "issues": ["duplicado semántico"]})
            continue

        accepted.append(candidate)

    df = pd.DataFrame(accepted)
    if df.empty:
        return pd.DataFrame(columns=CSV_COLUMNS + ["source_basis", "assumption"]), {"accepted": 0, "dropped": dropped}

    for column in CSV_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[CSV_COLUMNS + ["source_basis", "assumption"]].copy()
    df.insert(len(CSV_COLUMNS), "Estado", "Pendiente")
    return df, {"accepted": len(df), "dropped": dropped}


def scenarios_dataframe_to_csv(df: pd.DataFrame) -> str:
    ordered_columns = [column for column in CSV_COLUMNS if column in df.columns]
    return df[ordered_columns].to_csv(index=False)
