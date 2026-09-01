from datetime import date
from pathlib import Path
import unittest

import pandas as pd

from config.settings import CONCILIATION_COLUMNS, recent_window_start
from src.analytics.metrics import funnel_metrics
from src.processing.cleaner import clean_conciliation
from src.processing.reconciler import apply_business_rules, combine_general_and_recent, merge_master


def raw_row(order: str, when: str, invoice: str = "", ac: int = 0) -> dict:
    row = {column: "" for column in CONCILIATION_COLUMNS}
    row.update({"ID_Pedido_Ingresado": order, "SKU_Material_Ingresado": "SKU-1", "Fecha_Ingreso": when, "ID_Factura_Final": invoice, "Cantidad_Ingresada": 1, "Valor_Neto_Ingresado": 0, "TOTAL": 0, "Saldo_Total_Pedido": ac, "Tipo_Pedido": "PEDIDO BEES"})
    return row


class ConciliationContractsTest(unittest.TestCase):
    def test_recent_window_is_current_plus_two_prior_months(self):
        self.assertEqual(recent_window_start(date(2026, 9, 1)), date(2026, 7, 1))

    def test_partition_uses_recent_source_only_inside_window(self):
        general, _ = clean_conciliation(pd.DataFrame([raw_row("A", "30/06/2026"), raw_row("B", "01/07/2026")]), "GENERAL")
        recent, _ = clean_conciliation(pd.DataFrame([raw_row("C", "01/07/2026"), raw_row("D", "01/08/2026")]), "3M")
        result = combine_general_and_recent(general, recent, date(2026, 9, 1))
        self.assertEqual(result["ID_Pedido_Ingresado"].tolist(), ["A", "C", "D"])

    def test_empty_invoice_is_not_invoiced_and_ac_is_sum_of_lines(self):
        raw = pd.DataFrame([raw_row("A", "01/08/2026", "", 0), raw_row("B", "01/08/2026", "F-1", 10), raw_row("B", "01/08/2026", "F-1", 15)])
        frame, _ = clean_conciliation(raw, "3M")
        values = funnel_metrics(frame.assign(is_return=False))
        self.assertEqual(values["invoiced_orders"], 1)
        self.assertEqual(values["final_value"], 25)
        self.assertTrue(frame.loc[0, "is_promotional"])

    def test_business_status_and_missing_master_are_explicit(self):
        frame, _ = clean_conciliation(pd.DataFrame([raw_row("A", "01/08/2026", "", 20), raw_row("B", "01/08/2026", "F-1", 20)]), "3M")
        frame.loc[1, "Motivo_Devolucion"] = "Dif precio"
        master = pd.DataFrame([{"Material": "SKU-1", "Marca": "Marca", "Categoria Cuota": "Categoria"}])
        result = apply_business_rules(merge_master(frame, master), Path("config/return_reasons.json"))
        self.assertEqual(result.loc[0, "Estado_Conciliacion"], "NO_FACTURADO")
        self.assertEqual(result.loc[1, "Estado_Conciliacion"], "ENTREGADO_PARCIAL")
        self.assertEqual(result.loc[1, "Motivo_Devolucion_Categoria"], "FALLA_ADMINISTRATIVA")

    def test_duplicate_master_fails_instead_of_silently_deduplicating(self):
        frame, _ = clean_conciliation(pd.DataFrame([raw_row("A", "01/08/2026")]), "3M")
        master = pd.DataFrame([{"Material": "SKU-1", "Marca": "A", "Categoria Cuota": "X"}, {"Material": "SKU-1", "Marca": "B", "Categoria Cuota": "Y"}])
        with self.assertRaises(ValueError):
            merge_master(frame, master)


if __name__ == "__main__":
    unittest.main()
