# Data Dictionary & Schema Specification
## Autonomous Investment Research Intelligence Agent (IRA)

---

### Document Control
- **Document Version:** 1.0.0
- **Scope:** Complete Data Catalog for Financial Filings, Transcripts, Entities, and Citations

---

## 1. SEC Financial Statement Entities & XBRL Taxonomies

### 1.1 Consolidated Statements of Operations (Income Statement)

| Field Name | Data Type | XBRL Taxonomy Tag (US-GAAP) | Unit | Description & Line-Item Semantics |
|---|---|---|---|---|
| `ticker` | String | `dei:TradingSymbol` | N/A | Primary equity trading symbol (e.g. `AAPL`). |
| `fiscal_year` | Integer | `dei:DocumentFiscalYearFocus` | Year | Fiscal reporting year (e.g. `2024`). |
| `fiscal_period` | String | `dei:DocumentFiscalPeriodFocus` | Enum | `FY`, `Q1`, `Q2`, `Q3`, `Q4`. |
| `revenue_total` | Float/Decimal | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | USD | Total top-line net sales / revenues. |
| `cost_of_revenue` | Float/Decimal | `us-gaap:CostOfGoodsAndServicesSold` | USD | Cost of goods and services sold. |
| `gross_profit` | Float/Decimal | `us-gaap:GrossProfit` | USD | Net revenue minus cost of revenue. |
| `research_and_development` | Float/Decimal | `us-gaap:ResearchAndDevelopmentExpense` | USD | Operating R&D expenditures. |
| `selling_general_admin` | Float/Decimal | `us-gaap:SellingGeneralAndAdministrativeExpense` | USD | SG&A overhead expenses. |
| `operating_income` | Float/Decimal | `us-gaap:OperatingIncomeLoss` | USD | Earnings Before Interest & Taxes (EBIT). |
| `net_income` | Float/Decimal | `us-gaap:NetIncomeLoss` | USD | Bottom-line consolidated net income. |
| `diluted_eps` | Float/Decimal | `us-gaap:EarningsPerShareDiluted` | USD/Share | Diluted earnings per common share. |

---

### 1.2 Consolidated Balance Sheets

| Field Name | Data Type | XBRL Taxonomy Tag (US-GAAP) | Unit | Description & Line-Item Semantics |
|---|---|---|---|---|
| `cash_and_equivalents` | Float/Decimal | `us-gaap:CashAndCashEquivalentsAtCarryingValue` | USD | Highly liquid cash and short-term deposits. |
| `marketable_securities_current` | Float/Decimal | `us-gaap:MarketableSecuritiesCurrent` | USD | Current liquid marketable securities. |
| `accounts_receivable` | Float/Decimal | `us-gaap:AccountsReceivableNetCurrent` | USD | Trade receivables due within one year. |
| `total_current_assets` | Float/Decimal | `us-gaap:AssetsCurrent` | USD | Total short-term assets. |
| `property_plant_equipment` | Float/Decimal | `us-gaap:PropertyPlantAndEquipmentNet` | USD | Net fixed physical assets. |
| `total_assets` | Float/Decimal | `us-gaap:Assets` | USD | Total balance sheet assets. |
| `accounts_payable` | Float/Decimal | `us-gaap:AccountsPayableCurrent` | USD | Current trade liabilities. |
| `short_term_debt` | Float/Decimal | `us-gaap:DebtCurrent` | USD | Commercial paper, current notes payable. |
| `long_term_debt` | Float/Decimal | `us-gaap:LongTermDebtNoncurrent` | USD | Long-term bonds, senior notes, mortgages. |
| `total_liabilities` | Float/Decimal | `us-gaap:Liabilities` | USD | Total obligations and debt. |
| `retained_earnings` | Float/Decimal | `us-gaap:RetainedEarningsAccumulatedDeficit` | USD | Cumulative retained net earnings. |
| `shareholders_equity` | Float/Decimal | `us-gaap:StockholdersEquity` | USD | Net book value / total equity interest. |

---

### 1.3 Consolidated Statements of Cash Flows

| Field Name | Data Type | XBRL Taxonomy Tag (US-GAAP) | Unit | Description & Line-Item Semantics |
|---|---|---|---|---|
| `cash_from_operations` | Float/Decimal | `us-gaap:NetCashProvidedByUsedInOperatingActivities` | USD | Net cash provided by operating activities. |
| `capital_expenditures` | Float/Decimal | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` | USD | Additions to property, plant, and equipment. |
| `cash_from_investing` | Float/Decimal | `us-gaap:NetCashProvidedByUsedInInvestingActivities` | USD | Net cash used in investing activities. |
| `dividends_paid` | Float/Decimal | `us-gaap:PaymentsOfDividends` | USD | Cash returned via common/preferred dividends. |
| `share_repurchases` | Float/Decimal | `us-gaap:PaymentsForRepurchaseOfCommonStock` | USD | Cash spent repurchasing common shares. |
| `cash_from_financing` | Float/Decimal | `us-gaap:NetCashProvidedByUsedInFinancingActivities` | USD | Net cash provided by/used in financing. |

---

## 2. Earnings Call Transcript Speaker & Segment Labels

| Field Name | Data Type | Valid Enum Values | Description |
|---|---|---|---|
| `section_type` | String | `PREPARED_REMARKS`, `ANALYST_QA` | Distinguishes scripted formal presentation from unscripted Q&A. |
| `speaker_role` | String | `CHIEF_EXECUTIVE_OFFICER`, `CHIEF_FINANCIAL_OFFICER`, `HEAD_OF_IR`, `EQUITY_ANALYST`, `OPERATOR` | Corporate or financial role of the speaker. |
| `speaker_name` | String | Free text (e.g. `Luca Maestri`, `Tim Cook`) | Full name of the speaker. |
| `speaker_firm` | String | Free text (e.g. `Apple Inc.`, `Morgan Stanley`) | Employer / financial institution of speaker. |
| `timestamp_offset` | Integer | Seconds elapsed | Offset from audio start time. |
| `speech_content` | String | Verbatim transcript text | Verbatim transcribed remarks. |
| `sentiment_score` | Float | Range `[-1.0, +1.0]` | Polarity score of statement segment. |
| `topics_mentioned` | List[String] | e.g. `["Gross_Margin", "Services", "China"]` | Detected financial discussion topics. |

---

## 3. Evidentiary Provenance Citation Schema

| Field Name | Data Type | Nullable | Description & Example |
|---|---|---|---|
| `citation_id` | String (UUID) | No | Unique citation identifier (`cite-e4b1-91a2`). |
| `source_type` | String | No | Enum: `SEC_FORM_10K`, `SEC_FORM_10Q`, `TRANSCRIPT_REMARKS`, `TRANSCRIPT_QA`, `MACRO_NEWS`. |
| `filing_accession_number` | String | Yes | SEC EDGAR accession number (e.g. `0000320193-24-000106`). |
| `document_period` | String | No | Period string (e.g. `FY2024`, `Q4_2024`). |
| `table_or_section_name` | String | No | Name of table or transcript section (`Consolidated Statements of Operations`). |
| `row_item` | String | Yes | Exact row title (`Products net sales`). |
| `column_header` | String | Yes | Exact column header (`September 28, 2024`). |
| `verbatim_quote` | String | Yes | Quote excerpt from transcript or MD&A text. |
| `source_url` | String (URI) | Yes | Direct hyperlink to SEC EDGAR filing or news article. |
| `confidence_score` | Float | No | Groundedness confidence rating (`1.0`). |
