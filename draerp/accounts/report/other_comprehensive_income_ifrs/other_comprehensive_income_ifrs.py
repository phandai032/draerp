# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
# Author: Nghĩa+Phát


from curses import keyname
import frappe
from frappe import _
from frappe.utils import flt

from draerp.accounts.report.other_comprehensive_income import (
	get_columns,
	get_data as get_data_main,
	get_period_list as get_period_list_test
)
from draerp.accounts.report.financial_statements import get_period_list

def execute(filters=None):
	period_list = get_period_list(filters.from_fiscal_year, filters.to_fiscal_year,
		filters.period_start_date, filters.period_end_date, filters.filter_based_on, filters.periodicity,
		company=filters.company)

	period_test=get_period_list_test(filters.from_fiscal_year, filters.to_fiscal_year,
		filters.period_start_date, filters.period_end_date, filters.filter_based_on, filters.periodicity,
		company=filters.company)
	data=[]
	dulieu = get_data_main(filters.company,filters.finance_book,period_test,period_list,filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True)
	data.extend(dulieu)

	columns = get_columns(filters.periodicity, period_test, filters.accumulated_values, filters.company)
	return columns, data, None, None, None
