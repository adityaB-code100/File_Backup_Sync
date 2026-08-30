import React, { useEffect, useState } from 'react';
import { X, History, Download, RotateCcw, ShieldCheck } from 'lucide-react';
import api from '../services/api';

const VersionHistoryModal = ({ file, onClose, onRestored }) => {
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchRevisions = async () => {
    if (!file) return;
    try {
      const res = await api.get(`/files/${file.id}/revisions/`);
      setRevisions(res.data);
    } catch (e) {
      console.error("Failed to fetch version history", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRevisions();
  }, [file]);

  const handleDownloadRevision = async (rev) => {
    try {
      const res = await api.get(`/files/${file.id}/revisions/${rev.id}/content/`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `${file.name}.v${rev.version_number}`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (e) {
      alert("Failed to download past revision");
    }
  };

  const handleRestoreRevision = async (rev) => {
    if (!window.confirm(`Restore version ${rev.version_number} as current version?`)) return;
    try {
      await api.post(`/files/${file.id}/revisions/${rev.id}/restore/`);
      alert(`Version ${rev.version_number} restored successfully!`);
      if (onRestored) onRestored();
      onClose();
    } catch (e) {
      alert("Failed to restore past revision");
    }
  };

  const formatBytes = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <History size={22} color="var(--primary)" />
            <h3 style={{ fontSize: '1.2rem', fontWeight: '600' }}>Version History: {file.name}</h3>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: '6px' }}>
          {loading ? (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '20px' }}>Loading version history...</p>
          ) : revisions.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '20px' }}>No revisions available.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {revisions.map((rev) => {
                const isCurrent = file.current_version_id === rev.id || file.version_number === rev.version_number;
                return (
                  <div
                    key={rev.id}
                    className="glass-card"
                    style={{
                      padding: '16px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      borderLeft: isCurrent ? '4px solid var(--primary)' : '1px solid var(--border-color)'
                    }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                        <span style={{ fontWeight: '700', fontSize: '1rem' }}>v{rev.version_number}</span>
                        {isCurrent && (
                          <span style={{ fontSize: '0.75rem', background: 'var(--primary)', color: '#fff', padding: '2px 8px', borderRadius: '12px' }}>
                            Current Version
                          </span>
                        )}
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                          {new Date(rev.created_at).toLocaleString()}
                        </span>
                      </div>
                      <div style={{ fontSize: '0.85rem', color: 'var(--text-dim)', display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <span>Size: {formatBytes(rev.size)}</span>
                        <span className="hash-badge" title="SHA-256 Content Hash">
                          <ShieldCheck size={12} style={{ display: 'inline', marginRight: '4px' }} />
                          {rev.content_hash ? rev.content_hash.slice(0, 16) + '...' : 'N/A'}
                        </span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        className="btn btn-secondary"
                        onClick={() => handleDownloadRevision(rev)}
                        title="Download this version"
                        style={{ padding: '6px 12px' }}
                      >
                        <Download size={16} />
                      </button>

                      {!isCurrent && (
                        <button
                          className="btn btn-primary"
                          onClick={() => handleRestoreRevision(rev)}
                          title="Restore as current version"
                          style={{ padding: '6px 12px' }}
                        >
                          <RotateCcw size={16} />
                          Restore
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default VersionHistoryModal;
