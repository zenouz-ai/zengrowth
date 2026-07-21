import { Suspense, lazy } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/Layout'
import { SetupGate } from './components/SetupGate'

// Every page is code-split so the entry chunk stays at the router/auth shell;
// recharts (the heaviest dependency) loads only with the pages that chart.
const Setup = lazy(() => import('./pages/Setup').then((m) => ({ default: m.Setup })))
const AddJob = lazy(() => import('./pages/AddJob').then((m) => ({ default: m.AddJob })))
const Dashboard = lazy(() => import('./pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const DataGovernance = lazy(() =>
  import('./pages/DataGovernance').then((m) => ({ default: m.DataGovernance })),
)
const Discover = lazy(() => import('./pages/Discover').then((m) => ({ default: m.Discover })))
const Insights = lazy(() => import('./pages/Insights').then((m) => ({ default: m.Insights })))
const JobDetail = lazy(() => import('./pages/JobDetail').then((m) => ({ default: m.JobDetail })))
const Knowledge = lazy(() => import('./pages/Knowledge').then((m) => ({ default: m.Knowledge })))
const KnowledgeGraph = lazy(() =>
  import('./pages/KnowledgeGraph').then((m) => ({ default: m.KnowledgeGraph })),
)
const Library = lazy(() => import('./pages/Library').then((m) => ({ default: m.Library })))
const Login = lazy(() => import('./pages/Login').then((m) => ({ default: m.Login })))
const Observability = lazy(() =>
  import('./pages/Observability').then((m) => ({ default: m.Observability })),
)
const Pipeline = lazy(() => import('./pages/Pipeline').then((m) => ({ default: m.Pipeline })))
const PublicDashboard = lazy(() =>
  import('./pages/PublicDashboard').then((m) => ({ default: m.PublicDashboard })),
)
const ReviewQueue = lazy(() =>
  import('./pages/ReviewQueue').then((m) => ({ default: m.ReviewQueue })),
)
const Traces = lazy(() => import('./pages/Traces').then((m) => ({ default: m.Traces })))

function PageFallback() {
  return <div className="p-8 micro-label">loading…</div>
}

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Public / anonymous surface */}
            <Route path="/login" element={<Login />} />
            <Route path="/public" element={<PublicDashboard />} />

            {/* First-run wizard: protected, but outside the setup gate so it
                never redirects to itself. */}
            <Route
              path="/setup"
              element={
                <ProtectedRoute>
                  <Setup />
                </ProtectedRoute>
              }
            />

            {/* Operator surface */}
            <Route
              element={
                <ProtectedRoute>
                  <SetupGate>
                    <Layout />
                  </SetupGate>
                </ProtectedRoute>
              }
            >
              <Route path="/" element={<Dashboard />} />
              <Route path="/pipeline" element={<Pipeline />} />
              <Route path="/library" element={<Library />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/jobs/:id" element={<JobDetail />} />
              {/* Sub-destinations: reachable from within the four top-level pages
                  (Library, Insights, Jobs), not shown in the top nav. */}
              <Route path="/review" element={<ReviewQueue />} />
              <Route path="/add" element={<AddJob />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/knowledge" element={<Knowledge />} />
              <Route path="/knowledge/graph" element={<KnowledgeGraph />} />
              <Route path="/observability" element={<Observability />} />
              <Route path="/traces" element={<Traces />} />
              <Route path="/governance" element={<DataGovernance />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  )
}
