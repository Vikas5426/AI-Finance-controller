import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';

export type ViewType = 'overview' | 'workflow' | 'exceptions' | 'audit' | 'agents';

interface SidebarProps {
  currentView: ViewType;
  onSelectView: (view: ViewType) => void;
  exceptionsCount: number;
  onOpenSop: () => void;
  onOpenManual: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentView,
  onSelectView,
  exceptionsCount,
  onOpenSop,
  onOpenManual,
  isOpen,
  onClose,
}) => {
  const { theme, toggleTheme } = useTheme();

  return (
    <>
      <div
        id="sidebar-overlay"
        className={`sidebar-overlay ${isOpen ? 'active' : ''}`}
        aria-hidden={!isOpen}
        onClick={onClose}
      />
      <aside className={`app-sidebar ${isOpen ? 'open' : ''}`} id="app-sidebar">
        <nav className="sidebar-nav">
          <div className="nav-group-title">Dashboards</div>
          <a
            className={`nav-link ${currentView === 'overview' ? 'active' : ''}`}
            id="nav-overview"
            onClick={() => { onSelectView('overview'); onClose(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
            </svg>
            <span className="nav-label">Overview</span>
          </a>
          <a
            className={`nav-link ${currentView === 'workflow' ? 'active' : ''}`}
            id="nav-workflow"
            onClick={() => { onSelectView('workflow'); onClose(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
            <span className="nav-label">Reconciliation</span>
          </a>

          <div className="nav-group-title">Governance & Risk</div>
          <a
            className={`nav-link ${currentView === 'exceptions' ? 'active' : ''}`}
            id="nav-exceptions"
            onClick={() => { onSelectView('exceptions'); onClose(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span className="nav-label">Exceptions Queue</span>
            <span
              className="nav-badge-soon"
              id="nav-badge-excs-count"
              style={{ background: 'rgba(245,158,11,0.15)', color: 'var(--accent-amber)' }}
            >
              {exceptionsCount} Held
            </span>
          </a>
          <a
            className={`nav-link ${currentView === 'audit' ? 'active' : ''}`}
            id="nav-audit"
            onClick={() => { onSelectView('audit'); onClose(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
            </svg>
            <span className="nav-label">Audit Trail (SHA-256)</span>
          </a>

          <div className="nav-group-title">AI Intelligence Suite</div>
          <a
            className={`nav-link ${currentView === 'agents' ? 'active' : ''}`}
            id="nav-agents"
            onClick={() => { onSelectView('agents'); onClose(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="4" y="4" width="16" height="16" rx="3" />
              <rect x="9" y="9" width="6" height="6" />
              <line x1="9" y1="1" x2="9" y2="4" />
              <line x1="15" y1="1" x2="15" y2="4" />
              <line x1="9" y1="20" x2="9" y2="23" />
              <line x1="15" y1="20" x2="15" y2="23" />
              <line x1="20" y1="9" x2="23" y2="9" />
              <line x1="20" y1="14" x2="23" y2="14" />
              <line x1="1" y1="9" x2="4" y2="9" />
              <line x1="1" y1="14" x2="4" y2="14" />
            </svg>
            <span className="nav-label">Reasoning Agents</span>
            <span className="nav-badge-soon" style={{ background: 'rgba(56,189,248,0.15)', color: 'var(--accent-cyan)' }}>
              5 Agents
            </span>
          </a>
        </nav>

        <div className="sidebar-bottom-menu">
          <a className="nav-link" id="nav-settings" onClick={onOpenSop}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="4" width="18" height="18" rx="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <span className="nav-label">SOP Rules Engine</span>
          </a>
          <a className="nav-link" id="nav-docs" onClick={onOpenManual}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
            </svg>
            <span className="nav-label">Accounting Manual</span>
          </a>
        </div>

        {/* Exact Original Sidebar Footer */}
        <div className="sidebar-footer">
          <div className="sidebar-brand-wrapper">
            <div className="sidebar-brand-mark">
              <img
                className="brand-logo-img"
                src={theme === 'light' ? '/static/img/logo_black.png' : '/static/img/logo_white.png'}
                alt="AI Finance Controller Logo"
              />
            </div>
            <div className="sidebar-brand-text">
              <div className="sidebar-brand-title">AI Finance</div>
              <div className="sidebar-brand-sub">Controller Pro</div>
            </div>
          </div>
          <button
            className="icon-btn theme-toggle-btn"
            id="theme-toggle-btn"
            title="Toggle Dark / Light Mode"
            aria-label="Toggle Dark / Light Mode"
            onClick={toggleTheme}
          >
            {theme === 'dark' ? (
              <svg id="theme-icon" className="theme-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5"></circle>
                <line x1="12" y1="1" x2="12" y2="3"></line>
                <line x1="12" y1="21" x2="12" y2="23"></line>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                <line x1="1" y1="12" x2="3" y2="12"></line>
                <line x1="21" y1="12" x2="23" y2="12"></line>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
              </svg>
            ) : (
              <svg id="theme-icon" className="theme-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
              </svg>
            )}
          </button>
        </div>
      </aside>
    </>
  );
};
