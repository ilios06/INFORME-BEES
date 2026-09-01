# INFORME-BEES

Dashboard Streamlit para la conciliación comercial BEES/COSTEÑO. Combina el histórico General con la ventana 3M sin duplicar el periodo vigente: General aporta las fechas previas al inicio de 3M y 3M aporta el periodo reciente.

## Ejecución local

1. Instala dependencias: `python -m pip install -r requirements.txt`.
2. Copia `.streamlit/secrets.example.toml` como `.streamlit/secrets.toml` y completa las credenciales de una cuenta de servicio de solo lectura y los IDs de las fuentes.
3. Ejecuta `streamlit run streamlit_app.py`.

La versión pública está diseñada para mostrar agregados, no datos transaccionales. Consulta [la política de seguridad](docs/PUBLIC_ACCESS_SECURITY.md) antes de configurar Streamlit Cloud.
