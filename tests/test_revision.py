import unittest

from revision import aprobar_revision, estado_aceptacion, validar_formato_revision


def revision(veredicto="APTO", hallazgos="- ninguno"):
    return validar_formato_revision(
        f"## Veredicto\n{veredicto}\n\n## Hallazgos\n{hallazgos}\n"
    )


class TestCompuertaAceptacion(unittest.TestCase):
    def test_revision_apta_no_equivale_a_merge_automatico(self):
        self.assertEqual(aprobar_revision(revision()), "aprobado")
        self.assertEqual(
            estado_aceptacion("pasa", "aprobado", True),
            "revision_aprobada_pendiente_decision_director",
        )

    def test_fallo_de_revision_bloquea_aceptacion(self):
        self.assertEqual(
            estado_aceptacion("pasa", "revision_error", True),
            "bloqueado_por_error_revision",
        )
        self.assertEqual(
            estado_aceptacion("pasa", "revision_formato_invalido", True),
            "bloqueado_por_error_revision",
        )

    def test_observaciones_bloquean_aceptacion(self):
        self.assertEqual(
            estado_aceptacion("pasa", "con_observaciones", True),
            "bloqueado_por_observaciones",
        )

    def test_resultado_tecnico_fallido_bloquea_antes_de_revisar(self):
        self.assertEqual(
            estado_aceptacion("falla_oraculo", "bloqueado_por_resultado_tecnico", True),
            "bloqueado_por_resultado_tecnico",
        )

    def test_sin_revisor_queda_pendiente_del_director(self):
        self.assertEqual(
            estado_aceptacion("pasa", "no_requerida", False),
            "pendiente_decision_director",
        )

    def test_salida_revision_malformada_no_se_aprueba(self):
        revision_malformada = validar_formato_revision("Terminé, todo bien.")
        self.assertFalse(revision_malformada["formato_valido"])
        self.assertEqual(aprobar_revision(revision_malformada), "revision_formato_invalido")
        self.assertEqual(
            estado_aceptacion("pasa", "revision_formato_invalido", True),
            "bloqueado_por_error_revision",
        )


if __name__ == "__main__":
    unittest.main()
