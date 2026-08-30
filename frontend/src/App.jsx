import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Sidebar from './components/Sidebar';
import Navbar from './components/Navbar';
import FileBrowser from './components/FileBrowser';
import TrashView from './components/TrashView';
import LoginRegister from './components/LoginRegister';
import api from './services/api';

const MainLayout = () => {
  const { user, loading } = useAuth();
  const [activeTab, setActiveTab] = useState('drive'); // 'drive' | 'trash'
  const [searchQuery, setSearchQuery] = useState('');
  const [viewMode, setViewMode] = useState('grid'); // 'grid' | 'list'
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  if (loading) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Loading VaultCloud Platform...
      </div>
    );
  }

  if (!user) {
    return <LoginRegister />;
  }

  const handleNewFolder = async () => {
    const folderName = prompt("Enter folder name:");
    if (!folderName) return;

    try {
      await api.post('/folders/', { name: folderName });
      setRefreshTrigger((prev) => prev + 1);
    } catch (e) {
      alert("Failed to create folder: " + (e.response?.data?.error || e.message));
    }
  };

  const handleDirectUpload = async (e) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (let i = 0; i < files.length; i++) {
      const formData = new FormData();
      formData.append('file', files[i]);
      try {
        await api.post('/files/', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
      } catch (err) {
        alert(`Failed to upload ${files[i].name}: ` + (err.response?.data?.error || err.message));
      }
    }
    setRefreshTrigger((prev) => prev + 1);
  };

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />

      <div className="main-content">
        <Navbar
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          viewMode={viewMode}
          setViewMode={setViewMode}
          onNewFolder={handleNewFolder}
          onUpload={handleDirectUpload}
        />

        <main className="content-body">
          {activeTab === 'drive' ? (
            <FileBrowser
              key={refreshTrigger}
              searchQuery={searchQuery}
              viewMode={viewMode}
              onRefreshStorage={() => setRefreshTrigger((prev) => prev + 1)}
            />
          ) : (
            <TrashView onRefreshStorage={() => setRefreshTrigger((prev) => prev + 1)} />
          )}
        </main>
      </div>
    </div>
  );
};

export default function App() {
  return (
    <AuthProvider>
      <MainLayout />
    </AuthProvider>
  );
}
