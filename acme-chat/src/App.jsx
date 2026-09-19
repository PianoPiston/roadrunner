import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ArchiveProvider } from './lib/ArchiveContext.jsx';
import Home from './pages/Home.jsx';
import DevView from './pages/DevView.jsx';
import ManagerView from './pages/ManagerView.jsx';
import MarketingView from './pages/MarketingView.jsx';
import './App.css';

export default function App() {
  return (
    <BrowserRouter>
      <ArchiveProvider>
        <div className="app">
          <div className="main-panel">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/dev" element={<DevView />} />
              <Route path="/manager" element={<ManagerView />} />
              <Route path="/marketing" element={<MarketingView />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </div>
        </div>
      </ArchiveProvider>
    </BrowserRouter>
  );
}
