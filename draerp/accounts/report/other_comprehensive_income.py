# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import functools
import math
from pydoc import tempfilepager
import re
import tempfile
from webbrowser import get
import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, cstr, flt, formatdate, get_first_day, getdate, log
from draerp.accounts.report.financial_statements import get_data as get_data_test

from draerp.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from draerp.accounts.report.utils import convert_to_presentation_currency, get_currency
from draerp.accounts.utils import get_fiscal_year
from pymysql import NULL
from draerp.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
	get_net_profit_loss,
)


def get_period_list(from_fiscal_year, to_fiscal_year, period_start_date, period_end_date, filter_based_on, periodicity, accumulated_values=False,
	company=None, reset_period_on_fy_change=True, ignore_fiscal_year=False):
	"""Get a list of dict {"from_date": from_date, "to_date": to_date, "key": key, "label": label}
		Periodicity can be (Yearly, Quarterly, Monthly)"""

	if filter_based_on == 'Fiscal Year':
		fiscal_year = get_fiscal_year_data(from_fiscal_year, to_fiscal_year)
		validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year)
		year_start_date = getdate(fiscal_year.year_start_date)
		year_end_date = getdate(fiscal_year.year_end_date)
	else:
		validate_dates(period_start_date, period_end_date)
		year_start_date = getdate(period_start_date)
		year_end_date = getdate(period_end_date)

	months_to_add = {
		"Yearly": 12,
		"Half-Yearly": 6,
		"Quarterly": 3,
		"Monthly": 1
	}[periodicity]

	period_list = []

	start_date = year_start_date
	months = get_months(year_start_date, year_end_date)

	for i in range(cint(math.ceil(months / months_to_add))):
		period = frappe._dict({
			"from_date": start_date
		})

		if i==0 and filter_based_on == 'Date Range':
			to_date = add_months(get_first_day(start_date), months_to_add)
		else:
			to_date = add_months(start_date, months_to_add)

		start_date = to_date

		# Subtract one day from to_date, as it may be first day in next fiscal year or month
		to_date = add_days(to_date, -1)

		if to_date <= year_end_date:
			# the normal case
			period.to_date = to_date
		else:
			# if a fiscal year ends before a 12 month period
			period.to_date = year_end_date

		# if not ignore_fiscal_year:
		# 	period.to_date_fiscal_year = get_fiscal_year(period.to_date, company=company)[0]
		# 	period.from_date_fiscal_year_start_date = get_fiscal_year(period.from_date, company=company)[1]

		period_list.append(period)

		if period.to_date == year_end_date:
			break

	# common processing
	for opts in period_list:
		key = opts["to_date"].strftime("%b_%Y").lower()
		if periodicity == "Monthly" and not accumulated_values:
			label = formatdate(opts["to_date"], "MMM YYYY")
		else:
			if not accumulated_values:
				label = get_label(periodicity, opts["from_date"], opts["to_date"])
			else:
				if reset_period_on_fy_change:
					label = get_label(periodicity, opts.from_date_fiscal_year_start_date, opts["to_date"])
				else:
					label = get_label(periodicity, period_list[0].from_date, opts["to_date"])

		opts.update({
			"key": key.replace(" ", "_").replace("-", "_"),
			"label": label,
			"year_start_date": year_start_date,
			"year_end_date": year_end_date,
			"periodicity": periodicity
		})

	return period_list


def get_fiscal_year_data(from_fiscal_year, to_fiscal_year):
	fiscal_year = frappe.db.sql("""select min(year_start_date) as year_start_date,
		max(year_end_date) as year_end_date from `tabFiscal Year` where
		name between %(from_fiscal_year)s and %(to_fiscal_year)s""",
		{'from_fiscal_year': from_fiscal_year, 'to_fiscal_year': to_fiscal_year}, as_dict=1)

	return fiscal_year[0] if fiscal_year else {}


def validate_fiscal_year(fiscal_year, from_fiscal_year, to_fiscal_year):
	if not fiscal_year.get('year_start_date') or not fiscal_year.get('year_end_date'):
		frappe.throw(_("Start Year and End Year are mandatory"))

	if getdate(fiscal_year.get('year_end_date')) < getdate(fiscal_year.get('year_start_date')):
		frappe.throw(_("End Year cannot be before Start Year"))

def validate_dates(from_date, to_date):
	if not from_date or not to_date:
		frappe.throw(_("From Date and To Date are mandatory"))

	if to_date < from_date:
		frappe.throw(_("To Date cannot be less than From Date"))

def get_months(start_date, end_date):
	diff = (12 * end_date.year + end_date.month) - (12 * start_date.year + start_date.month)
	return diff + 1


def get_label(periodicity, from_date, to_date):
	if periodicity == "Yearly":
		if formatdate(from_date, "YYYY") == formatdate(to_date, "YYYY"):
			label = formatdate(from_date, "YYYY")
		else:
			label = formatdate(from_date, "YYYY") + "-" + formatdate(to_date, "YYYY")
	else:
		label = formatdate(from_date, "MMM YY") + "-" + formatdate(to_date, "MMM YY")

	return label


def get_data(
		company,finance_book,period_list,period,filters,
		accumulated_values=1, only_current_fiscal_year=True, ignore_closing_entries=False,
		ignore_accumulated_values_for_fy=False , total = True):


	income = get_data_test(filters.company, "Income", "Credit", period, filters = filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True)

	
	expense = get_data_test(filters.company, "Expense", "Debit", period, filters=filters,
		accumulated_values=filters.accumulated_values,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True)
	
	net_profit_loss=get_net_profit_loss(income, expense, period, filters.company, filters.presentation_currency)
	drop_table()
	create_table()
	accounts = get_dulieu()
	if not accounts:
		
		insert_data()
		accounts=get_dulieu()
	out = prepare_data(accounts, period_list,company,finance_book,net_profit_loss)
	return out
def insert_data():
	return frappe.db.sql("""
		INSERT INTO `tabOther Comprehensive Income IFRS` (`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`, `chitieu`, `_user_tags`, `_comments`, `_assign`, `_liked_by`, `chi_tieu`) VALUES
		('OCI00001', '2022-09-01 11:20:46.406745', '2022-09-01 11:20:46.406745', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Lợi nhuận trong năm'),
		('OCI00002', '2022-09-01 11:20:57.256715', '2022-09-01 11:20:57.256715', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Các khoản thu nhập toàn diện khác'),
		('OCI00003', '2022-09-01 11:21:08.090679', '2022-09-01 11:21:08.090679', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Các chỉ tiêu sẽ không được phân loại lại sang báo cáo lãi hoặc lỗ'),
		('OCI00004', '2022-09-01 11:21:15.459516', '2022-09-01 11:21:15.459516', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Thặng dự đánh giá lại tài sản'),
		('OCI00005', '2022-09-01 11:21:26.417501', '2022-10-04 14:32:19.428758', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Tăng/giảm đánh giá lại quỹ phúc lợi với mức phúc lợi xác định'),
		('OCI00006', '2022-09-01 11:21:50.500247', '2022-10-04 14:32:50.318935', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ vốn được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện'),
		('OCI00007', '2022-09-01 11:22:16.482843', '2022-10-04 14:33:53.863700', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Tăng/giảm giá trị hợp lý đối với các khoản nợ tài chính được ghi nhận thông qua báo cáo kết quả kinh doanh'),
		('OCI00008', '2022-09-01 11:22:27.054626', '2022-10-04 14:34:25.862031', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Các chỉ tiêu sẽ được phân loại lại sang báo cáo lãi hoặc lỗ'),
		('OCI00009', '2022-09-01 11:22:36.615504', '2022-10-04 14:34:38.835891', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Chênh lệch tỷ giá hối đoái trong chuyển đổi'),
		('OCI00010', '2022-09-01 11:22:45.243316', '2022-10-04 14:35:40.077262', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ nợ được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện'),
		('OCI00011', '2022-09-01 11:22:58.171139', '2022-10-04 14:36:18.580172', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Dữ trự rủi ro dòng tiền và các điều chỉnh liên quan'),
		('OCI00012', '2022-09-01 11:23:10.710701', '2022-10-04 15:23:20.842529', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Các khoản thu nhập toàn diện trong năm'),
		('OCI00013', '2022-09-01 11:23:25.215732', '2022-10-04 14:38:00.708366', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Tổng các thu nhập toàn diện phân bổ cho:'),
		('OCI00014', '2022-09-01 11:23:33.307982', '2022-10-04 14:38:10.972633', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Chủ sở hữu của công ty mẹ'),
		('OCI00015', '2022-09-01 11:23:39.437247', '2022-10-04 14:38:27.348934', 'Administrator', 'Administrator', 0, 0, NULL, NULL, NULL, NULL, NULL, 'Lợi ích của cổ đông không kiểm soát');
	""")
def drop_table():
	return frappe.db.sql("""
		DROP TABLE IF EXISTS `tabOther Comprehensive Income IFRS`;
	""")
def create_table():
	return frappe.db.sql("""
		CREATE TABLE IF NOT EXISTS `tabOther Comprehensive Income IFRS` (
			`name` varchar(140) COLLATE utf8mb4_unicode_ci NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`owner` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`chitieu` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_user_tags` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_comments` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_assign` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_liked_by` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`chi_tieu` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `modified` (`modified`)
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC;
	""")
def prepare_data(accounts, period_list,company,finance_book,net_profit_loss):
	data = []

	for d in accounts:
		# add to output
		has_value = False
		total = 0
		row = frappe._dict({
			"chi_tieu": d.chi_tieu
		})
		if (d.chi_tieu=='Tổng các thu nhập toàn diện phân bổ cho:'):

			for period in period_list:
				
				row[period.key] = ""
				
			data.append(row)
		else:
		
			for period in period_list:
				if d.chi_tieu=='Lợi nhuận trong năm':
					try:
						row[period.key] = net_profit_loss[period.key]
					except:
						row[period.key] = 0
				else:
					try:
						row[period.key] = get_giatri(period,d.chi_tieu,period.periodicity,company,finance_book,net_profit_loss[period.key])
					except:
						row[period.key] = 0
				total += row[period.key]


			row["total"] = total
			data.append(row)

	return data

def get_dulieu():
	return frappe.db.sql("""
		select chi_tieu
		from `tabOther Comprehensive Income IFRS`
		""",as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chỉ Tiêu",
		"fieldtype": "Data",
		"options": "Other Comprehensive Income IFRS",
		"width": 600
	}]

	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 200
		})
	# if periodicity!="Yearly":
	# 	if not accumulated_values:
	# 		columns.append({
	# 			"fieldname": "total",
	# 			"label": _("Total"),
	# 			"fieldtype": "Currency",
	# 			"width": 200
	# 		})

	return columns

def get_giatri(nam,chitieu,periodicity,company,finance_book,du_lieu_ma2):
	if periodicity=="Yearly":		

		nam=nam.label

		if chitieu=='Các khoản thu nhập toàn diện khác':
			return (
				(
				layGiaTriCredit(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company,finance_book) - layGiaTriCredit(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCredit(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCredit(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1002%',company,finance_book)
				)
			)


		elif chitieu=='Các chỉ tiêu sẽ không được phân loại lại sang báo cáo lãi hoặc lỗ':
			return (
				layGiaTriCredit(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company,finance_book) - layGiaTriCredit(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCredit(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company,finance_book))

			)


		elif chitieu=='Thặng dự đánh giá lại tài sản':
			return layGiaTriCredit(nam,'3.3.1005%',company,finance_book)
		elif chitieu=='Tăng/giảm đánh giá lại quỹ phúc lợi với mức phúc lợi xác định':
			return layGiaTriSumDeBit(nam,'3.3.1004%',company,finance_book) - layGiaTriCredit(nam,'3.3.1004%',company,finance_book)
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ vốn được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện':
			return (layGiaTriCredit(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company,finance_book))
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản nợ tài chính được ghi nhận thông qua báo cáo kết quả kinh doanh':
			return (layGiaTriCredit(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company,finance_book))


		elif chitieu=='Các chỉ tiêu sẽ được phân loại lại sang báo cáo lãi hoặc lỗ':
			return (
				layGiaTriCredit(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCredit(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1002%',company,finance_book)
			)


		elif chitieu=='Chênh lệch tỷ giá hối đoái trong chuyển đổi':
			return layGiaTriCredit(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1001%',company,finance_book)
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ nợ được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện':
			return (layGiaTriCredit(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company,finance_book))
		elif chitieu=='Dữ trự rủi ro dòng tiền và các điều chỉnh liên quan':
			return layGiaTriCredit(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1002%',company,finance_book)
		

		elif chitieu=='Các khoản thu nhập toàn diện trong năm':
			return (
				du_lieu_ma2
				+
				(
				layGiaTriCredit(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company,finance_book) - layGiaTriCredit(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCredit(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCredit(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1002%',company,finance_book)
				)
				
			)
	

		



		elif chitieu=='Chủ sở hữu của công ty mẹ':
			return (
				(
				du_lieu_ma2
				+
				(
				layGiaTriCredit(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company,finance_book) - layGiaTriCredit(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCredit(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCredit(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBit(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCredit(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'3.3.1002%',company,finance_book)
				)
				
				)
				-layGiaTriCredit(nam,'3.6%',company,finance_book)
			)
		elif chitieu=='Lợi ích của cổ đông không kiểm soát':
			return (
				layGiaTriCredit(nam,'3.6%',company,finance_book)
			)	
	# Niên độ
	else:	
		if chitieu=='Các khoản thu nhập toàn diện khác':
			return (
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'3.3.1004%',company,finance_book) - layGiaTriCreditKhacYearly(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCreditKhacYearly(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCreditKhacYearly(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1002%',company,finance_book)
				)
			)


		elif chitieu=='Các chỉ tiêu sẽ không được phân loại lại sang báo cáo lãi hoặc lỗ':
			return (
				layGiaTriCreditKhacYearly(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'3.3.1004%',company,finance_book) - layGiaTriCreditKhacYearly(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCreditKhacYearly(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1007%',company,finance_book))

			)


		elif chitieu=='Thặng dự đánh giá lại tài sản':
			return layGiaTriCreditKhacYearly(nam,'3.3.1005%',company,finance_book)
		elif chitieu=='Tăng/giảm đánh giá lại quỹ phúc lợi với mức phúc lợi xác định':
			return layGiaTriSumDeBitKhacYearly(nam,'3.3.1004%',company,finance_book) - layGiaTriCreditKhacYearly(nam,'3.3.1004%',company,finance_book)
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ vốn được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện':
			return (layGiaTriCreditKhacYearly(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1006%',company,finance_book))
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản nợ tài chính được ghi nhận thông qua báo cáo kết quả kinh doanh':
			return (layGiaTriCreditKhacYearly(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1007%',company,finance_book))


		elif chitieu=='Các chỉ tiêu sẽ được phân loại lại sang báo cáo lãi hoặc lỗ':
			return (
				layGiaTriCreditKhacYearly(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCreditKhacYearly(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1002%',company,finance_book)
			)


		elif chitieu=='Chênh lệch tỷ giá hối đoái trong chuyển đổi':
			return layGiaTriCreditKhacYearly(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1001%',company,finance_book)
		elif chitieu=='Tăng/giảm giá trị hợp lý đối với các khoản đầu tư vào công cụ nợ được ghi nhận thông qua báo cáo các khoản thu nhập toàn diện':
			return (layGiaTriCreditKhacYearly(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1003%',company,finance_book))
		elif chitieu=='Dữ trự rủi ro dòng tiền và các điều chỉnh liên quan':
			return layGiaTriCreditKhacYearly(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1002%',company,finance_book)
		

		elif chitieu=='Các khoản thu nhập toàn diện trong năm':
			return (
				du_lieu_ma2
				+
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'3.3.1004%',company,finance_book) - layGiaTriCreditKhacYearly(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCreditKhacYearly(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCreditKhacYearly(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1002%',company,finance_book)
				)
			)
	

		



		elif chitieu=='Chủ sở hữu của công ty mẹ':
			return (
				(
				du_lieu_ma2
				+
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1005%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'3.3.1004%',company,finance_book) - layGiaTriCreditKhacYearly(nam,'3.3.1004%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1006%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1006%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1006%',company,finance_book))
				+(layGiaTriCreditKhacYearly(nam,'3.3.1007%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1007%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1007%',company,finance_book))

				)
				+
				(
				layGiaTriCreditKhacYearly(nam,'3.3.1001%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1001%',company,finance_book)
				+(layGiaTriCreditKhacYearly(nam,'3.3.1003%',company,finance_book)-(layGiaTriSumDeBitKhacYearly(nam,'3.3.1003%',company,finance_book))-layGiaTriOpeningCreDitKhacYearly(nam,'3.3.1003%',company,finance_book))
				+layGiaTriCreditKhacYearly(nam,'3.3.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'3.3.1002%',company,finance_book)
				)
				)
				-layGiaTriCreditKhacYearly(nam,'3.6%',company,finance_book)
			)
		elif chitieu=='Lợi ích của cổ đông không kiểm soát':
			return (
				layGiaTriCreditKhacYearly(nam,'3.6%',company,finance_book)
			)	
		

def layGiaTriSumDeBitCoAgainst(nam,account,against,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"against":against,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
	from `tabGL Entry`
	where
		company=%(company)s
		and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and against LIKE %(against)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriSumCreditCoAgainst(nam,account,against,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"against":against,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
	from `tabGL Entry`
	where
		company=%(company)s
		and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and against LIKE %(against)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriSumDeBit(nam,account,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
	from `tabGL Entry`
	where
		company=%(company)s
		and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriCredit(nam,account,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
	from `tabGL Entry`
	where
		company=%(company)s
		and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriOpeningDeBit(nam,account,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
		from `tabGL Entry`
		where
			company=%(company)s
			and (fiscal_year <= %(nam)s) and ifnull(is_opening, 'No') = 'Yes'
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))
			
def layGiaTriOpeningCreDit(nam,account,company,finance_book):

	test={
		"nam":nam,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
		from `tabGL Entry`
		where
			company=%(company)s
			and (fiscal_year <= %(nam)s) and ifnull(is_opening, 'No') = 'Yes'
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))

# Niên độ

def layGiaTriSumDeBitCoAgainstKhacYearly(nam,account,against,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"against":against,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
	from `tabGL Entry`
	where
		company=%(company)s
		and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and against LIKE %(against)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriSumCreditCoAgainstKhacYearly(nam,account,against,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"against":against,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
	from `tabGL Entry`
	where
		company=%(company)s
		and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and against LIKE %(against)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriSumDeBitKhacYearly(nam,account,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
	from `tabGL Entry`
	where
		company=%(company)s
		and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriCreditKhacYearly(nam,account,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
	from `tabGL Entry`
	where
		company=%(company)s
		and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'No'
		and account LIKE %(account)s
		and is_cancelled = 0
		""",test,as_list=True)[0][0],2))

def layGiaTriOpeningDeBitKhacYearly(nam,account,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(debit)
		from `tabGL Entry`
		where
			company=%(company)s
			and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'Yes'
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))
			
def layGiaTriOpeningCreDitKhacYearly(nam,account,company,finance_book):

	test={
		"from_date":nam.from_date,
		"to_date":nam.to_date,
		"account":account,
		"company":company,
		"finance_book":finance_book
	}
	return(flt(frappe.db.sql("""
		select
			sum(credit)
		from `tabGL Entry`
		where
			company=%(company)s
			and posting_date>=%(from_date)s and posting_date<=%(to_date)s and ifnull(is_opening, 'No') = 'Yes'
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))