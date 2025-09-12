import pandas as pd
import streamlit as st

# 🧠 Marcar cambios celda por celda
def marcar_cambios(df_original: pd.DataFrame, df_nuevo: pd.DataFrame):
    """
    Compara dos DataFrames y agrega una columna 'Estado' por fila:
    - 'Modificado' si al menos una celda cambió
    - 'Sin cambios' si todo está igual
    También resalta celdas modificadas agregando sufijo ⚠️ en la cabecera.
    """
    df_estado = df_nuevo.copy()
    columnas = df_original.columns

    for idx, row in df_nuevo.iterrows():
        modificado = False
        for col in columnas:
            original_val = str(df_original.at[idx, col]).strip()
            nuevo_val = str(row[col]).strip()
            if original_val != nuevo_val:
                df_estado.at[idx, col] = nuevo_val
                modificado = True
        df_estado.at[idx, "Estado"] = "Modificado" if modificado else "Sin cambios"

    return df_estado


# 🎨 Colorear filas modificadas
def colorear_filas(df: pd.DataFrame):
    """
    Devuelve un DataFrame estilizado donde las filas modificadas se pintan en naranja.
    """
    def color_fila(row):
        color = "#fff3cd" if row.get("Estado") == "Modificado" else "#ffffff"
        return ["background-color: {}".format(color) for _ in row]

    return df.style.apply(color_fila, axis=1)
