import React, { useEffect, useState } from 'react';
import { HardDrive, Trash2, Cloud, LogOut, ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';

const Sidebar = ({ activeTab, setActiveTab }) => {
  const { user, logout } = useAuth();
  const [storageInfo, setStorageInfo] = useState({
    storage_used_bytes: 0,
    storage_quota_bytes: 5368709120,
    usage_percentage: 0,
  });

  const fetchStorage = async () => {
    try {
      const res = await api.get('/storage/usage/');
      setStorageInfo(res.data);
    } catch (e) {
      console.error("Failed to fetch storage usage", e);
    }
  };

  useEffect(() => {
    fetchStorage();
    const interval = setInterval(fetchStorage, 10000);
    return () => clearInterval(interval);
  }, []);

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const isWarning = storageInfo.usage_percentage > 85;

  return (
    <aside className="sidebar">
      {/* Brand Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '32px' }}>
        <div style={{
          width: '42px',
          height: '42px',
          borderRadius: '10px',
          background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 15px rgba(59, 130, 246, 0.4)'
        }}>
          <Cloud size={24} color="#fff" />
        </div>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: '700', letterSpacing: '-0.5px' }}>VaultCloud</h2>
          <span style={{ fontSize: '0.75rem', color: '#10b981', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <ShieldCheck size={12} /> Encrypted Storage
          </span>
        </div>
      </div>

      {/* Navigation Links */}
      <nav style={{ display: 'flex', flexDirection: 'column', gap: '6px', flex: 1 }}>
        <button
          onClick={() => setActiveTab('drive')}
          className={`btn ${activeTab === 'drive' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ justifyContent: 'flex-start', padding: '12px 16px', border: activeTab === 'drive' ? 'none' : '1px solid transparent' }}
        >
          <HardDrive size={18} />
          My Drive
        </button>

        <button
          onClick={() => setActiveTab('trash')}
          className={`btn ${activeTab === 'trash' ? 'btn-primary' : 'btn-secondary'}`}
          style={{ justifyContent: 'flex-start', padding: '12px 16px', border: activeTab === 'trash' ? 'none' : '1px solid transparent' }}
        >
          <Trash2 size={18} />
          Trash / Recycled
        </button>
      </nav>

      {/* Storage Indicator */}
      <div style={{
        background: 'rgba(255, 255, 255, 0.03)',
        border: '1px solid var(--border-color)',
        borderRadius: '12px',
        padding: '16px',
        marginBottom: '20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
          <span style={{ color: 'var(--text-muted)' }}>Storage</span>
          <span style={{ fontWeight: '600' }}>{storageInfo.usage_percentage}%</span>
        </div>
        <div className="progress-bar" style={{ marginBottom: '10px' }}>
          <div
            className={`progress-fill ${isWarning ? 'warning' : ''}`}
            style={{ width: `${Math.min(storageInfo.usage_percentage, 100)}%` }}
          />
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-dim)', textAlign: 'right' }}>
          {formatBytes(storageInfo.storage_used_bytes)} / {formatBytes(storageInfo.storage_quota_bytes)}
        </div>
      </div>

      {/* User Footer */}
      <div style={{
        borderTop: '1px solid var(--border-color)',
        paddingTop: '16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '160px' }}>
          <div style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)' }}>
            {user?.email}
          </div>
        </div>
        <button
          onClick={logout}
          title="Sign Out"
          style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '6px' }}
        >
          <LogOut size={18} />
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
