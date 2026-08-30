import React, { useEffect, useState } from 'react';
import { X, Folder, Move } from 'lucide-react';
import api from '../services/api';

const MoveModal = ({ item, onClose, onMoved }) => {
  const [folders, setFolders] = useState([]);
  const [selectedParent, setSelectedParent] = useState('root');

  useEffect(() => {
    const loadFolders = async () => {
      try {
        const res = await api.get('/files/?trashed=false');
        const onlyFolders = res.data.results.filter(
          (i) => i.type === 'folder' && i.id !== item.id
        );
        setFolders(onlyFolders);
      } catch (e) {
        console.error("Failed to load folders for move modal", e);
      }
    };
    loadFolders();
  }, [item]);

  const handleMove = async () => {
    try {
      const endpoint = item.type === 'folder' ? `/folders/${item.id}/` : `/files/${item.id}/`;
      await api.patch(endpoint, {
        parent_id: selectedParent === 'root' ? null : selectedParent,
      });
      if (onMoved) onMoved();
      onClose();
    } catch (e) {
      alert("Failed to move item: " + (e.response?.data?.error || e.message));
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '480px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Move size={20} color="var(--primary)" />
            <h3 style={{ fontSize: '1.1rem', fontWeight: '600' }}>Move "{item.name}"</h3>
          </div>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer' }}>
            <X size={20} />
          </button>
        </div>

        <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)', marginBottom: '16px' }}>Select destination folder:</p>

        <div style={{ maxHeight: '250px', overflowY: 'auto', marginBottom: '24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div
            onClick={() => setSelectedParent('root')}
            className="glass-card"
            style={{
              padding: '12px 16px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              border: selectedParent === 'root' ? '2px solid var(--primary)' : '1px solid var(--border-color)'
            }}
          >
            <Folder size={18} color="#3b82f6" />
            <span style={{ fontWeight: '500' }}>My Drive (Root)</span>
          </div>

          {folders.map((f) => (
            <div
              key={f.id}
              onClick={() => setSelectedParent(f.id)}
              className="glass-card"
              style={{
                padding: '12px 16px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                border: selectedParent === f.id ? '2px solid var(--primary)' : '1px solid var(--border-color)'
              }}
            >
              <Folder size={18} color="#06b6d4" />
              <span>{f.name}</span>
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <button className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={handleMove}>Move Here</button>
        </div>
      </div>
    </div>
  );
};

export default MoveModal;
