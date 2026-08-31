import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { ViewType } from './Sidebar';

interface TopNavProps {
  currentView: ViewType;
  onToggleSidebar: () => void;
  onOpenQa: () => void;
}

export const TopNav: React.FC<TopNavProps> = ({
  currentView,
  onToggleSidebar,
  onOpenQa,
}) => {
  const { user, logout } = useAuth();

  const getBreadcrumbCategory = (view: ViewType) => {
    switch (view) {
      case 'overview':
      case 'workflow':
        return 'Dashboards';
      case 'exceptions':
      case 'audit':
        return 'Governance & Risk';
      case 'agents':
        return 'AI Intelligence Suite';
      default:
        return 'Dashboards';
    }
  };

  const getBreadcrumbTitle = (view: ViewType) => {
    switch (view) {
      case 'overview':
        return 'Overview';
      case 'workflow':
        return 'Reconciliation';
      case 'exceptions':
        return 'Exceptions Queue';
      case 'audit':
        return 'Audit Trail (SHA-256)';
      case 'agents':
        return 'Specialized Reasoning Agents';
      default:
        return 'Overview';
    }
  };

  const getRoleBadge = (role?: string) => {
    switch (role) {
      case 'approver':
        return 'Approver (Checker)';
      case 'admin':
        return 'Admin (Controller)';
      case 'analyst':
      default:
        return 'Analyst (Maker)';
    }
  };

  const userInitial = user?.full_name ? user.full_name.charAt(0).toUpperCase() : user?.email ? user.email.charAt(0).toUpperCase() : 'A';

  return (
    <header className="top-nav-bar">
      <div className="breadcrumb-trail">
        <a className="breadcrumb-item breadcrumb-home" id="breadcrumb-home">
          <svg className="breadcrumb-home-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
            <polyline points="9 22 9 12 15 12 15 22"></polyline>
          </svg>
          <span id="breadcrumb-category">{getBreadcrumbCategory(currentView)}</span>
        </a>
        <span className="breadcrumb-sep">/</span>
        <span className="breadcrumb-active" id="breadcrumb-current-title">{getBreadcrumbTitle(currentView)}</span>
      </div>

      <div className="top-nav-actions">
        <button
          className="header-search-pill"
          id="btn-open-qa-pill"
          title="Open AI Financial Investigator (⌘K)"
          aria-label="Open AI Financial Investigator"
          onClick={onOpenQa}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <span>Ask AI Assistant</span>
          <kbd className="reui-pill-kbd" style={{ fontSize: '0.65rem', background: 'var(--bg-card)', padding: '0.1rem 0.35rem', borderRadius: '4px', border: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
            ⌘K
          </kbd>
        </button>

        {user && (
          <div
            id="header-role-session"
            onClick={logout}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              padding: '0.25rem 0.65rem',
              borderRadius: '20px',
              fontSize: '0.75rem',
              cursor: 'pointer',
            }}
            title="Click to sign out"
          >
            <span
              id="header-user-role-tag"
              className="badge-min badge-gray"
              style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}
            >
              {getRoleBadge(user.role)}
            </span>
            <span id="header-user-email" style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
              {user.email}
            </span>
          </div>
        )}

        <div className="avatar-circle" id="header-avatar" title="Current session" onClick={logout}>
          {userInitial}
          <div className="avatar-online-dot"></div>
        </div>
      </div>
    </header>
  );
};
