import unittest
from app.money import format_cents

class MoneyTests(unittest.TestCase):
    def test_exact_display_of_integer_cents(self):
        for cents,expected in [(0,'0.00'),(1,'0.01'),(10,'0.10'),(101,'1.01'),(-1,'-0.01'),(9007199254740991,'90071992547409.91')]:
            self.assertEqual(format_cents(cents),expected)
    def test_rejects_values_that_would_require_rounding_or_coercion(self):
        for value in [True,1.1,'100',None]:
            with self.assertRaises(TypeError):format_cents(value)
