import { Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from './components/RequireAuth'
import { useAuth } from './auth/useAuth'
import { useBrands } from './brands/useBrands'
import BatchUploadReceipt from './pages/BatchUploadReceipt'
import BrandSelect from './pages/BrandSelect'
import Login from './pages/Login'
import NewBatchMarketplaces from './pages/NewBatchMarketplaces'
import NewBatchSubcategory from './pages/NewBatchSubcategory'
import NewBatchUpload from './pages/NewBatchUpload'
import NewBatchUploading from './pages/NewBatchUploading'
import NewBatchValidation from './pages/NewBatchValidation'
import Workspace from './pages/Workspace'

function RootRedirect() {
  const { user, loading } = useAuth()
  const { selectedBrand } = useBrands()

  if (loading) {
    return (
      <div className="app-loading">
        <p>Loading…</p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Navigate to={selectedBrand ? '/workspace' : '/brands'} replace />
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/brands"
        element={
          <RequireAuth>
            <BrandSelect />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace"
        element={
          <RequireAuth>
            <Workspace />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/new"
        element={
          <RequireAuth>
            <NewBatchSubcategory />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/new/upload"
        element={
          <RequireAuth>
            <NewBatchUpload />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/new/validation"
        element={
          <RequireAuth>
            <NewBatchValidation />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/new/uploading"
        element={
          <RequireAuth>
            <NewBatchUploading />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/new/marketplaces"
        element={
          <RequireAuth>
            <NewBatchMarketplaces />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace/batch/summer-tees"
        element={
          <RequireAuth>
            <BatchUploadReceipt />
          </RequireAuth>
        }
      />
      <Route path="*" element={<RootRedirect />} />
    </Routes>
  )
}

export default App
