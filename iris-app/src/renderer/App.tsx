import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ThemeProvider } from './components/shared/ThemeProvider'
import { ProjectsPage } from './pages/ProjectsPage'
import { WorkspacePage } from './pages/WorkspacePage'

export default function App() {
  return (
    <ThemeProvider defaultTheme="system" storageKey="iris-theme">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/project/:name" element={<WorkspacePage />} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}
