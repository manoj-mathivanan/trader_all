import unittest
from core.research import investor_financials as f

class FinancialTests(unittest.TestCase):
    def setUp(self):
        self.item=dict(symbol='EXAMPLE')
        self.sections={'annual_income':{'data':{'income_statement':[{'category':'net_profit','history':[{'period':'Mar 2026','value':100}]}]}},'balance_sheet':{'data':{'full_statement':[{'particular':'Equity Capital','history':[{'period':'Mar 2026','value':500}]}]}}}
    def page(self,basis='Consolidated',equity=450,profit=100):
        def table(key,rows):
            return '<section id="'+key+'">'+basis+' Figures in Rs. Crores<table><thead><tr><th></th><th>Mar 2026</th><th>TTM</th></tr></thead><tbody>'+''.join('<tr><td>'+label+'</td><td>'+str(value)+'</td><td>999</td></tr>' for label,value in rows)+'</tbody></table></section>'
        return ('<a>NSE: EXAMPLE</a>'+table('balance-sheet',[('Equity Capital',50),('Reserves',equity),('Borrowings +',100)])+table('profit-loss',[('Net Profit +',profit)])+table('cash-flow',[('Cash from Operating Activity +',120)])).encode()
    def test_matched_basis_period_and_reconciled_values(self):
        r=f.parse(self.page(),self.item,'consolidated',self.sections)
        self.assertEqual(r['debt_equity'],.2);self.assertEqual(r['operating_cash_flow'],120);self.assertEqual(r['period'],'Mar 2026')
    def test_mismatched_equity_and_profit_not_used(self):
        r=f.parse(self.page(equity=100,profit=60),self.item,'consolidated',self.sections)
        self.assertIsNone(r['debt_equity']);self.assertIsNone(r['operating_cash_flow'])
    def test_wrong_symbol_and_basis_rejected(self):
        with self.assertRaises(ValueError):f.parse(self.page().replace(b'EXAMPLE',b'OTHER'),self.item,'consolidated',self.sections)
        with self.assertRaises(ValueError):f.parse(self.page('Standalone'),self.item,'consolidated',self.sections)
    def test_missing_borrowings_not_zero_debt(self):
        r=f.parse(self.page().replace(b'Borrowings +',b'Other Liabilities'),self.item,'consolidated',self.sections)
        self.assertIsNone(r['debt_equity'])

    def test_standalone_only_page_metadata(self):
        raw=self.page().replace(b'Consolidated Figures',b'Figures')+b'<div id="company-info" data-company-id="1" data-warehouse-id="2"></div>'
        r=f.parse(raw,self.item,'standalone',self.sections)
        self.assertEqual(r['debt_equity'],.2)
        with self.assertRaises(ValueError):f.parse(raw,self.item,'consolidated',self.sections)

    def test_profit_disagreement_blocks_leverage_also(self):
        r=f.parse(self.page(profit=50),self.item,'consolidated',self.sections)
        self.assertIsNone(r['debt_equity'])

    def test_official_nci_reconciliation_requires_exact_basis_and_year(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from core.research import store
        with tempfile.TemporaryDirectory() as folder,patch.object(store,'DATA',Path(folder)):
            self.item['isin']='X'
            v=dict(status='visually_verified',company=self.item,period='Mar 2026',statement_basis='consolidated',units='crore',source_sha256='hash',source_pages=[1],total_equity=500,debt_including_leases=100)
            store.write('investor/assessments/verified-financials-X',v)
            self.assertEqual(f.parse(self.page(equity=100),self.item,'consolidated',self.sections)['debt_equity'],.2)
            for field,value in [('period','Mar 2025'),('statement_basis','standalone'),('status','needs_review'),('total_equity',700)]:
                store.write('investor/assessments/verified-financials-X',dict(v,**{field:value}))
                self.assertIsNone(f.parse(self.page(equity=100),self.item,'consolidated',self.sections)['debt_equity'])

    def test_negative_equity_has_no_debt_ratio(self):
        self.sections['balance_sheet']['data']['full_statement'][0]['history'][0]['value']=-500
        r=f.parse(self.page(equity=-550),self.item,'consolidated',self.sections)
        self.assertTrue(r['reconciliation']['equity']);self.assertIsNone(r['debt_equity'])
