import React from 'react';
import { Search, FolderPlus, Upload, Grid, List } from 'lucide-react';

const Navbar = ({ searchQuery, setSearchQuery, viewMode, setViewMode, onNewFolder, onUpload }) => {
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

      {/* Action Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
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
