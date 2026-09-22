// User-facing navigation labels — keep in one place so nav, guides, and pages stay aligned.

export type NavLink = { readonly to: string; readonly label: string }

export const NAV = {
  // Four top-level destinations that map to the journey (PS-P3).
  dashboard: { to: '/', label: 'Home' },
  jobs: { to: '/pipeline', label: 'Jobs' },
  library: { to: '/library', label: 'Library' },
  insights: { to: '/insights', label: 'Insights' },

  // Sub-destinations: reachable from within the four, not shown in the top nav.
  approveFacts: { to: '/review', label: 'Approve facts' },
  addJob: { to: '/add', label: 'Add job' },
  findJobs: { to: '/discover', label: 'Find jobs' },
  documents: { to: '/knowledge', label: 'Documents' },
  documentGraph: { to: '/knowledge/graph', label: 'Document graph' },
  usage: { to: '/observability', label: 'Usage' },
  runLog: { to: '/traces', label: 'Run log' },
  dataSources: { to: '/governance', label: 'Data sources' },
  setup: { to: '/setup', label: 'Setup' },
} as const satisfies Record<string, NavLink>

// The four top-level destinations a phone can hold without a manual.
export const PRIMARY_NAV: readonly NavLink[] = [NAV.dashboard, NAV.jobs, NAV.library, NAV.insights]

export const FLAT_NAV_LINKS: readonly NavLink[] = PRIMARY_NAV
