# 🌱 Monitoreo Agrícola – HORIBA LAQUAtwin

App de Streamlit para registrar y analizar pH, CE, NO3⁻, K⁺, Ca²⁺ y Na⁺ medidos con HORIBA LAQUAtwin
en agua de riego, solución de suelo y savia (ECP), con rangos de referencia por etapa fenológica.

## Estructura del repositorio

```
app.py               ← la aplicación
requirements.txt     ← librerías que instala Streamlit Cloud
.gitignore           ← evita subir los CSV con tus datos
secrets_ejemplo.toml ← plantilla para conectar Google Sheets (solo de guía)
README.md
```

## Publicar en Streamlit Community Cloud

1. Crea un repositorio en GitHub y sube estos 4 archivos (botón **Add file → Upload files**).
2. Entra a https://share.streamlit.io e inicia sesión con tu cuenta de GitHub.
3. **Create app** → elige el repositorio, rama `main` y archivo principal `app.py`.
4. **Deploy**. En unos minutos tendrás un enlace `https://<nombre>.streamlit.app`.

Cada vez que subas un cambio a GitHub, la app se actualiza sola.

## ☁️ Guardado permanente en Google Sheets

Sin esta configuración la app funciona, pero guarda en archivos temporales que Streamlit Cloud
borra al reiniciarse. Con Google Sheets los datos quedan guardados para siempre.

### A. Crear la hoja de cálculo
1. Entra a https://sheets.google.com y crea una hoja en blanco, por ejemplo "Datos HORIBA".
2. Copia el enlace de la barra de direcciones (lo usarás en el paso D).

### B. Crear la "cuenta de servicio" (un usuario robot que escribe en la hoja)
1. Entra a https://console.cloud.google.com con tu cuenta de Google.
2. Arriba, en el selector de proyectos → **Proyecto nuevo** → nombre `horiba-app` → **Crear**.
3. Menú ☰ → **APIs y servicios → Biblioteca**. Busca y **habilita** estas dos:
   - **Google Sheets API**
   - **Google Drive API**
4. Menú ☰ → **IAM y administración → Cuentas de servicio → + Crear cuenta de servicio**.
   Nombre: `horiba-app` → **Crear y continuar** → **Listo** (no necesita roles).
5. Haz clic en la cuenta creada → pestaña **Claves → Agregar clave → Crear clave nueva → JSON → Crear**.
   Se descarga un archivo `.json`. **Guárdalo bien y no lo compartas ni lo subas a GitHub.**

### C. Compartir la hoja con el robot
1. Abre el `.json` con el Bloc de notas y copia el valor de `client_email`
   (algo como `horiba-app@horiba-app-12345.iam.gserviceaccount.com`).
2. En tu hoja de Google → **Compartir** → pega ese correo → rol **Editor** → **Enviar**.

### D. Pegar las credenciales en Streamlit Cloud
1. En https://share.streamlit.io → en tu app, los tres puntos **⋮ → Settings → Secrets**.
2. Copia el contenido de `secrets_ejemplo.toml` y reemplaza cada valor con los de tu `.json`
   y el enlace de tu hoja. La `private_key` debe quedar en una sola línea, con los `\n` tal cual vienen en el JSON.
3. **Save**. La app se reinicia y en la barra lateral debe aparecer **"☁️ Guardando en Google Sheets"**.

La app crea sola las pestañas `datos` y `rangos` dentro de la hoja.
Si tenías datos guardados, súbelos con **📤 Restaurar** en la barra lateral.

## Respaldo manual

Aun con Google Sheets, la barra lateral permite **📥 descargar** y **📤 restaurar** un respaldo CSV.

## Ejecutar en tu computador

```bash
pip install -r requirements.txt
streamlit run app.py
```
