# Vistas operativas públicas — 2026-09-08

## Alcance

Streamlit y Google Drive/Sheets autenticados. Sin Firebase. Se conserva el resumen
contable y sus fuentes existentes. Navegación persistente: Resumen, Control de
fugas, Canales, Rutas y Fricción. Los filtros de zona, canal y periodo se comparten.

## Contrato del modelo

- Precio comparable = Valor_Neto_Ingresado / Cantidad_Ingresada, sin impuestos.
- GMV de cada etapa = cantidad comercial de esa etapa × precio comparable.
- Cantidad devuelta: Cantidad_Devuelta_UM_Comercial, nunca sustituida por una unidad incompatible.
- Entregado modelado = facturado modelado − devuelto modelado.
- Fuga previa = max(cantidad ingresada − facturada, 0) × precio comparable.
- Peso comparable = Peso_Ingresado / Cantidad_Ingresada, tratado como kg según
  la decisión aprobada. La interfaz lo muestra en toneladas métricas: kg / 1,000.
- No hay región validada ni fecha prometida: no inventar regiones, OTIF ni causas de stockout.
- Datos inválidos, negativos o devoluciones superiores a lo facturado invalidan
  el cálculo afectado. Un total incompleto queda nulo; no se publica un subtotal como total.
- Divisor cero: indicador no disponible. Bonificaciones con cantidad positiva y
  precio cero se preservan. Pedidos/clientes se cuentan con nunique después de filtrar.
- El saldo original AC sigue exclusivamente en Resumen. No confundir el precio
  comparable del modelo con los precios fiscales reales de cada factura.
- Conversión institucional: soles / 3.396. No se incorpora margen sin costos.

## Rendimiento y seguridad

Limpieza de texto y números regionales vectorizada; mantiene comas decimales y
formatos mixtos. Cruces de maestro m:1 siguen bloqueando duplicados ambiguos.
La cuenta de servicio se materializa antes de crear trabajadores.
Caché de capas: cubo diario y tablas de identidad para nunique exacto.
Las identidades se mantienen en el servidor; las vistas públicas solo renderizan
agregados. Sin tablas de clientes, SKU individual ni descarga.

## Verificación reproducible

`python -m unittest discover -s tests -v`

Incluye contratos existentes, parser regional/acentos, totales del modelo,
conteos únicos, filtros, nulos y render de todas las vistas con comprobación
de ausencia de identidades en tablas. Las pruebas usan datos sintéticos.
Una prueba adicional con secretos locales se ejecuta sin registrar credenciales
ni filas. La evidencia de publicación debe comprobarse aparte en la URL pública.

## Fuente operativa única

Este documento es el hilo operativo vigente para publicación y continuidad.

- Aplicación única: `https://dashboard-bees.streamlit.app`.
- Rama canónica de despliegue: `codex/metricas-operacion-publica`.
- Punto de entrada: `streamlit_app.py`.
- La rama `main` se conserva como historial base del repositorio, pero no es
  fuente de una aplicación de Streamlit.
- La rama temporal `codex/dashboard-conciliacion-pruebas` y el despliegue
  duplicado de `main` fueron retirados el 2026-09-08 tras validar la aplicación
  canónica con filtros, métricas y agregados reales.
- Los secretos quedan exclusivamente en Streamlit Community Cloud y nunca se
  versionan ni registran en documentación, commits o pruebas.

## Procedimiento de despliegue y aceptación

1. Confirmar que el cambio está en `codex/metricas-operacion-publica` y que
   las pruebas reproducibles pasan.
2. Actualizar únicamente `dashboard-bees.streamlit.app` desde esa rama y
   `streamlit_app.py`.
3. Verificar en la sesión administrativa la carga de fuentes, cobertura,
   filtros, KPIs y los módulos Resumen, Fugas, Canales, Rutas y Fricción.
4. Probar desde una sesión anónima que la URL no redirige al acceso de Streamlit.
   Una etiqueta visual de “pública” no sustituye esta comprobación.
5. Si Streamlit solicita autenticación pese a estar marcada como pública,
   conservar esta rama canónica y escalar el caso; no recrear ramas ni copias
   paralelas.

## Estado de la consolidación

- Una sola aplicación configurada en Streamlit: `dashboard-bees.streamlit.app`.
- Una sola rama Codex de operación: `codex/metricas-operacion-publica`.
- Accesibilidad visual: contraste para tema claro/oscuro, foco visible,
  salto seguro de títulos y reducción de movimiento.
- La disponibilidad pública anónima solo se comunica tras esa validación.
