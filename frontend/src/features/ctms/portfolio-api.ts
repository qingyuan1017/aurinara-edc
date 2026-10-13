import { useQuery } from '@tanstack/react-query'
import { api, type PaginatedResponse } from '@/lib/api'

export type PortfolioMoney = string | number

export interface PortfolioMonitoringSummary {
  total: number
  upcoming: number
  overdue: number
  in_progress: number
  completed: number
  unassigned: number
  open_findings: number
}

export interface PortfolioMonitoringActivity {
  id: string
  study_id: string
  study_code: string
  study_title: string
  site_id?: string | null
  site_number?: string | null
  site_name?: string | null
  activity_type: string
  modality: string
  planned_date: string
  assigned_cra_id?: string | null
  assigned_cra_name?: string | null
  status: string
  is_overdue: boolean
  overdue_days: number
  open_findings: number
  report_status?: string | null
  reschedule_count: number
  escalation_reference?: string | null
}

export interface PortfolioCraWorkload {
  cra_id?: string | null
  cra_name: string
  total: number
  upcoming: number
  overdue: number
  in_progress: number
  completed: number
}

export interface PortfolioMonitoringFinding {
  id: string
  finding_code: string
  study_id: string
  study_code: string
  study_title: string
  site_id?: string | null
  site_number?: string | null
  site_name?: string | null
  visit_id?: string | null
  category: string
  severity: string
  description: string
  owner_id?: string | null
  owner_name?: string | null
  responsible_party?: string | null
  due_date?: string | null
  status: string
  capa_required: boolean
  open_actions: number
  is_overdue: boolean
}

export interface PortfolioContractSummary {
  total: number
  internal_review: number
  negotiation: number
  approved_awaiting_execution: number
  active: number
  expiring_30_days: number
  expired: number
}

export interface PortfolioContract {
  id: string
  study_id: string
  study_code: string
  study_title: string
  site_id?: string | null
  site_number?: string | null
  site_name?: string | null
  organization_id?: string | null
  contract_number: string
  title: string
  contract_type: string
  direction: string
  party_name: string
  status: string
  currency: string
  owner_id?: string | null
  owner_name?: string | null
  current_version_id?: string | null
  version_status?: string | null
  total_value?: PortfolioMoney | null
  effective_from?: string | null
  effective_to?: string | null
  days_to_expiry?: number | null
}

export interface PortfolioCurrencySummary {
  currency: string
  approved_budget: PortfolioMoney
  contracted: PortfolioMoney
  calculated_payables: PortfolioMoney
  approved_payables: PortfolioMoney
  invoiced: PortfolioMoney
  paid: PortfolioMoney
  outstanding: PortfolioMoney
  overdue: PortfolioMoney
  budget_variance: PortfolioMoney
}

export interface PortfolioFinancialSummary { currencies: PortfolioCurrencySummary[] }

export interface PortfolioPayable {
  id: string
  study_id: string
  study_code: string
  study_title: string
  contract_id: string
  contract_number: string
  party_name: string
  gross_amount: PortfolioMoney
  holdback_amount: PortfolioMoney
  net_amount: PortfolioMoney
  currency: string
  status: string
  approved_at?: string | null
  created_at: string
}

export interface PortfolioInvoice {
  id: string
  study_id: string
  study_code: string
  study_title: string
  contract_id: string
  contract_number: string
  party_name: string
  invoice_number: string
  direction: string
  invoice_date: string
  due_date: string
  amount: PortfolioMoney
  currency: string
  status: string
  paid_amount: PortfolioMoney
  outstanding_amount: PortfolioMoney
  is_overdue: boolean
  days_overdue: number
}

export interface PortfolioPayment {
  id: string
  study_id: string
  study_code: string
  study_title: string
  party_name: string
  direction: string
  payment_date: string
  amount: PortfolioMoney
  allocated_amount: PortfolioMoney
  currency: string
  reference: string
  status: string
  reversal_of_id?: string | null
}

export interface PortfolioFinancialReportRow extends PortfolioCurrencySummary {
  study_id: string
  study_code: string
  study_title: string
  group_by: string
  group_key: string
  group_label: string
}

export type PortfolioParams = Record<string, string | number | boolean | null | undefined>

function withParams(path: string, params: PortfolioParams = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const suffix = query.toString()
  return suffix ? `${path}?${suffix}` : path
}

async function get<T>(path: string, params?: PortfolioParams): Promise<T> {
  return (await api.get<T>(withParams(path, params))).data
}

export const portfolioApi = {
  monitoringSummary: () => get<PortfolioMonitoringSummary>('/ctms/portfolio/monitoring/summary'),
  monitoringActivities: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioMonitoringActivity>>('/ctms/portfolio/monitoring/activities', params),
  monitoringWorkload: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioCraWorkload>>('/ctms/portfolio/monitoring/workload', params),
  monitoringFindings: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioMonitoringFinding>>('/ctms/portfolio/monitoring/findings', params),
  contractSummary: () => get<PortfolioContractSummary>('/ctms/portfolio/contracts/summary'),
  contracts: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioContract>>('/ctms/portfolio/contracts', params),
  financialSummary: () => get<PortfolioFinancialSummary>('/ctms/portfolio/financials/summary'),
  payables: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioPayable>>('/ctms/portfolio/financials/payables', params),
  invoices: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioInvoice>>('/ctms/portfolio/financials/invoices', params),
  payments: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioPayment>>('/ctms/portfolio/financials/payments', params),
  report: (params?: PortfolioParams) => get<PaginatedResponse<PortfolioFinancialReportRow>>('/ctms/portfolio/financials/report', params),
}

export function usePortfolioMonitoringSummary() {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'monitoring', 'summary'], queryFn: portfolioApi.monitoringSummary })
}

export function usePortfolioMonitoringActivities(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'monitoring', 'activities', params], queryFn: () => portfolioApi.monitoringActivities(params) })
}

export function usePortfolioMonitoringWorkload(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'monitoring', 'workload', params], queryFn: () => portfolioApi.monitoringWorkload(params) })
}

export function usePortfolioMonitoringFindings(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'monitoring', 'findings', params], queryFn: () => portfolioApi.monitoringFindings(params) })
}

export function usePortfolioContractSummary() {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'contracts', 'summary'], queryFn: portfolioApi.contractSummary })
}

export function usePortfolioContracts(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'contracts', params], queryFn: () => portfolioApi.contracts(params) })
}

export function usePortfolioFinancialSummary() {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'financials', 'summary'], queryFn: portfolioApi.financialSummary })
}

export function usePortfolioPayables(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'financials', 'payables', params], queryFn: () => portfolioApi.payables(params) })
}

export function usePortfolioInvoices(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'financials', 'invoices', params], queryFn: () => portfolioApi.invoices(params) })
}

export function usePortfolioPayments(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'financials', 'payments', params], queryFn: () => portfolioApi.payments(params) })
}

export function usePortfolioFinancialReport(params: PortfolioParams = {}) {
  return useQuery({ queryKey: ['ctms', 'portfolio', 'financials', 'report', params], queryFn: () => portfolioApi.report(params) })
}
