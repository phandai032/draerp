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

from draerp.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from draerp.accounts.report.utils import convert_to_presentation_currency, get_currency
from draerp.accounts.utils import get_fiscal_year
from pymysql import NULL
from draerp.accounts.report.financial_statements import get_data as get_data_test
from draerp.accounts.report.profit_and_loss_statement.profit_and_loss_statement import (
	get_net_profit_loss,
)

def get_data(
		company,nam,period,filters,
		accumulated_values=1,
		ignore_closing_entries=True, ignore_accumulated_values_for_fy= True):
		
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
	out = prepare_data(accounts,company,nam,net_profit_loss)
	return out

def insert_data():
	return frappe.db.sql("""
		INSERT INTO `tabCHANGES IN EQUITY` (`name`, `creation`, `modified`, `modified_by`, `owner`, `docstatus`, `idx`, `chi_tieu`, `von_co_phan`, `thang_du_co_phan`, `loi_nhuan_giu_lai`, `co_phieu_quy`, `thu_nhap_toan_dien_khac`, `tong_nguon_von`, `_user_tags`, `_comments`, `_assign`, `_liked_by`) VALUES
			('CIE0001', '2022-10-04 16:29:51.699178', '2022-10-04 16:29:51.699178', 'Administrator', 'Administrator', 0, 0, 'Số dư đầu kỳ', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0002', '2022-10-04 16:30:12.629672', '2022-10-04 16:30:12.629672', 'Administrator', 'Administrator', 0, 0, 'Lợi nhuận trong năm', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0003', '2022-10-04 16:30:18.883372', '2022-10-04 16:30:18.883372', 'Administrator', 'Administrator', 0, 0, 'Thu nhập toàn diện khác', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0004', '2022-10-04 16:30:24.781125', '2022-10-04 16:30:24.781125', 'Administrator', 'Administrator', 0, 0, 'Phát hành cổ phiếu', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0005', '2022-10-04 16:30:31.615638', '2022-10-04 16:30:31.615638', 'Administrator', 'Administrator', 0, 0, 'Mua lại cổ phiếu', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0006', '2022-10-04 16:30:38.093535', '2022-10-04 16:30:38.093535', 'Administrator', 'Administrator', 0, 0, 'Chia cổ tức', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
			('CIE0007', '2022-10-04 16:30:47.256926', '2022-10-04 16:30:47.256926', 'Administrator', 'Administrator', 0, 0, 'Số dư cuối kỳ', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);
		""")
def drop_table():
	return frappe.db.sql("""
		DROP TABLE IF EXISTS `tabCHANGES IN EQUITY`;
	""")
def create_table():
	return frappe.db.sql("""
		CREATE TABLE IF NOT EXISTS `tabCHANGES IN EQUITY` (
			`name` varchar(140) COLLATE utf8mb4_unicode_ci NOT NULL,
			`creation` datetime(6) DEFAULT NULL,
			`modified` datetime(6) DEFAULT NULL,
			`modified_by` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`owner` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`docstatus` int(1) NOT NULL DEFAULT 0,
			`idx` int(8) NOT NULL DEFAULT 0,
			`chi_tieu` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`von_co_phan` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`thang_du_co_phan` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`loi_nhuan_giu_lai` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`co_phieu_quy` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`thu_nhap_toan_dien_khac` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`tong_nguon_von` varchar(140) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_user_tags` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_comments` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_assign` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			`_liked_by` text COLLATE utf8mb4_unicode_ci DEFAULT NULL,
			PRIMARY KEY (`name`),
			KEY `modified` (`modified`)
			) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci ROW_FORMAT=DYNAMIC;
	""")

def prepare_data(accounts,company,nam,net_profit_loss):
	data = []
	i=0
	for d in accounts:
		# add to output
		
		row = frappe._dict({
			"chi_tieu": d.chi_tieu,
			"von_co_phan":tinhMaI(company,nam,i),
			"thang_du_von_co_phan": tinhMaII(company,nam,i),
			"lai_nhuan_giu_lai":tinhMaIII(company,nam,i,net_profit_loss),
			"co_phieu_quy": tinhMaIV(company,nam,i),
			"thu_nhap_toan_dien_khac":tinhMaV(company,nam,i),
			"tong_nguon_von":tinhMaVI(company,nam,i,net_profit_loss),
		})
		i=i+1

		data.append(row)

	return data

def get_dulieu():
	return frappe.db.sql("""
		select chi_tieu
		from `tabCHANGES IN EQUITY`
		""",as_dict=True)

def get_columns():
	columns = [{
		"fieldname": "chi_tieu",
		"label": "Chỉ Tiêu",
		"fieldtype": "Data",
		"options": "CHANGES IN EQUITY",
		"width":173.188
	},
	{
		"fieldname": "von_co_phan",
		"label": "I. Vốn cổ phần",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":145,
	},
	{
		"fieldname": "thang_du_von_co_phan",
		"label": "II. Thặng dư vốn cổ phần",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":200
	},
	{
		"fieldname": "lai_nhuan_giu_lai",
		"label": "III. Lợi nhuận giữ lại",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":167
	},
	{
		"fieldname": "co_phieu_quy",
		"label": "IV. Cổ phiếu quỹ",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":158
	},
	{
		"fieldname": "thu_nhap_toan_dien_khac",
		"label": "V. Thu nhập toàn diện khác",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":200
	},
	{
		"fieldname": "tong_nguon_von",
		"label": "Tổng nguồn vốn",
		"fieldtype": "Data",
		"fieldtype": "Currency",
		"width":164
	},
	]

	return columns

def tinhMaI(company,nam,vi_tri):
	if vi_tri==0:
		return layGiaTriOpeningCreDit(nam,'3.1.1001%',company)
	elif vi_tri==1:
		return 0
	elif vi_tri==2:
		return 0
	elif vi_tri==3:
		return(
			(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company))
			+
			(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.4%',company))
			+
			(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.3%',company))
			+
			(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.1%',company))
			+
			(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.2%',company))
		)
	elif vi_tri==4:
		return 0
	elif vi_tri==5:
		return 0
	elif vi_tri==6:
		return (
			layGiaTriOpeningCreDit(nam,'3.1.1001%',company)
			+
			(
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company))
				+
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.4%',company))
				+
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.3%',company))
				+
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.1%',company))
				+
				(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.2%',company))
			)
		)
	
def tinhMaII(company,nam,vi_tri):
	if vi_tri==0:
		return layGiaTriOpeningCreDit(nam,'3.1.1002%',company)
	elif vi_tri==1:
		return 0
	elif vi_tri==2:
		return 0
	elif vi_tri==3:
		return (
			layGiaTriCredit(nam,'3.1.1002%',company)
			-
			layGiaTriSumDeBit(nam,'3.1.1002%',company)
		)
	elif vi_tri==4:
		return 0
	elif vi_tri==5:
		return 0
	elif vi_tri==6:
		return (
			layGiaTriOpeningCreDit(nam,'3.1.1002%',company)
			+
			(
				layGiaTriCredit(nam,'3.1.1002%',company)
				-
				layGiaTriSumDeBit(nam,'3.1.1002%',company)
			)
		)
def tinhMaIII(company,nam,vi_tri,net_profit_loss):
	if vi_tri==0:
		return layGiaTriOpeningCreDit(nam,'3.1.1003%',company)
	elif vi_tri==1:
		test=0
		try:
			test=net_profit_loss['total']
		except:
			test=0
		return test
	elif vi_tri==2:
		return 0
	elif vi_tri==3:
		return 0
	elif vi_tri==4:
		return 0
	elif vi_tri==5:
		return -tinhMa_III_5(nam,company)
	elif vi_tri==6:
		return (
			layGiaTriOpeningCreDit(nam,'3.1.1003%',company)
			+
			-tinhMa_III_5(nam,company)
		)
def tinhMaIV(company,nam,vi_tri):
	if vi_tri==0:
		return -layGiaTriOpeningDeBit(nam,'3.2%',company)
	elif vi_tri==1:
		return 0
	elif vi_tri==2:
		return 0
	elif vi_tri==3:
		return layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company)+layGiaTriSumCreditCoAgainst(nam,'3.2%','3.1.1002%',company)
	elif vi_tri==4:
		return -layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company)
	elif vi_tri==5:
		return 0
	elif vi_tri==6:
		return (
			-layGiaTriOpeningDeBit(nam,'3.2%',company)
			+
			layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company)+layGiaTriSumCreditCoAgainst(nam,'3.2%','3.1.1002%',company)
			+
			-layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company)
		)
def tinhMaV(company,nam,vi_tri):
	if vi_tri==0:
		return layGiaTriOpeningCreDit(nam,'3.3%',company)
	elif vi_tri==1:
		return 0
	elif vi_tri==2:
		return (
				(
				layGiaTriCredit(nam,'3.3.1005%',company)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company) - layGiaTriCredit(nam,'3.3.1004%',company)
				+(layGiaTriCredit(nam,'3.3.1006%',company)-(layGiaTriSumDeBit(nam,'3.3.1006%',company))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company))
				+(layGiaTriCredit(nam,'3.3.1007%',company)-(layGiaTriSumDeBit(nam,'3.3.1007%',company))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company)-layGiaTriSumDeBit(nam,'3.3.1001%',company)
				+(layGiaTriCredit(nam,'3.3.1003%',company)-(layGiaTriSumDeBit(nam,'3.3.1003%',company))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company))
				+layGiaTriCredit(nam,'3.3.1002%',company)-layGiaTriSumDeBit(nam,'3.3.1002%',company)
				)
			)
	elif vi_tri==3:
		return 0
	elif vi_tri==4:
		return 0
	elif vi_tri==5:
		return 0
	elif vi_tri==6:
		return (
			layGiaTriOpeningCreDit(nam,'3.3%',company)
			+
			(
				(
				layGiaTriCredit(nam,'3.3.1005%',company)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company) - layGiaTriCredit(nam,'3.3.1004%',company)
				+(layGiaTriCredit(nam,'3.3.1006%',company)-(layGiaTriSumDeBit(nam,'3.3.1006%',company))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company))
				+(layGiaTriCredit(nam,'3.3.1007%',company)-(layGiaTriSumDeBit(nam,'3.3.1007%',company))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company)-layGiaTriSumDeBit(nam,'3.3.1001%',company)
				+(layGiaTriCredit(nam,'3.3.1003%',company)-(layGiaTriSumDeBit(nam,'3.3.1003%',company))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company))
				+layGiaTriCredit(nam,'3.3.1002%',company)-layGiaTriSumDeBit(nam,'3.3.1002%',company)
				)
			)
		)
def tinhMaVI(company,nam,vi_tri,net_profit_loss):
	if vi_tri==0:
		return (
			layGiaTriOpeningCreDit(nam,'3.1.1001%',company)
			+
			layGiaTriOpeningCreDit(nam,'3.1.1002%',company)
			+
			layGiaTriOpeningCreDit(nam,'3.1.1003%',company)
			+
			-layGiaTriOpeningDeBit(nam,'3.2%',company)
			+
			layGiaTriOpeningCreDit(nam,'3.3%',company)
		)
	elif vi_tri==1:
		test=0
		try:
			test=net_profit_loss['total']
		except:
			test=0
		return test
	elif vi_tri==2:
		return (
				(
				layGiaTriCredit(nam,'3.3.1005%',company)
				+layGiaTriSumDeBit(nam,'3.3.1004%',company) - layGiaTriCredit(nam,'3.3.1004%',company)
				+(layGiaTriCredit(nam,'3.3.1006%',company)-(layGiaTriSumDeBit(nam,'3.3.1006%',company))-layGiaTriOpeningCreDit(nam,'3.3.1006%',company))
				+(layGiaTriCredit(nam,'3.3.1007%',company)-(layGiaTriSumDeBit(nam,'3.3.1007%',company))-layGiaTriOpeningCreDit(nam,'3.3.1007%',company))

				)
				+
				(
				layGiaTriCredit(nam,'3.3.1001%',company)-layGiaTriSumDeBit(nam,'3.3.1001%',company)
				+(layGiaTriCredit(nam,'3.3.1003%',company)-(layGiaTriSumDeBit(nam,'3.3.1003%',company))-layGiaTriOpeningCreDit(nam,'3.3.1003%',company))
				+layGiaTriCredit(nam,'3.3.1002%',company)-layGiaTriSumDeBit(nam,'3.3.1002%',company)
				)
			)
	elif vi_tri==3:
		return (
				(
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.4%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.3%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.1%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.2%',company))
				)
				+
				(
					layGiaTriCredit(nam,'3.1.1002%',company)
					-
					layGiaTriSumDeBit(nam,'3.1.1002%',company)
				)
				+
				layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company)+layGiaTriSumCreditCoAgainst(nam,'3.2%','3.1.1002%',company)
		)
	elif vi_tri==4:
		return -layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company)
	elif vi_tri==5:
		return -tinhMa_III_5(nam,company)
	elif vi_tri==6:
		return (
			(
				layGiaTriOpeningCreDit(nam,'3.1.1001%',company)
				+
				layGiaTriOpeningCreDit(nam,'3.1.1002%',company)
				+
				layGiaTriOpeningCreDit(nam,'3.1.1003%',company)
				+
				-layGiaTriOpeningDeBit(nam,'3.2%',company)
				+
				layGiaTriOpeningCreDit(nam,'3.3%',company)
			)
			+
			(
				(
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.1%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.4%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','1.3%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.1%',company))
					+
					(layGiaTriSumCreditCoAgainst(nam,'3.1.1001%','2.2%',company))
				)
				+
				(
					layGiaTriCredit(nam,'3.1.10012',company)
					-
					layGiaTriSumDeBit(nam,'3.1.1001%',company)
				)
				+
				layGiaTriSumCreditCoAgainst(nam,'3.2%','1.1%',company)+layGiaTriSumCreditCoAgainst(nam,'3.2%','3.1.1002%',company)
			)
			+
			-layGiaTriSumDeBitCoAgainst(nam,'3.2%','1.1%',company)
			+
			-tinhMa_III_5(nam,company)

		)
	

def tinhMa_III_5(nam,company):

	test={
		"nam":nam,
		"company":company
	}
	return(flt(frappe.db.sql("""
		select
			SUM(debit)
	from `tabGL Entry`
	where
		( company=%(company)s
		and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No' and is_cancelled = 0 )
		AND ( account LIKE '3.1.1003%%' AND AGAINST LIKE '4.1.1002%%' )
		OR ( ACCOUNT LIKE '3.1.1003%%' AND AGAINST IN (
					select
					party
			from `tabGL Entry`
			where
				( company=%(company)s
				and (fiscal_year = %(nam)s) and ifnull(is_opening, 'No') = 'No' and is_cancelled = 0 )
				AND ( account LIKE '4.1.1002%%' AND AGAINST LIKE '3.1.1003%%' )
			)
		)
		
		""",test,as_list=True)[0][0],2))

def layGiaTriSumDeBit(nam,account,company):

	test={
		"nam":nam,
		"account":account,
		"company":company
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

def layGiaTriCredit(nam,account,company):

	test={
		"nam":nam,
		"account":account,
		"company":company
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

def layGiaTriOpeningDeBit(nam,account,company):

	test={
		"nam":nam,
		"account":account,
		"company":company
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
			
def layGiaTriOpeningCreDit(nam,account,company):

	test={
		"nam":nam,
		"account":account,
		"company":company
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

def layGiaTriSumDeBitCoAgainst(nam,account,against,company):

	test={
		"nam":nam,
		"account":account,
		"against":against,
		"company":company
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

def layGiaTriSumCreditCoAgainst(nam,account,against,company):

	test={
		"nam":nam,
		"account":account,
		"against":against,
		"company":company
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