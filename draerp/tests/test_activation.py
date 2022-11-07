from frappe.tests.utils import FrappeTestCase

from draerp.utilities.activation import get_level


class TestActivation(FrappeTestCase):
	def test_activation(self):
		levels = get_level()
		self.assertTrue(levels)
