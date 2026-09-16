import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import RequireBrand from './components/RequireBrand'
import { useAuth } from './auth/useAuth'
import { useBrands } from './brands/useBrands'
import { brandPath, loginPath } from './lib/brandPath'
import BrandSelect from './pages/BrandSelect'
import Login from './pages/Login'
import BatchContent from './pages/BatchContent'
import NewBatchMarketplaces from './pages/NewBatchMarketplaces'
import NewBatchSubcategory from './pages/NewBatchSubcategory'
import NewBatchUpload from './pages/NewBatchUpload'
import NewBatchUploading from './pages/NewBatchUploading'
import NewBatchValidation from './pages/NewBatchValidation'
import Workspace from './pages/Workspace'
import UserManagement from './pages/UserManagement'

function RootRedirect() {
  const { user, loading } = useAuth()
  const { selectedBrand } = useBrands()
  const location = useLocation()

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (!user) {
    const next = `${location.pathname}${location.search}`
    return <Navigate to={loginPath(next)} replace />
  }

  if (selectedBrand) {
    return <Navigate to={brandPath(selectedBrand.id, '/workspace')} replace />
  }

  return <Navigate to="/brands" replace />
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<RequireAuth />}>
        <Route path="/brands" element={<BrandSelect />} />
        <Route path="/b/:brandId" element={<RequireBrand />}>
          <Route path="workspace" element={<Workspace />} />
          <Route path="workspace/users" element={<UserManagement />} />
          <Route path="workspace/new" element={<NewBatchSubcategory />} />
          <Route path="workspace/new/upload" element={<NewBatchUpload />} />
          <Route path="workspace/new/validation" element={<NewBatchValidation />} />
          <Route path="workspace/new/uploading" element={<NewBatchUploading />} />
          <Route path="workspace/new/marketplaces" element={<NewBatchMarketplaces />} />
          <Route path="batches/preview/:jobExternalId" element={<BatchContent />} />
        </Route>
      </Route>
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}

export default App
