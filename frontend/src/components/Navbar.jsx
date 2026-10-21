import React from 'react';
import { Search, FolderPlus, Upload, Grid, List, User as UserIcon } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const Navbar = ({ searchQuery, setSearchQuery, viewMode, setViewMode, onNewFolder, onUpload }) => {
  const { user } = useAuth();

  return (
    <header className="navbar">
      {/* Search Input */}
      <div style={{ position: 'relative', width: '320px' }}>
        <Search size={18} style={{ position: 'absolute', left: '14px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
        <input
          type="text"
          placeholder="Search files and folders..."
          className="input-field"
          style={{ paddingLeft: '40px' }}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* Action Controls & Active Account */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Active Authenticated Account Pill */}
        {user?.email && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'rgba(255, 255, 255, 0.05)',
              border: '1px solid var(--border-color)',
              borderRadius: '20px',
              padding: '6px 14px',
              fontSize: '0.85rem',
              color: 'var(--text-main)',
              fontWeight: '500'
            }}
            title={`Active Account: ${user.email} (ID: ${user.id})`}
          >
            <UserIcon size={14} color="var(--primary)" />
            <span style={{ maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {user.email}
            </span>
          </div>
        )}

        {/* Grid/List View Toggle */}
        <div style={{ display: 'flex', background: 'var(--bg-input)', padding: '4px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
          <button
            onClick={() => setViewMode('grid')}
            style={{
              background: viewMode === 'grid' ? 'var(--primary)' : 'transparent',
              color: viewMode === 'grid' ? '#fff' : 'var(--text-muted)',
              border: 'none',
              borderRadius: '6px',
              padding: '6px 10px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center'
            }}
            title="Grid View"
          >
            <Grid size={16} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            style={{
              background: viewMode === 'list' ? 'var(--primary)' : 'transparent',
              color: viewMode === 'list' ? '#fff' : 'var(--text-muted)',
              border: 'none',
              borderRadius: '6px',
              padding: '6px 10px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center'
            }}
            title="List View"
          >
            <List size={16} />
          </button>
        </div>

        {/* Create Folder Button */}
        <button className="btn btn-secondary" onClick={onNewFolder}>
          <FolderPlus size={18} />
          New Folder
        </button>

        {/* Upload File Button */}
        <label className="btn btn-primary" style={{ margin: 0, cursor: 'pointer' }}>
          <Upload size={18} />
          Upload File
          <input type="file" onChange={onUpload} style={{ display: 'none' }} />
        </label>
      </div>
    </header>
  );
};

export default Navbar;
