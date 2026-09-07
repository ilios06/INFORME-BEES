import unittest
from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from test_contracts import raw_row
from src.processing.cleaner import clean_conciliation, parse_regional_number, parse_regional_series, fold_series
from src.processing.reconciler import merge_master, apply_business_rules
from src.analytics.public_dashboard import operational_frame
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

    def test_filters(self):
        result = select(layers(operational_frame(fixture())), '2026-08-01','2026-08-31', {'canal':['COSTEÑO']})
        self.assertTrue(result['cube'].empty)

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
