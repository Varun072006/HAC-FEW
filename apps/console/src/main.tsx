import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter, Navigate, useLocation } from 'react-router-dom'
import './styles/index.css'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AppShell } from './layout/AppShell'
import { ApiError } from './api/client'
import { Loading } from './components/ui'
import Login from './pages/Login'
import Overview from './pages/Overview'
import Workflows from './pages/Workflows'
import WorkflowBuilder from './pages/WorkflowBuilder'
import PlanPage from './pages/Plan'
import Runs from './pages/Runs'
import RunDetail from './pages/RunDetail'
import Approvals from './pages/Approvals'
import Agents from './pages/Agents'
import Connectors from './pages/Connectors'
import Policies from './pages/Policies'
import Observability from './pages/Observability'
import Settings from './pages/Settings'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 3000,
      refetchOnWindowFocus: true,
      // Client errors (401/403/404/422) will not succeed on retry.
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
    },
  },
})

function Protected() {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading label="Restoring session" />
  if (!user) return <Login key={loc.pathname} />
  return <AppShell />
}

function NotFound() {
  return <div className="py-16 text-center"><h1 className="text-xl">Page not found</h1><p className="mt-1 text-sm text-ink-2">That address does not exist in this console.</p></div>
}

const router = createBrowserRouter([
  {
    element: <Protected />,
    children: [
      { path: '/', element: <Overview /> },
      { path: '/workflows', element: <Workflows /> },
      { path: '/workflows/:id', element: <WorkflowBuilder /> },
      { path: '/plan', element: <PlanPage /> },
      { path: '/runs', element: <Runs /> },
      { path: '/runs/:id', element: <RunDetail /> },
      { path: '/approvals', element: <Approvals /> },
      { path: '/agents', element: <Agents /> },
      { path: '/connectors', element: <Connectors /> },
      { path: '/policies', element: <Policies /> },
      { path: '/observability', element: <Observability /> },
      { path: '/settings', element: <Settings /> },
      { path: '/overview', element: <Navigate to="/" replace /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)
