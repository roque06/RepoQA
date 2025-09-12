from datetime import datetime

def asignar_origen(generacion_valida: bool) -> str:
    return "Gemini CSV" if generacion_valida else "Fallback híbrido"

def registrar_error(mensaje_error: str, tipo_error: str, respuesta_gemini: str, ruta_log: str = "log_fallos.txt") -> None:
    with open(ruta_log, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] {tipo_error}: {mensaje_error}\nRespuesta:\n{respuesta_gemini}\n---\n")

def es_plano(texto_steps: str) -> bool:
    # Detecta si el contenido está mal estructurado (sin bullets, todo seguido)
    return not any(simbolo in texto_steps for simbolo in ["•", "-", "*", "\n"])

def regenerar_steps(prompt_inicial: str, llamar_a_gemini_fn) -> str:
    instrucciones = """
Reformula los pasos del escenario con formato bullet.
Sé claro, conciso y enfocado en acciones concretas.
Evita repetir precondiciones o resultados esperados.
Usa una acción por línea en lenguaje técnico simple.
"""
    return llamar_a_gemini_fn(prompt_inicial + "\n" + instrucciones)
