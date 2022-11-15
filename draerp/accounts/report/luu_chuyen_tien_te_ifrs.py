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
from draerp.controllers.queries import get_fields

def lay_DS_Company():
	return frappe.db.sql("""
		select company_name,create_chart_of_accounts_based_on,existing_company,chart_of_accounts
		from `tabCompany`
		""",as_dict=True)
def lay_Parent_Company(company):
	test={
		"company":company
	}
	return frappe.db.sql("""
		select company_name,existing_company,chart_of_accounts
		from `tabCompany` where company_name=%(company)s
		""",test,as_dict=True)[0]
	
		
# Code xử lý query
@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def company_query(doctype, txt, searchfield, start, page_len, filters):

	fields = ["company_name"]
	list_IFRS=[]
	temp=[]
	list_Existing=[]
	fields = get_fields("Company", fields)
	
	for i in lay_DS_Company():
		if i.chart_of_accounts=='Standard with IFRS':
			list_IFRS.append(i.company_name)
		if i.create_chart_of_accounts_based_on=='Existing Company':
			temp.append(i.company_name)
	
	list="'"
	for i in list_IFRS:
		if i==list_IFRS[0]:
			list=list+""+i+"'"
		else:
			list=list+",'"+i+"'"

	for i in temp:
		j=i
		while lay_Parent_Company(j).existing_company:
			k=lay_Parent_Company(j).existing_company
			if lay_Parent_Company(k).chart_of_accounts=='Standard with IFRS':
				check=0
				for l in list_Existing:
					if l==lay_Parent_Company(j).company_name:
						check=1
						break
				if check==0:
					list_Existing.append(lay_Parent_Company(j).company_name)
			j=k

			
	for i in list_Existing:
		if i==list_Existing[0] and len(list_IFRS)==0:
			list=list+""+i+"'"
		else:
			list=list+",'"+i+"'"

	searchfields = frappe.get_meta("Company").get_search_fields()
	searchfields = " or ".join(field + " like %(txt)s" for field in searchfields)

	if len(list_IFRS)>0:
		return frappe.db.sql("""select {fields} from `tabCompany`
			where company_name in ({l}) and ({scond})

			limit %(start)s, %(page_len)s""".format(**{
				"fields": ", ".join(fields),
				"scond": searchfields,
				"l":list,
			}), {
				'txt': "%%%s%%" % txt,
				'_txt': txt.replace("%", ""),
				'start': start,
				'page_len': page_len
			})
	else:
		frappe.throw('Không tìm thấy công ty nào theo bộ tài khoản IFRS')	


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
		INSERT INTO `tabBang Luu Chuyen Tien Te IFRS` (`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`, `chi_tieu`, `_user_tags`, `_comments`, `_assign`, `_liked_by`) VALUES
	('IFRS00001', '2022-08-25 15:38:32.999990', '2022-08-25 15:38:32.999990', 'Administrator', 'Administrator', 0, 0, 'Hoạt động kinh doanh', NULL, NULL, NULL, NULL),
	('IFRS00002', '2022-08-25 15:38:49.076171', '2022-08-25 15:38:49.076171', 'Administrator', 'Administrator', 0, 0, 'Lợi nhuận trong năm', NULL, NULL, NULL, NULL),
	('IFRS00003', '2022-08-25 15:39:00.266128', '2022-08-25 15:39:00.266128', 'Administrator', 'Administrator', 0, 0, 'Các khoản điều chỉnh', NULL, NULL, NULL, NULL),
	('IFRS00004', '2022-08-25 15:39:20.379560', '2022-08-25 15:39:28.832067', 'Administrator', 'Administrator', 0, 0, 'Chi phí khấu hao tài sản hữu hình', NULL, NULL, NULL, NULL),
	('IFRS00005', '2022-08-25 15:39:44.661093', '2022-08-25 15:39:44.661093', 'Administrator', 'Administrator', 0, 0, 'Chi phí khấu hao tài sản vô hình', NULL, NULL, NULL, NULL),
	('IFRS00006', '2022-08-25 15:40:21.896795', '2022-08-25 15:40:21.896795', 'Administrator', 'Administrator', 0, 0, 'Lãi thanh lý tài sản cố định', NULL, NULL, NULL, NULL),
	('IFRS00007', '2022-08-25 15:40:43.018215', '2022-08-25 15:40:43.018215', 'Administrator', 'Administrator', 0, 0, 'Lỗ thanh lý tài sản cố định', NULL, NULL, NULL, NULL),
	('IFRS00008', '2022-08-25 15:40:44.334937', '2022-08-25 15:40:44.334944', 'Administrator', 'Administrator', 0, 0, 'Doanh thu tài chính', NULL, NULL, NULL, NULL),
	('IFRS00009', '2022-08-25 15:40:54.158428', '2022-08-25 15:40:54.158428', 'Administrator', 'Administrator', 0, 0, 'Chi phí tài chính', NULL, NULL, NULL, NULL),
	('IFRS00010', '2022-08-25 15:41:13.941297', '2022-08-25 15:41:13.941297', 'Administrator', 'Administrator', 0, 0, 'Chi phí thuế thu nhập', NULL, NULL, NULL, NULL),
	('IFRS00011', '2022-08-25 15:41:13.941300', '2022-08-25 15:41:13.941300', 'Administrator', 'Administrator', 0, 0, 'Chi phí phúc lợi sau nghỉ việc', NULL, NULL, NULL, NULL),
	('IFRS00012', '2022-08-25 15:41:22.233938', '2022-08-25 15:41:22.233938', 'Administrator', 'Administrator', 0, 0, 'Thay đổi phát sinh từ hoạt động kinh doanh', NULL, NULL, NULL, NULL),
	('IFRS00013', '2022-08-25 15:41:30.196238', '2022-08-25 15:41:30.196238', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm các khoản phải thu', NULL, NULL, NULL, NULL),
	('IFRS00014', '2022-08-25 15:41:38.309041', '2022-08-25 15:41:38.309041', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm các khoản phải thu khác', NULL, NULL, NULL, NULL),
	('IFRS00015', '2022-08-25 15:41:47.767439', '2022-08-25 15:41:47.767439', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm dự phòng', NULL, NULL, NULL, NULL),
	('IFRS00016', '2022-08-25 15:41:54.530784', '2022-08-25 15:41:54.530784', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm hàng tồn kho', NULL, NULL, NULL, NULL),
	('IFRS00017', '2022-08-25 15:42:01.848261', '2022-08-25 15:42:01.848261', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm chi phí trả trước', NULL, NULL, NULL, NULL),
	('IFRS00018', '2022-08-25 15:42:08.694517', '2022-08-25 15:42:08.694517', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm các khoản phải trả', NULL, NULL, NULL, NULL),
	('IFRS00019', '2022-08-25 15:42:15.027316', '2022-08-25 15:42:15.027316', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm chi phí dồn tích', NULL, NULL, NULL, NULL),
	('IFRS00020', '2022-08-25 15:42:15.027320', '2022-08-25 15:42:15.027320', 'Administrator', 'Administrator', 0, 0, 'Đóng góp vào quỹ phúc lợi sau nghỉ việc', NULL, NULL, NULL, NULL),
	('IFRS00021', '2022-08-25 15:42:35.021582', '2022-08-25 15:42:35.021582', 'Administrator', 'Administrator', 0, 0, 'Tiền hình thành từ hoạt động kinh doanh', NULL, NULL, NULL, NULL),
	('IFRS00022', '2022-08-25 15:43:27.741325', '2022-08-25 15:43:27.741325', 'Administrator', 'Administrator', 0, 0, 'Tiền lãi đã trả', NULL, NULL, NULL, NULL),
	('IFRS00023', '2022-08-25 15:43:36.618345', '2022-08-25 15:43:36.618345', 'Administrator', 'Administrator', 0, 0, 'Tiền lãi đã nhận', NULL, NULL, NULL, NULL),
	('IFRS00024', '2022-08-25 15:43:44.894781', '2022-08-25 15:43:44.894781', 'Administrator', 'Administrator', 0, 0, 'Cổ tức đã trả', NULL, NULL, NULL, NULL),
	('IFRS00025', '2022-08-25 15:43:51.894823', '2022-08-25 15:43:51.894823', 'Administrator', 'Administrator', 0, 0, 'Thuế thu nhập đã trả', NULL, NULL, NULL, NULL),
	('IFRS00026', '2022-08-25 15:43:59.530863', '2022-08-25 15:43:59.530863', 'Administrator', 'Administrator', 0, 0, 'Tiền ròng từ hoạt động kinh doanh', NULL, NULL, NULL, NULL),
	('IFRS00027', '2022-08-25 15:44:06.758473', '2022-08-25 15:44:06.758473', 'Administrator', 'Administrator', 0, 0, 'Hoạt động đầu tư', NULL, NULL, NULL, NULL),
	('IFRS00028', '2022-08-25 15:44:14.190679', '2022-08-25 15:44:14.190679', 'Administrator', 'Administrator', 0, 0, 'Mua sắm tài sản cố định', NULL, NULL, NULL, NULL),
	('IFRS00029', '2022-08-25 15:44:20.566669', '2022-08-25 15:44:20.566669', 'Administrator', 'Administrator', 0, 0, 'Bán tài sản cố định', NULL, NULL, NULL, NULL),
	('IFRS00030', '2022-08-25 15:44:26.932535', '2022-08-25 15:44:26.932535', 'Administrator', 'Administrator', 0, 0, 'Cổ tức nhận được từ công ty liên doanh. liên kết', NULL, NULL, NULL, NULL),
	('IFRS00031', '2022-08-25 15:44:33.744541', '2022-08-25 15:44:33.744541', 'Administrator', 'Administrator', 0, 0, 'Các khoản cho vay', NULL, NULL, NULL, NULL),
	('IFRS00032', '2022-08-25 15:44:42.413712', '2022-08-25 15:44:42.413712', 'Administrator', 'Administrator', 0, 0, 'Thu được từ cho vay', NULL, NULL, NULL, NULL),
	('IFRS00033', '2022-08-25 15:44:48.060899', '2022-08-25 15:44:48.060899', 'Administrator', 'Administrator', 0, 0, 'Mua các công cụ tài chính', NULL, NULL, NULL, NULL),
	('IFRS00034', '2022-08-25 15:44:53.309836', '2022-08-25 15:44:53.309836', 'Administrator', 'Administrator', 0, 0, 'Bán các công cụ tài chính', NULL, NULL, NULL, NULL),
	('IFRS00035', '2022-08-25 15:44:58.658087', '2022-08-25 15:44:58.658087', 'Administrator', 'Administrator', 0, 0, 'Dòng tiền thuần từ hoạt động đầu tư', NULL, NULL, NULL, NULL),
	('IFRS00036', '2022-08-25 15:45:04.615771', '2022-08-25 15:45:04.615771', 'Administrator', 'Administrator', 0, 0, 'Hoạt động tài chính', NULL, NULL, NULL, NULL),
	('IFRS00037', '2022-08-25 15:45:10.633525', '2022-08-25 15:45:10.633525', 'Administrator', 'Administrator', 0, 0, 'Tiền thu được khi phát hành cổ phiếu', NULL, NULL, NULL, NULL),
	('IFRS00038', '2022-08-25 15:45:20.187658', '2022-08-25 15:45:20.187658', 'Administrator', 'Administrator', 0, 0, 'Tiền trả nợ gốc vay', NULL, NULL, NULL, NULL),
	('IFRS00039', '2022-08-25 15:45:25.670724', '2022-08-25 15:45:25.670724', 'Administrator', 'Administrator', 0, 0, 'Tiền thu từ đi vay', NULL, NULL, NULL, NULL),
	('IFRS00040', '2022-08-25 15:45:32.814785', '2022-08-25 15:45:32.814785', 'Administrator', 'Administrator', 0, 0, 'Tiền thu được khi phát hành trái phiếu', NULL, NULL, NULL, NULL),
	('IFRS00041', '2022-08-25 15:45:32.814786', '2022-08-25 15:45:32.814786', 'Administrator', 'Administrator', 0, 0, 'Thanh toán mệnh giá trái phiếu', NULL, NULL, NULL, NULL),
	('IFRS00042', '2022-08-25 15:45:32.814787', '2022-08-25 15:45:32.814787', 'Administrator', 'Administrator', 0, 0, 'Tiền mua cổ phiếu quỹ', NULL, NULL, NULL, NULL),
	('IFRS00043', '2022-08-25 15:45:38.389646', '2022-08-25 15:45:38.389646', 'Administrator', 'Administrator', 0, 0, 'Tiền nhận từ thương phiếu phải trả', NULL, NULL, NULL, NULL),
	('IFRS00044', '2022-08-25 15:45:43.663965', '2022-08-25 15:45:43.663965', 'Administrator', 'Administrator', 0, 0, 'Tiền trả cho thương phiếu phải trả', NULL, NULL, NULL, NULL),
	('IFRS00045', '2022-08-25 15:45:59.317700', '2022-08-25 15:45:59.317700', 'Administrator', 'Administrator', 0, 0, 'Tiền thuần từ hoạt động tài chính', NULL, NULL, NULL, NULL),
	('IFRS00046', '2022-08-25 15:46:05.596470', '2022-08-25 15:46:05.596470', 'Administrator', 'Administrator', 0, 0, 'Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng dương)', NULL, NULL, NULL, NULL),
	('IFRS00047', '2022-08-25 15:46:13.844405', '2022-08-25 15:46:13.844405', 'Administrator', 'Administrator', 0, 0, 'Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng âm)', NULL, NULL, NULL, NULL),
	('IFRS00048', '2022-08-25 15:46:19.749168', '2022-08-25 15:46:19.749168', 'Administrator', 'Administrator', 0, 0, 'Tăng/giảm tiền và tương đương tiền', NULL, NULL, NULL, NULL),
	('IFRS00049', '2022-08-25 15:46:30.554835', '2022-08-25 15:46:30.554835', 'Administrator', 'Administrator', 0, 0, 'Tiền và tương đương tiền đầu năm', NULL, NULL, NULL, NULL),
	('IFRS00050', '2022-08-25 15:46:36.354577', '2022-08-25 15:46:36.354577', 'Administrator', 'Administrator', 0, 0, 'Tiền và tương đương tiền cuối năm', NULL, NULL, NULL, NULL);
""")
def drop_table():
	return frappe.db.sql("""
		DROP TABLE IF EXISTS `tabBang Luu Chuyen Tien Te IFRS`;
	""")
def create_table():
	return frappe.db.sql("""
		CREATE TABLE IF NOT EXISTS `tabBang Luu Chuyen Tien Te IFRS` (
			`name` varchar(140) COLLATE utf8mb4_unicode_ci NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`owner` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`chi_tieu` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_user_tags` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_comments` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_assign` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_liked_by` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
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
		if (d.chi_tieu=='Hoạt động kinh doanh' or d.chi_tieu=='Hoạt động đầu tư' or
			d.chi_tieu=='Hoạt động tài chính'):

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
		from `tabBang Luu Chuyen Tien Te IFRS`
		""",as_dict=True)

def get_columns(periodicity, period_list, accumulated_values=1, company=None):
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chỉ Tiêu",
		"fieldtype": "Data",
		"options": "Bang Luu Chuyen Tien Te IFRS",
		"width": 435
	}]

	for period in period_list:
		columns.append({
			"fieldname": period.key,
			"label": period.label,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 200
		})
	if periodicity!="Yearly":
		if not accumulated_values:
			columns.append({
				"fieldname": "total",
				"label": _("Total"),
				"fieldtype": "Currency",
				"width": 200
			})

	return columns

def get_giatri(nam,chitieu,periodicity,company,finance_book,du_lieu_ma2):
	if periodicity=="Yearly":		

		nam=nam.label
		if chitieu=='Các khoản điều chỉnh':
			return (
				layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
				-layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
				-layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)
			)



		elif chitieu=='Chi phí khấu hao tài sản hữu hình':
			return layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
		elif chitieu=='Chi phí khấu hao tài sản vô hình':
			return layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
		elif chitieu=='Doanh thu tài chính':
			return -layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
		elif chitieu=='Lãi thanh lý tài sản cố định':
			return -layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
		elif chitieu=='Lỗ thanh lý tài sản cố định':
			return layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
		elif chitieu=='Chi phí tài chính':
			return layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
		elif chitieu=='Chi phí thuế thu nhập':
			return layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
		elif chitieu=='Chi phí phúc lợi sau nghỉ việc':
			return layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)

		####

		elif chitieu=='Thay đổi phát sinh từ hoạt động kinh doanh':
			return (
				((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
					)
				)
				+(
					(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
					+layGiaTriCredit(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
				)
				+(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
					- layGiaTriCredit(nam,'1.3%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
					)
				)
				+(
					(
						(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
					
				)
				+(
					layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainst(nam,'4.4.1005%','1.1%',company,finance_book)
			)
		)

		####


		elif chitieu=='Tăng/giảm các khoản phải thu':
			return ((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm các khoản phải thu khác':
			return (layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm dự phòng':
			return (
					(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
					+layGiaTriCredit(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
			)
		elif chitieu=='Tăng/giảm hàng tồn kho':
			return (layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
					- layGiaTriCredit(nam,'1.3%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm chi phí trả trước':
			return (layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm các khoản phải trả':
			return (
				(
					(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
					+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
					-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
				)
				-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
			)
		elif chitieu=='Tăng/giảm chi phí dồn tích':
			return (
				(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
				+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
				-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
				
			)
		elif chitieu=='Đóng góp vào quỹ phúc lợi sau nghỉ việc':
			return (
					layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainst(nam,'4.4.1005%','1.1%',company,finance_book)
			)

		##########
		
		elif chitieu=='Tiền hình thành từ hoạt động kinh doanh':
			return (
				du_lieu_ma2
				+
				(
				layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
				-layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
				-layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
				+layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)
				)
				+
				(
				((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
					)
				)
				+(
					(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
					+layGiaTriCredit(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
				)
				+(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
					- layGiaTriCredit(nam,'1.3%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
					)
				)
				+(
					(
						(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
					
				)
				+(
					layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainst(nam,'4.4.1005%','1.1%',company,finance_book)
			)
		)
	)
		
		#############

		elif chitieu=='Tiền lãi đã trả':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.1.1003%','1.1%',company,finance_book)
		elif chitieu=='Tiền lãi đã nhận':
			return layGiaTriSumCreditCoAgainst(nam,'1.2.1004.1%','1.1%',company,finance_book)
		elif chitieu=='Cổ tức đã trả':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.1.1002%','1.1%',company,finance_book)
		elif chitieu=='Thuế thu nhập đã trả':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.4.1004.2%','1.1%',company,finance_book)
		


		elif chitieu=='Tiền ròng từ hoạt động kinh doanh':
			return (
						(
						du_lieu_ma2
						+
						(
						layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
						+layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
						-layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
						-layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
						+layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
						+layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
						+layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
						+layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)
						)
						+
						(
						((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
							-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
							+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
							- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
							)
						)
						+(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
							-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
							+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
							- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
							)
						)
						+(
							(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
							+layGiaTriCredit(nam,'4.2%',company,finance_book)
							- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
							)
							-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
						)
						+(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
							-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
							+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
							- layGiaTriCredit(nam,'1.3%',company,finance_book)
							)
						)
						+(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
							-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
							+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
							-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
							)
						)
						+(
							(
								(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
								+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
								-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
							)
							-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
						)
						+(
							(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
							+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
							-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
							
						)
						+(
							layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
							+layGiaTriSumDeBitCoAgainst(nam,'4.4.1006%','1.1%',company,finance_book)
					)
				)
			)
			+
			-layGiaTriSumDeBitCoAgainst(nam,'4.1.1003%','1.1%',company,finance_book)
			+layGiaTriSumCreditCoAgainst(nam,'1.2.1004.1%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainst(nam,'4.1.1002%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainst(nam,'4.4.1004.2%','1.1%',company,finance_book)
		)

#############
		elif chitieu=='Mua sắm tài sản cố định':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.1.1001.2%','1.1%',company,finance_book)
		elif chitieu=='Bán tài sản cố định':
			return +layGiaTriSumCreditCoAgainst(nam,'1.2.1001.2%','1.1%',company,finance_book)
		elif chitieu=='Cổ tức nhận được từ công ty liên doanh. liên kết':
			return layGiaTriSumCreditCoAgainst(nam,'5.2.1002%','1.1%',company,finance_book)
		elif chitieu=='Các khoản cho vay':
			return -layGiaTriSumDeBitCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
		elif chitieu=='Thu được từ cho vay':
			return layGiaTriSumCreditCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
		elif chitieu=='Mua các công cụ tài chính':
			return -layGiaTriSumDeBitCoAgainst(nam,'1.4%','1.1%',company,finance_book)
		elif chitieu=='Bán các công cụ tài chính':
			return layGiaTriSumCreditCoAgainst(nam,'1.4%','1.1%',company,finance_book)
		
		
		
		elif chitieu=='Dòng tiền thuần từ hoạt động đầu tư':
			return (
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.4%','1.1%',company,finance_book)
			)
		
		
#####################

		elif chitieu=='Tiền thu được khi phát hành cổ phiếu':
			return (layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company,finance_book)
			)
		elif chitieu=='Tiền trả nợ gốc vay':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
		elif chitieu=='Tiền thu từ đi vay':
			return layGiaTriSumCreditCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
		elif chitieu=='Tiền thu được khi phát hành trái phiếu':
			return layGiaTriSumCreditCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
		elif chitieu=='Thanh toán mệnh giá trái phiếu':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
		elif chitieu=='Tiền mua cổ phiếu quỹ':
			return -layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company,finance_book)
		elif chitieu=='Tiền nhận từ thương phiếu phải trả':
			return layGiaTriSumCreditCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
		elif chitieu=='Tiền trả cho thương phiếu phải trả':
			return -layGiaTriSumDeBitCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
		


		elif chitieu=='Tiền thuần từ hoạt động tài chính':
			return (
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
				)



		elif chitieu=='Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng dương)':
			return layGiaTriSumCreditCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
		elif chitieu=='Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng âm)':
			return -layGiaTriSumDeBitCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
		



		elif chitieu=='Tăng/giảm tiền và tương đương tiền':
			return (
					(
						(
							du_lieu_ma2
							+
							(
							layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
							-layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
							-layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)
							)
							+
							(
							((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
								-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
								+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
								- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
								- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
								)
							)
							+(
								(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
								+layGiaTriCredit(nam,'4.2%',company,finance_book)
								- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
								)
								-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
							)
							+(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
								- layGiaTriCredit(nam,'1.3%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
								-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
								)
							)
							+(
								(
									(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
									+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
									-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
								)
								-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
							)
							+(
								(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
								+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
								-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
								
							)
							+(
								layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
								+layGiaTriSumDeBitCoAgainst(nam,'4.4.1006%','1.1%',company,finance_book)
						)
					)
				)
				+
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1004.1%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.4.1004.2%','1.1%',company,finance_book)
			)
			+
			(
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.4%','1.1%',company,finance_book)
			)
			+
			(
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
			)
			+layGiaTriSumCreditCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
		)




		elif chitieu=='Tiền và tương đương tiền đầu năm':
			return layGiaTriOpeningDeBit(nam,'1.1%',company,finance_book)
		

		elif chitieu=='Tiền và tương đương tiền cuối năm':
			return (
				layGiaTriOpeningDeBit(nam,'1.1%',company,finance_book)
				+
				(
					(
						(
							du_lieu_ma2
							+
							(
							layGiaTriSumDeBit(nam,'6.1.1004%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.1.1005%',company,finance_book)
							-layGiaTriSumDeBit(nam,'5.2.1001%',company,finance_book)
							-layGiaTriCredit(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBit(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.2.1001%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.1.1008%',company,finance_book)
							+layGiaTriSumDeBit(nam,'6.2.1002%',company,finance_book)
							)
							+
							(
							((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
								-((layGiaTriOpeningDeBit(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDit(nam,'1.2.1001%',company,finance_book))
								+layGiaTriSumDeBit(nam,'1.2.1001%',company,finance_book)
								- layGiaTriCredit(nam,'1.2.1001%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.2.1004.2%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.2.1004.2%',company,finance_book)
								- layGiaTriCredit(nam,'1.2.1004.2%',company,finance_book)
								)
							)
							+(
								(-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
								+layGiaTriCredit(nam,'4.2%',company,finance_book)
								- layGiaTriSumDeBit(nam,'4.2%',company,finance_book)
								)
								-layGiaTriOpeningCreDit(nam,'4.2%',company,finance_book)
							)
							+(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.3%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.3%',company,finance_book)
								- layGiaTriCredit(nam,'1.3%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
								-(layGiaTriOpeningDeBit(nam,'1.5.1001%',company,finance_book)
								+layGiaTriSumDeBit(nam,'1.5.1001%',company,finance_book)
								-layGiaTriCredit(nam,'1.5.1001%',company,finance_book)
								)
							)
							+(
								(
									(layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book))
									+(layGiaTriCredit(nam,'4.1%',company,finance_book)-layGiaTriCredit(nam,'4.1.1002%',company,finance_book)-layGiaTriCredit(nam,'4.1.1003%',company,finance_book))
									-(layGiaTriSumDeBit(nam,'4.1%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBit(nam,'4.1.1003%',company,finance_book))
								)
								-((layGiaTriOpeningCreDit(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.1.1003%',company,finance_book)))
							)
							+(
								(layGiaTriOpeningCreDit(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDit(nam,'4.4.1005%',company,finance_book))
								+(layGiaTriCredit(nam,'4.4%',company,finance_book)-layGiaTriCredit(nam,'4.4.1004%',company,finance_book)-layGiaTriCredit(nam,'4.4.1005%',company,finance_book))
								-(layGiaTriSumDeBit(nam,'4.4%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBit(nam,'4.4.1005%',company,finance_book))
								
							)
							+(
								layGiaTriSumDeBitCoAgainst(nam,'2.7.1001%','1.1%',company,finance_book)
								+layGiaTriSumDeBitCoAgainst(nam,'4.4.1006%','1.1%',company,finance_book)
						)
					)
				)
				+
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1004.1%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.4.1004.2%','1.1%',company,finance_book)
			)
			+
			(
				-layGiaTriSumDeBitCoAgainst(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'1.4%','1.1%',company,finance_book)
			)
			+
			(
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainst(nam,'4.3.1001%','1.1%',company,finance_book)
			)
			+layGiaTriSumCreditCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainst(nam,'3.3.1001%','1.1%',company,finance_book)
			)
		)

	# Xử lý niên độ
	else:

		if chitieu=='Các khoản điều chỉnh':
			return (
				layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
				-layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
				-layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)
			)



		elif chitieu=='Chi phí khấu hao tài sản hữu hình':
			return layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
		elif chitieu=='Chi phí khấu hao tài sản vô hình':
			return layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
		elif chitieu=='Doanh thu tài chính':
			return -layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
		elif chitieu=='Lãi thanh lý tài sản cố định':
			return -layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
		elif chitieu=='Lỗ thanh lý tài sản cố định':
			return layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
		elif chitieu=='Chi phí tài chính':
			return layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
		elif chitieu=='Chi phí thuế thu nhập':
			return layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
		elif chitieu=='Chi phí phúc lợi sau nghỉ việc':
			return layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)

		####

		elif chitieu=='Thay đổi phát sinh từ hoạt động kinh doanh':
			return (
				((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					)
				)
				+(
					(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
					+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
					)
				)
				+(
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCreditKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1005%',company,finance_book))
					
				)
				+(
					layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1005%','1.1%',company,finance_book)
			)
		)

		####


		elif chitieu=='Tăng/giảm các khoản phải thu':
			return ((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm các khoản phải thu khác':
			return (layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm dự phòng':
			return (
					(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
					+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
			)
		elif chitieu=='Tăng/giảm hàng tồn kho':
			return (layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm chi phí trả trước':
			return (layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
					)
			)
		elif chitieu=='Tăng/giảm các khoản phải trả':
			return (
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				
		elif chitieu=='Tăng/giảm chi phí dồn tích':
			return (
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1001%',company,finance_book)
					+layGiaTriCreditKhacYearly(nam,'4.4.1001%',company,finance_book)
					- layGiaTriSumDeBitKhacYearly(nam,'4.4.1001%',company,finance_book)
					)
					-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1001%',company,finance_book)
			)
		elif chitieu=='Đóng góp vào quỹ phúc lợi sau nghỉ việc':
			return (
					layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1005%','1.1%',company,finance_book)
			)

		##########
		
		elif chitieu=='Tiền hình thành từ hoạt động kinh doanh':
			return (
				du_lieu_ma2
				+
				(
				layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
				-layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
				-layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
				+layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)
				)
				+
				(
				((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
					)
				)
				+(
					(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
					+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
					- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
					)
					-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
					- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
					)
				)
				+(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
					-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
					)
				)
				+(
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCreditKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1005%',company,finance_book))
					
				)
				+(
					layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
					+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1005%','1.1%',company,finance_book)
			)
		)
	)
		
		#############

		elif chitieu=='Tiền lãi đã trả':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1003%','1.1%',company,finance_book)
		elif chitieu=='Tiền lãi đã nhận':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1004.1%','1.1%',company,finance_book)
		elif chitieu=='Cổ tức đã trả':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1002%','1.1%',company,finance_book)
		elif chitieu=='Thuế thu nhập đã trả':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1004.2%','1.1%',company,finance_book)
		


		elif chitieu=='Tiền ròng từ hoạt động kinh doanh':
			return (
						(
						du_lieu_ma2
						+
						(
						layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
						+layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
						-layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
						-layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
						+layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
						+layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
						+layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
						+layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)
						)
						+
						(
						((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
							-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
							+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
							- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
							)
						)
						+(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
							-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
							- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
							)
						)
						+(
							(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
							+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
							- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
							)
							-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
						)
						+(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
							-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
							- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
							)
						)
						+(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
							-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
							-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
							)
						)
						+(
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCreditKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1005%',company,finance_book))
					
				)
						+(
							layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
							+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1006%','1.1%',company,finance_book)
					)
				)
			)
			+
			-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1003%','1.1%',company,finance_book)
			+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1004.1%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1002%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1004.2%','1.1%',company,finance_book)
		)

#############
		elif chitieu=='Mua sắm tài sản cố định':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1001.2%','1.1%',company,finance_book)
		elif chitieu=='Bán tài sản cố định':
			return +layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1001.2%','1.1%',company,finance_book)
		elif chitieu=='Cổ tức nhận được từ công ty liên doanh. liên kết':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'5.2.1002%','1.1%',company,finance_book)
		elif chitieu=='Các khoản cho vay':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
		elif chitieu=='Thu được từ cho vay':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
		elif chitieu=='Mua các công cụ tài chính':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
		elif chitieu=='Bán các công cụ tài chính':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
		
		
		
		elif chitieu=='Dòng tiền thuần từ hoạt động đầu tư':
			return (
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
			)
		
		
#####################

		elif chitieu=='Tiền thu được khi phát hành cổ phiếu':
			return (layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
			)
		elif chitieu=='Tiền trả nợ gốc vay':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
		elif chitieu=='Tiền thu từ đi vay':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
		elif chitieu=='Tiền thu được khi phát hành trái phiếu':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
		elif chitieu=='Thanh toán mệnh giá trái phiếu':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
		elif chitieu=='Tiền mua cổ phiếu quỹ':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
		elif chitieu=='Tiền nhận từ thương phiếu phải trả':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
		elif chitieu=='Tiền trả cho thương phiếu phải trả':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
		


		elif chitieu=='Tiền thuần từ hoạt động tài chính':
			return (
				(layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
				)



		elif chitieu=='Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng dương)':
			return layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
		elif chitieu=='Ảnh hưởng của việc thay đổi tỷ giá hối đoái (Ảnh hưởng âm)':
			return -layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
		



		elif chitieu=='Tăng/giảm tiền và tương đương tiền':
			return (
					(
						(
							du_lieu_ma2
							+
							(
							layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
							-layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
							-layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)
							)
							+
							(
							((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
								-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
								+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								)
							)
							+(
								(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
								+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
								- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
								)
								-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
								)
							)
							+(
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCreditKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1005%',company,finance_book))
					
				)
							+(
								layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
								+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1006%','1.1%',company,finance_book)
						)
					)
				)
				+
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1004.1%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1004.2%','1.1%',company,finance_book)
			)
			+
			(
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
			)
			+
			(
				(layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
			)
			+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
		)




		elif chitieu=='Tiền và tương đương tiền đầu năm':
			return layGiaTriOpeningDeBitKhacYearly(nam,'1.1%',company,finance_book)
		

		elif chitieu=='Tiền và tương đương tiền cuối năm':
			return (
				layGiaTriOpeningDeBitKhacYearly(nam,'1.1%',company,finance_book)
				+
				(
					(
						(
							du_lieu_ma2
							+
							(
							layGiaTriSumDeBitKhacYearly(nam,'6.1.1004%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.1.1005%',company,finance_book)
							-layGiaTriSumDeBitKhacYearly(nam,'5.2.1001%',company,finance_book)
							-layGiaTriCreditKhacYearly(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'7.1.1002%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.2.1001%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.1.1008%',company,finance_book)
							+layGiaTriSumDeBitKhacYearly(nam,'6.2.1002%',company,finance_book)
							)
							+
							(
							((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
								-((layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'1.2.1001%',company,finance_book))
								+layGiaTriSumDeBitKhacYearly(nam,'1.2.1001%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.2.1001%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.2.1004.2%',company,finance_book)
								)
							)
							+(
								(-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
								+layGiaTriCreditKhacYearly(nam,'4.2%',company,finance_book)
								- layGiaTriSumDeBitKhacYearly(nam,'4.2%',company,finance_book)
								)
								-layGiaTriOpeningCreDitKhacYearly(nam,'4.2%',company,finance_book)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.3%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.3%',company,finance_book)
								- layGiaTriCreditKhacYearly(nam,'1.3%',company,finance_book)
								)
							)
							+(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								-(layGiaTriOpeningDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								+layGiaTriSumDeBitKhacYearly(nam,'1.5.1001%',company,finance_book)
								-layGiaTriCreditKhacYearly(nam,'1.5.1001%',company,finance_book)
								)
							)
							+(
					(
						(layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book))
						+(layGiaTriCreditKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.1.1003%',company,finance_book))
						-(layGiaTriSumDeBitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.1.1003%',company,finance_book))
					)
					-((layGiaTriOpeningCreDitKhacYearly(nam,'4.1%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1002%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.1.1003%',company,finance_book)))
				)
				+(
					(layGiaTriOpeningCreDitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriOpeningCreDitKhacYearly(nam,'4.4.1005%',company,finance_book))
					+(layGiaTriCreditKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriCreditKhacYearly(nam,'4.4.1005%',company,finance_book))
					-(layGiaTriSumDeBitKhacYearly(nam,'4.4%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1004%',company,finance_book)-layGiaTriSumDeBitKhacYearly(nam,'4.4.1005%',company,finance_book))
					
				)
							+(
								layGiaTriSumDeBitCoAgainstKhacYearly(nam,'2.7.1001%','1.1%',company,finance_book)
								+layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1006%','1.1%',company,finance_book)
						)
					)
				)
				+
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1004.1%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.4.1004.2%','1.1%',company,finance_book)
			)
			+
			(
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.1.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1001.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'5.2.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.2.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'1.4%','1.1%',company,finance_book)
			)
			+
			(
				(layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1001%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.1.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1002%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1003%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.2%','1.1%',company,finance_book)
				+layGiaTriSumCreditCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
				-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'4.3.1001%','1.1%',company,finance_book)
			)
			+layGiaTriSumCreditCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
			-layGiaTriSumDeBitCoAgainstKhacYearly(nam,'3.3.1001%','1.1%',company,finance_book)
			)
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



# XỬ lý niên độ 
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
		and posting_date>=%(from_date)s
		and posting_date<=%(to_date)s
		and ifnull(is_opening, 'No') = 'No'
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
		and posting_date>=%(from_date)s
		and posting_date<=%(to_date)s
		and ifnull(is_opening, 'No') = 'No'
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
		and posting_date>=%(from_date)s
		and posting_date<=%(to_date)s
		and ifnull(is_opening, 'No') = 'No'
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
		and posting_date>=%(from_date)s
		and posting_date<=%(to_date)s
		and ifnull(is_opening, 'No') = 'No'
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
			and posting_date>=%(from_date)s
			and posting_date<=%(to_date)s
			and ifnull(is_opening, 'No') = 'Yes'
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
			and posting_date>=%(from_date)s
			and posting_date<=%(to_date)s
			and ifnull(is_opening, 'No') = 'Yes'
			and account LIKE %(account)s
			and is_cancelled = 0
			""",test,as_list=True)[0][0],2))