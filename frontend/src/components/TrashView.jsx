import React, { useEffect, useState } from 'react';
import { Trash2, RotateCcw, XCircle, Folder, FileText } from 'lucide-react';
import api from '../services/api';

const TrashView = ({ onRefreshStorage }) => {
  const [trashedItems, setTrashedItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchTrash = async () => {
    setLoading(true);
    try {
      const res = await api.get('/files/?trashed=true');
      setTrashedItems(res.data.results || []);
    } catch (e) {
      console.error("Failed to load trash items", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrash();
  }, []);

  const handleRestore = async (item) => {
    try {
      const endpoint = item.type === 'folder' ? `/folders/${item.id}/` : `/files/${item.id}/restore/`;
      if (item.type === 'folder') {
        await api.patch(endpoint, { deleted: false });
      } else {
        await api.post(endpoint);
      }
      fetchTrash();
      if (onRefreshStorage) onRefreshStorage();
    } catch (e) {
      alert("Failed to restore item.");
    }
  };

  const handlePermanentDelete = async (item) => {
    if (!window.confirm(`Permanently delete "${item.name}"? This action cannot be undone.`)) return;

    try {
      const endpoint = item.type === 'folder' ? `/folders/${item.id}/` : `/files/${item.id}/permanent/`;
      await api.delete(endpoint);
      fetchTrash();
      if (onRefreshStorage) onRefreshStorage();
    } catch (e) {
      alert("Failed to permanently delete item.");
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
        <Trash2 size={24} color="var(--accent-rose)" />
        <h2 style={{ fontSize: '1.4rem', fontWeight: '700' }}>Trash / Recycled Items</h2>
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px' }}>Loading trash...</p>
      ) : trashedItems.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
          <Trash2 size={48} style={{ opacity: 0.2, marginBottom: '12px' }} />
          <p style={{ fontSize: '1.1rem' }}>Trash is empty.</p>
        </div>
      ) : (
        <div className="file-list">
          {trashedItems.map((item) => (
            <div
              key={item.id}
              className="glass-card"
              style={{ padding: '14px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                {item.type === 'folder' ? (
                  <Folder size={28} color="#06b6d4" />
                ) : (
                  <FileText size={28} color="#9ca3af" />
                )}
                <div>
                  <div style={{ fontWeight: '600', fontSize: '1rem' }}>{item.name}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Deleted item ({item.type})
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '10px' }}>
                <button
                  className="btn btn-secondary"
                  onClick={() => handleRestore(item)}
                  style={{ padding: '8px 14px' }}
                  title="Restore"
                >
                  <RotateCcw size={16} />
                  Restore
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => handlePermanentDelete(item)}
                  style={{ padding: '8px 14px' }}
                  title="Delete Permanently"
                >
                  <XCircle size={16} />
                  Delete Permanently
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default TrashView;
