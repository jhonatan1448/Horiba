# 🌱 Monitoreo Agrícola – HORIBA LAQUAtwin

App de Streamlit para registrar y analizar pH, CE, NO3⁻, K⁺, Ca²⁺ y Na⁺ medidos con HORIBA LAQUAtwin
en agua de riego, solución de suelo y savia (ECP), con rangos de referencia por etapa fenológica.

## Estructura del repositorio

```
app.py             ← la aplicación
requirements.txt   ← librerías que instala Streamlit Cloud
.gitignore         ← evita subir los CSV con tus datos
README.md
```

## Publicar en Streamlit Community Cloud

1. Crea un repositorio en GitHub y sube estos 4 archivos (botón **Add file → Upload files**).
2. Entra a https://share.streamlit.io e inicia sesión con tu cuenta de GitHub.
3. **Create app** → elige el repositorio, rama `main` y archivo principal `app.py`.
4. **Deploy**. En unos minutos tendrás un enlace `https://<nombre>.streamlit.app`.

Cada vez que subas un cambio a GitHub, la app se actualiza sola.

## ⚠️ Importante sobre los datos

Streamlit Cloud **no guarda archivos de forma permanente**: cuando la app se reinicia o se
"duerme" por inactividad, el CSV se borra. Por eso la barra lateral tiene:

- **📥 Descargar respaldo (CSV)**: hazlo al final de cada jornada.
- **📤 Restaurar**: sube el respaldo si la app se reinició.

## Ejecutar en tu computador

```bash
pip install -r requirements.txt
streamlit run app.py
```
