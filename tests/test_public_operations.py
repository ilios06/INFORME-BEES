import unittest
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from test_contracts import raw_row
from src.processing.cleaner import clean_conciliation, parse_regional_number, parse_regional_series, fold_series
from src.processing.reconciler import merge_master, apply_business_rules
from src.analytics.public_dashboard import adaptive_granularity, operational_frame, period_compare
from src.analytics.operations import layers, summary, select


def fixture():
    row = raw_row('PRIVATE_ORDER', '01/08/2026', 'PRIVATE_INVOICE', 84)
    row.update(Codigo_Cliente='PRIVATE_CLIENT', Cantidad_Ingresada=10, Cantidad_Facturada=8,
               Cantidad_Devuelta_UM_Comercial=2, Valor_Neto_Ingresado=100, Peso_Ingresado=20,
               Total_Devuelto=20, Motivo_Devolucion='Dif precio', Zona_OfVta='LÍMA', Columna_AE_Zpedidos='R1')
    data, _ = clean_conciliation(pd.DataFrame([row, row]), '3M')
    return apply_business_rules(merge_master(data, pd.DataFrame([{
        'Material':'SKU-1','Marca':'Marca','Categoria Cuota':'Categoría'}])), Path('config/return_reasons.json'))


class PublicOperationsTest(unittest.TestCase):
    def test_adaptive_granularity_thresholds(self):
        self.assertEqual(adaptive_granularity('2026-01-01', '2026-01-31'), 'Diario')
        self.assertEqual(adaptive_granularity('2026-01-01', '2026-02-01'), 'Semanal')
        self.assertEqual(adaptive_granularity('2026-01-01', '2026-06-29'), 'Semanal')
        self.assertEqual(adaptive_granularity('2026-01-01', '2026-06-30'), 'Mensual')

    def test_comparison_periods_are_exact(self):
        self.assertEqual(period_compare('2026-08-10', '2026-08-19', 'Vs. periodo anterior (PoP)'),
                         (pd.Timestamp('2026-07-31'), pd.Timestamp('2026-08-09')))
        self.assertEqual(period_compare('2026-08-10', '2026-08-19', 'Vs. mismo periodo año anterior (YoY)'),
                         (pd.Timestamp('2025-08-10'), pd.Timestamp('2025-08-19')))
    def test_parser_parity(self):
        values = pd.Series(['57,992838','1.234,56','1,234.56','(S/ 12,34)',None,'bad',1.23, True,'nan'])
        pd.testing.assert_series_equal(parse_regional_series(values), values.map(parse_regional_number), check_names=False)
        self.assertEqual(fold_series(pd.Series(['LÍMA'])).iloc[0], 'lima')

    def test_totals_and_unique_counts(self):
        result = summary(layers(operational_frame(fixture())), ['Total']).iloc[0]
        self.assertEqual(result.gmv_facturado, 160)
        self.assertEqual(result.gmv_entregado, 120)
        self.assertEqual(result.fuga_pre, 40)
        self.assertEqual(result.pedidos_facturados, 1)
        self.assertEqual(result.clientes, 1)
        self.assertEqual(result.kg_facturado / 1_000, 0.032)

    def test_missing_return_does_not_become_zero(self):
        data = fixture()
        data.loc[0, 'Cantidad_Devuelta_UM_Comercial'] = float('nan')
        result = summary(layers(operational_frame(data)), ['Total']).iloc[0]
        self.assertTrue(pd.isna(result.gmv_devuelto))
        self.assertTrue(pd.isna(result.tasa_devolucion))

    def test_explicit_stage_values_keep_funnel_available_when_units_cannot_model_a_line(self):
        data = fixture()
        data.loc[0, ['Cantidad_Ingresada', 'Cantidad_Facturada', 'Cantidad_Devuelta_UM_Comercial']] = 0
        data.loc[0, ['Valor_Neto_Ingresado', 'Valor_Neto_Facturado', 'Valor_Neto_Devuelto']] = [100, 80, 20]
        data.loc[0, ['Peso_Ingresado', 'Peso_Facturado', 'Peso_Neto_Devuelto']] = [20, 16, 4]
        result = summary(layers(operational_frame(data)), ['Total']).iloc[0]
        self.assertEqual(result.gmv_ingresado, 200)
        self.assertEqual(result.gmv_facturado, 160)
        self.assertEqual(result.gmv_devuelto, 40)
        self.assertEqual(result.fuga_pre, 40)

    def test_signed_entered_adjustment_is_preserved_in_funnel_base(self):
        data = fixture()
        data.loc[0, ['Valor_Neto_Ingresado', 'Valor_Neto_Facturado', 'Valor_Neto_Devuelto']] = [-10, 0, 0]
        result = summary(layers(operational_frame(data)), ['Total']).iloc[0]
        self.assertEqual(result.gmv_ingresado, 90)
        self.assertEqual(result.gmv_facturado, 80)
        self.assertEqual(result.fuga_pre, 20)

    def test_filters(self):
        result = select(layers(operational_frame(fixture())), '2026-08-01','2026-08-31', {'canal':['COSTEÑO']})
        self.assertTrue(result['cube'].empty)

    def test_routes_without_invoices_render_an_explanation(self):
        app = AppTest.from_string('''
from test_public_operations import fixture
from src.analytics.public_dashboard import render_operations
import pandas as pd
data = fixture(); data['has_invoice'] = False
render_operations(data, 'Rutas', (pd.Timestamp('2026-08-01'), pd.Timestamp('2026-08-31')))
''').run(timeout=30)
        self.assertEqual(len(app.exception), 0, str(app.exception))
        self.assertIn('No hay rutas con facturación y devolución comparables', ' '.join(item.value for item in app.info))

    def test_all_public_views_render_without_identifiers(self):
        for section in ['Control de fugas','Canales','Rutas','Fricción']:
            app = AppTest.from_string('''
from test_public_operations import fixture
from src.analytics.public_dashboard import render_operations
import pandas as pd
render_operations(fixture(), SECTION, (pd.Timestamp('2026-08-01'), pd.Timestamp('2026-08-31')), 'TODAS','TODOS')
'''.replace('SECTION', repr(section))).run(timeout=30)
            self.assertEqual(len(app.exception), 0, str(app.exception))
            for table in app.table:
                self.assertNotIn('PRIVATE_', table.value.to_string())
                self.assertNotIn('SKU-1', table.value.to_string())


if __name__ == '__main__':
    unittest.main()
