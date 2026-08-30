import React, { useState, useEffect } from 'react';
import {
  Folder,
  FileText,
  FileCode,
  Image as ImageIcon,
  Film,
  Music,
  Archive,
  Download,
  Edit2,
  Trash2,
  History,
  Move,
  ChevronRight,
  UploadCloud,
  File as GenericFile
} from 'lucide-react';
import api from '../services/api';
import VersionHistoryModal from './VersionHistoryModal';
import MoveModal from './MoveModal';

const FileBrowser = ({ searchQuery, viewMode, onRefreshStorage }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [breadcrumbs, setBreadcrumbs] = useState([{ id: 'root', name: 'My Drive' }]);
  const [currentFolderId, setCurrentFolderId] = useState('root');
  const [dragOver, setDragOver] = useState(false);

  // Modals state
  const [versionModalFile, setVersionModalFile] = useState(null);
  const [moveModalItem, setMoveModalItem] = useState(null);

  const fetchItems = async (folderId, search) => {
    setLoading(true);
    try {
      let url = '/files/?trashed=false';
      if (search) {
        url += `&q=${encodeURIComponent(search)}`;
      } else if (folderId && folderId !== 'root') {
        url += `&parent_id=${folderId}`;
      } else {
        url += '&parent_id=root';
      }

      const res = await api.get(url);
      setItems(res.data.results || []);
    } catch (e) {
      console.error("Error fetching files:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchItems(currentFolderId, searchQuery);
  }, [currentFolderId, searchQuery]);

  const handleOpenFolder = (folder) => {
    setBreadcrumbs((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setCurrentFolderId(folder.id);
  };

  const handleBreadcrumbClick = (index) => {
    const newCrumbs = breadcrumbs.slice(0, index + 1);
    setBreadcrumbs(newCrumbs);
    setCurrentFolderId(newCrumbs[newCrumbs.length - 1].id);
  };

  // Upload handler (drag-and-drop or file input)
  const uploadFiles = async (filesToUpload) => {
    for (let i = 0; i < filesToUpload.length; i++) {
      const file = filesToUpload[i];
      const formData = new FormData();
      formData.append('file', file);
      if (currentFolderId && currentFolderId !== 'root') {
        formData.append('parent_id', currentFolderId);
      }

      try {
        await api.post('/files/', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
      } catch (e) {
        alert(`Failed to upload ${file.name}: ` + (e.response?.data?.error || e.message));
      }
    }
    fetchItems(currentFolderId, searchQuery);
    if (onRefreshStorage) onRefreshStorage();
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFiles(e.dataTransfer.files);
    }
  };

  const handleDownload = async (item) => {
    if (item.type === 'folder') return;
    try {
      const res = await api.get(`/files/${item.id}/content/`, {
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', item.name);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (e) {
      alert("Failed to download file.");
    }
  };

  // Optimistic UI updates for Rename & Delete
  const handleRename = async (item) => {
    const newName = prompt("Enter new name:", item.name);
    if (!newName || newName === item.name) return;

    // Optimistic update
    const previousItems = [...items];
    setItems(items.map(i => i.id === item.id ? { ...i, name: newName } : i));

    try {
      const endpoint = item.type === 'folder' ? `/folders/${item.id}/` : `/files/${item.id}/`;
      await api.patch(endpoint, { name: newName });
    } catch (e) {
      setItems(previousItems); // Rollback
      alert("Failed to rename item.");
    }
  };

  const handleDelete = async (item) => {
    if (!window.confirm(`Move "${item.name}" to trash?`)) return;

    // Optimistic update
    const previousItems = [...items];
    setItems(items.filter(i => i.id !== item.id));

    try {
      const endpoint = item.type === 'folder' ? `/folders/${item.id}/` : `/files/${item.id}/`;
      await api.delete(endpoint);
      if (onRefreshStorage) onRefreshStorage();
    } catch (e) {
      setItems(previousItems); // Rollback
      alert("Failed to delete item.");
    }
  };

  const getFileIcon = (filename, type) => {
    if (type === 'folder') return <Folder size={32} color="#06b6d4" />;
    const ext = filename.split('.').pop().toLowerCase();
    if (['jpg', 'jpeg', 'png', 'gif', 'svg', 'webp'].includes(ext)) return <ImageIcon size={32} color="#10b981" />;
    if (['mp4', 'mkv', 'avi', 'mov'].includes(ext)) return <Film size={32} color="#f43f5e" />;
    if (['mp3', 'wav', 'flac'].includes(ext)) return <Music size={32} color="#8b5cf6" />;
    if (['zip', 'rar', 'tar', 'gz', '7z'].includes(ext)) return <Archive size={32} color="#f59e0b" />;
    if (['js', 'py', 'html', 'css', 'json', 'ts', 'jsx'].includes(ext)) return <FileCode size={32} color="#3b82f6" />;
    return <FileText size={32} color="#9ca3af" />;
  };

  const formatBytes = (bytes) => {
    if (!bytes) return '-';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      style={{ position: 'relative', minHeight: 'calc(100vh - 150px)' }}
    >
      {/* Drag overlay notice */}
      {dragOver && (
        <div style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(59, 130, 246, 0.15)',
          border: '2px dashed var(--primary)',
          borderRadius: '16px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 20,
          backdropFilter: 'blur(4px)'
        }}>
          <UploadCloud size={64} color="var(--primary)" />
          <h3 style={{ fontSize: '1.4rem', marginTop: '12px' }}>Drop files to upload</h3>
        </div>
      )}

      {/* Breadcrumb Navigation */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
        {breadcrumbs.map((b, idx) => (
          <React.Fragment key={b.id}>
            {idx > 0 && <ChevronRight size={16} color="var(--text-dim)" />}
            <button
              onClick={() => handleBreadcrumbClick(idx)}
              style={{
                background: 'transparent',
                border: 'none',
                color: idx === breadcrumbs.length - 1 ? 'var(--text-main)' : 'var(--text-muted)',
                fontWeight: idx === breadcrumbs.length - 1 ? '600' : '400',
                cursor: 'pointer',
                fontSize: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              {idx === 0 && <Folder size={18} color="var(--primary)" />}
              {b.name}
            </button>
          </React.Fragment>
        ))}
      </div>

      {/* Content Rendering */}
      {loading ? (
        <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px' }}>Loading items...</p>
      ) : items.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
          <GenericFile size={48} style={{ opacity: 0.3, marginBottom: '12px' }} />
          <p style={{ fontSize: '1.1rem' }}>No files or folders found in this location.</p>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-dim)', marginTop: '6px' }}>
            Drag & drop files here or click "Upload File" above.
          </p>
        </div>
      ) : viewMode === 'grid' ? (
        /* GRID VIEW */
        <div className="file-grid">
          {items.map((item) => (
            <div
              key={item.id}
              className="glass-card"
              style={{ padding: '20px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', cursor: item.type === 'folder' ? 'pointer' : 'default' }}
              onClick={() => item.type === 'folder' && handleOpenFolder(item)}
            >
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                  {getFileIcon(item.name, item.type)}
                  {item.type === 'file' && (
                    <span className="hash-badge" title="v1 SHA-256">
                      {item.content_hash ? item.content_hash.slice(0, 8) : 'File'}
                    </span>
                  )}
                </div>
                <h4 style={{ fontSize: '0.95rem', fontWeight: '600', marginBottom: '6px', wordBreak: 'break-word' }}>
                  {item.name}
                </h4>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {item.type === 'file' ? formatBytes(item.size) : 'Folder'}
                </div>
              </div>

              {/* Action Buttons */}
              <div
                style={{ display: 'flex', gap: '6px', marginTop: '16px', borderTop: '1px solid var(--border-color)', paddingTop: '12px' }}
                onClick={(e) => e.stopPropagation()}
              >
                {item.type === 'file' && (
                  <>
                    <button className="btn btn-secondary" style={{ padding: '6px' }} title="Download" onClick={() => handleDownload(item)}>
                      <Download size={15} />
                    </button>
                    <button className="btn btn-secondary" style={{ padding: '6px' }} title="Version History" onClick={() => setVersionModalFile(item)}>
                      <History size={15} />
                    </button>
                  </>
                )}
                <button className="btn btn-secondary" style={{ padding: '6px' }} title="Rename" onClick={() => handleRename(item)}>
                  <Edit2 size={15} />
                </button>
                <button className="btn btn-secondary" style={{ padding: '6px' }} title="Move" onClick={() => setMoveModalItem(item)}>
                  <Move size={15} />
                </button>
                <button className="btn btn-secondary" style={{ padding: '6px', color: 'var(--accent-rose)' }} title="Move to Trash" onClick={() => handleDelete(item)}>
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* LIST VIEW */
        <div className="file-list">
          {items.map((item) => (
            <div
              key={item.id}
              className="glass-card"
              style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: item.type === 'folder' ? 'pointer' : 'default' }}
              onClick={() => item.type === 'folder' && handleOpenFolder(item)}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1 }}>
                {getFileIcon(item.name, item.type)}
                <div>
                  <div style={{ fontWeight: '600', fontSize: '0.95rem' }}>{item.name}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Updated {new Date(item.updated_at || item.created_at).toLocaleDateString()}
                  </div>
                </div>
              </div>

              <div style={{ width: '120px', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                {item.type === 'file' ? formatBytes(item.size) : 'Folder'}
              </div>

              {item.type === 'file' && (
                <div style={{ width: '140px' }}>
                  <span className="hash-badge" title="SHA-256 Hash">
                    {item.content_hash ? item.content_hash.slice(0, 10) + '...' : ''}
                  </span>
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }} onClick={(e) => e.stopPropagation()}>
                {item.type === 'file' && (
                  <>
                    <button className="btn btn-secondary" style={{ padding: '6px 10px' }} title="Download" onClick={() => handleDownload(item)}>
                      <Download size={15} />
                    </button>
                    <button className="btn btn-secondary" style={{ padding: '6px 10px' }} title="Revisions" onClick={() => setVersionModalFile(item)}>
                      <History size={15} />
                    </button>
                  </>
                )}
                <button className="btn btn-secondary" style={{ padding: '6px 10px' }} title="Rename" onClick={() => handleRename(item)}>
                  <Edit2 size={15} />
                </button>
                <button className="btn btn-secondary" style={{ padding: '6px 10px' }} title="Move" onClick={() => setMoveModalItem(item)}>
                  <Move size={15} />
                </button>
                <button className="btn btn-secondary" style={{ padding: '6px 10px', color: 'var(--accent-rose)' }} title="Trash" onClick={() => handleDelete(item)}>
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Revisions Modal */}
      {versionModalFile && (
        <VersionHistoryModal
          file={versionModalFile}
          onClose={() => setVersionModalFile(null)}
          onRestored={() => fetchItems(currentFolderId, searchQuery)}
        />
      )}

      {/* Move Modal */}
      {moveModalItem && (
        <MoveModal
          item={moveModalItem}
          onClose={() => setMoveModalItem(null)}
          onMoved={() => fetchItems(currentFolderId, searchQuery)}
        />
      )}
    </div>
  );
};

export default FileBrowser;
