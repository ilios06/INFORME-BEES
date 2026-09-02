# Acceso público y seguridad de datos

## Decisión vigente

El dashboard puede ser público para quien tenga su URL, pero muestra solo agregados. No expone enlaces de Drive, IDs de pedidos/facturas/clientes, nombres de clientes, SKU por fila, tablas de detalle ni descargas.

## Controles implementados

1. Los IDs de Google Sheets y las credenciales viven exclusivamente en secretos de Streamlit Cloud.
2. La cuenta de servicio debe tener únicamente rol **Lector** en los tres libros y usar el alcance `drive.readonly`.
3. La aplicación exporta los libros con Drive API autenticada; no depende de enlaces de descarga pública.
4. Errores de autenticación y fuente no muestran secretos ni detalles técnicos al visitante.
5. La visualización solo usa gráficos y métricas agregadas; los controles de Plotly no permiten descargar datos.
6. Si un libro supera el límite de exportación de Drive, se lee por rangos mediante Sheets API con alcance `spreadsheets.readonly`.

## Límite importante

Una página pública no puede impedir que una persona copie, capture o reconstruya cifras que ve. Si incluso los agregados son confidenciales, la solución correcta es restringir acceso con autenticación/SSO y no mantener la aplicación pública.

## Antes de publicar

1. Crear o seleccionar una cuenta de servicio en un proyecto de Google Cloud.
2. Compartir los tres libros con su correo `client_email` como Lector.
3. Retirar el acceso público a los libros y verificar que una cuenta anónima no pueda abrirlos.
4. Cargar los secretos en Streamlit Cloud; no crear `.streamlit/secrets.toml` dentro de Git.
5. Publicar desde una rama revisada y comprobar que el enlace no redirige a autenticación de Streamlit.
6. Revisar los enlaces usados por versiones previas y revocar cualquier permiso público heredado; el historial del repositorio no debe considerarse un mecanismo de control de acceso.
