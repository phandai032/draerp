
// Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt
/* eslint-disable */

frappe.query_reports["Changes In Equity IFRS"] = {

	"filters": get_filters(),
	"formatter": function(value, row, column, data, default_formatter) {

		// column.link_onclick =
		// 	"draerp.filterCanDoi.open_general_ledger(" + JSON.stringify(data) + ")";
		// column.is_tree = true;

		

		value = default_formatter(value, row, column, data);

		if (data.chi_tieu=='Số dư đầu kỳ'||data.chi_tieu=='Số dư cuối kỳ')
			{
			value = $(`<span>${value}</span>`);

			var $value = $(value).css("font-weight", "bold");
			value = $value.wrap("<p></p>").parent().html();
		}
		return value;
	},
	onload: function(report) {
		// dropdown for links to other financial statementss
		// draerp.ket_qua_kinh_doanh.filters = get_filters()

		// let fiscal_year = frappe.defaults.get_user_default("fiscal_year")

		// frappe.model.with_doc("Fiscal Year", fiscal_year, function(r) {
		// 	var fy = frappe.model.get_doc("Fiscal Year", fiscal_year);
		// 	frappe.query_report.set_filter_value({
		// 		period_start_date: fy.year_start_date,
		// 		period_end_date: fy.year_end_date
		// 	});
		// });
	}
};

function get_filters() {
	const query = { query: "draerp.accounts.report.luu_chuyen_tien_te_ifrs.company_query" };
	let filters = [

		{
			"fieldname":"company",
			"label": __("Select the company with the IFRS account"),
			"fieldtype": "Link",
			"options": "Company",
			//"default": frappe.defaults.get_user_default("Company"),
			"reqd": 1,
			"get_query": () => query,
		},
		
		/*
		{
			"fieldname":"finance_book",
			"label": __("Finance Book"),
			"fieldtype": "Link",
			"options": "Finance Book",
			"reqd": 0
		},
		*/
		{
			"fieldname":"filter_based_on",
			"label": __("Filter Based On"),
			"fieldtype": "Select",
			"options": ["Fiscal Year"],
			"default": ["Fiscal Year"],
			"hidden":1,

			on_change: function() {
				let filter_based_on = frappe.query_report.get_filter_value('filter_based_on');
				frappe.query_report.toggle_filter_display('from_fiscal_year', filter_based_on === 'Date Range');
				frappe.query_report.toggle_filter_display('to_fiscal_year', filter_based_on === 'Date Range');
				frappe.query_report.toggle_filter_display('period_start_date', filter_based_on === 'Fiscal Year');
				frappe.query_report.toggle_filter_display('period_end_date', filter_based_on === 'Fiscal Year');

				frappe.query_report.refresh();
			}
		},
		{
			"fieldname":"period_start_date",
			"label": __("Start Date"),
			"fieldtype": "Date",
			
			"depends_on": "eval:doc.filter_based_on == 'Date Range'"
		},
		{
			"fieldname":"period_end_date",
			"label": __("End Date"),
			"fieldtype": "Date",
			
			"depends_on": "eval:doc.filter_based_on == 'Date Range'"
		},
		{
			"fieldname":"from_fiscal_year",
			"label": __("Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": frappe.defaults.get_user_default("fiscal_year"),
			"reqd": 1,
			"depends_on": "eval:doc.filter_based_on == 'Fiscal Year'",
			on_change: function(frm){
				frappe.query_report.set_filter_value('to_fiscal_year',frappe.query_report.get_filter_value('from_fiscal_year'))
			}
		},
		{
			"fieldname":"to_fiscal_year",
			"label": __("End Year"),
			"fieldtype": "Link",
			"options": "Fiscal Year",
			"default": frappe.defaults.get_user_default("fiscal_year"),
			"hidden":1,
			"depends_on": "eval:doc.filter_based_on == 'Fiscal Year'",

		},
		{
			"fieldname": "periodicity",
			"label": __("Periodicity"),
			"fieldtype": "Select",
			"options": [
				{ "value": "Monthly", "label": __("Monthly") },
				{ "value": "Quarterly", "label": __("Quarterly") },
				{ "value": "Half-Yearly", "label": __("Half-Yearly") },
				{ "value": "Yearly", "label": __("Yearly") }
			],
			"default": "Yearly",
			"hidden": 1
		}
		// Note:
		// If you are modifying this array such that the presentation_currency object
		// is no longer the last object, please make adjustments in cash_flow.js
		// accordingly.

		
	]

	return filters;
}


