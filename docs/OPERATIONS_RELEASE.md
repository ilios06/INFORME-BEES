# Vistas operativas públicas — 2026-09-05

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

## Unificación de aplicaciones

Objetivo: dashboard-bees.streamlit.app sobre main. GitHub no controla por sí solo
la asociación de rama guardada en Streamlit Community Cloud. Se requiere una
sesión administrativa de Streamlit. No borrar la aplicación actual antes de
validar la sustituta y conservar sus secretos. Mantener ambas ramas sincronizadas
es una medida transitoria, no equivale a cambiar la configuración de Cloud.
