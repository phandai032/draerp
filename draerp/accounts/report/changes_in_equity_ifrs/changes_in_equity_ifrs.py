# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
# Author: Nghĩa


from curses import keyname
import frappe
from frappe import _
from frappe.utils import flt

from draerp.accounts.report.changes_in_equity import (
	get_data,
	get_columns
)
from draerp.accounts.report.financial_statements import get_period_list
def execute(filters=None):
	period_list = get_period_list(filters.from_fiscal_year, filters.to_fiscal_year,
		filters.period_start_date, filters.period_end_date, filters.filter_based_on, filters.periodicity,
		company=filters.company)
	dulieu = get_data(filters.company,filters.from_fiscal_year,period_list,filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True)

	columns = get_columns()
	return columns, dulieu
