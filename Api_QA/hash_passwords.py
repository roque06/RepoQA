# hash_passwords.py
from streamlit_authenticator import Hasher  # 👈 import directo
passwords = ["clave_roque", "clave_admin"]
hashes = Hasher(passwords).generate()       # 👈 generate desde Hasher
print("Hashes generados:\n")
for i, h in enumerate(hashes, start=1):
    print(f"Contraseña {i}: {h}")
