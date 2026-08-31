import React, { useState } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useTheme } from '../../context/ThemeContext';
import { UserRole } from '../../types/auth';

export const AuthGateModal: React.FC = () => {
  const { isAuthenticated, login, register } = useAuth();
  const { theme } = useTheme();

  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState<UserRole>('analyst');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (isAuthenticated) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === 'signin') {
        await login({ email, password });
      } else {
        await register({ fullname: fullName, email, password, role });
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Authentication failed. Please check credentials.');
    } finally {
      setLoading(false);
    }
  };

  const quickFill = (demoEmail: string, demoPw: string) => {
    setEmail(demoEmail);
    setPassword(demoPw);
    setError(null);
  };

  return (
    <div className="auth-gate" id="auth-gate" aria-modal="true" role="dialog" aria-labelledby="auth-gate-title">
      <form className="auth-card" id="auth-form" onSubmit={handleSubmit}>
        <div className="auth-brand">
          <div className="auth-brand-mark">
            <img
              className="brand-logo-img"
              src={theme === 'light' ? '/static/img/logo_black.png' : '/static/img/logo_white.png'}
              alt="AI Financial Controller Logo"
            />
          </div>
          <div>
            <div className="auth-brand-name">AI Financial Controller</div>
            <div className="auth-brand-sub">Autonomous 3-Way Settlement Engine</div>
          </div>
        </div>

        <div className="auth-tab-bar" id="auth-tab-bar">
          <button
            type="button"
            className={`auth-tab-btn ${mode === 'signin' ? 'active' : ''}`}
            id="auth-tab-signin"
            onClick={() => { setMode('signin'); setError(null); }}
          >
            Sign in
          </button>
          <button
            type="button"
            className={`auth-tab-btn ${mode === 'signup' ? 'active' : ''}`}
            id="auth-tab-signup"
            onClick={() => { setMode('signup'); setError(null); }}
          >
            Create account
          </button>
        </div>

        {mode === 'signin' ? (
          <div id="auth-signin-header">
            <h1 className="auth-title" id="auth-gate-title">Welcome back</h1>
            <p className="auth-subtitle">Dual-control reconciliation and exception approvals require an authenticated session.</p>
          </div>
        ) : (
          <div id="auth-signup-header">
            <h1 className="auth-title">Create an account</h1>
            <p className="auth-subtitle">Join your organization's three-way financial reconciliation team.</p>
          </div>
        )}

        {mode === 'signup' && (
          <div className="auth-field-group" id="auth-name-group">
            <label className="auth-label" htmlFor="auth-fullname">Full Name</label>
            <div className="auth-input-wrapper">
              <svg className="auth-field-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="8" r="4" />
                <path d="M20 21a8 8 0 1 0-16 0" />
              </svg>
              <input
                className="auth-input with-left-icon"
                id="auth-fullname"
                name="fullname"
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                placeholder="Jane Doe"
              />
            </div>
          </div>
        )}

        <div className="auth-field-group">
          <label className="auth-label" htmlFor="auth-email">Work Email</label>
          <div className="auth-input-wrapper">
            <svg className="auth-field-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="4" width="20" height="16" rx="2" />
              <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
            </svg>
            <input
              className="auth-input with-left-icon"
              id="auth-email"
              name="email"
              type="email"
              autoComplete="username"
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
        </div>

        {mode === 'signup' && (
          <div className="auth-field-group" id="auth-role-group">
            <label className="auth-label" htmlFor="auth-role">Organization Role</label>
            <div className="auth-input-wrapper">
              <svg className="auth-field-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              </svg>
              <select
                className="auth-input with-left-icon select-custom"
                id="auth-role"
                name="role"
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
              >
                <option value="analyst">Reconciliation Analyst (Maker)</option>
                <option value="approver">Financial Approver (Checker)</option>
                <option value="admin">System Controller (Admin)</option>
              </select>
            </div>
          </div>
        )}

        <div className="auth-field-group">
          <label className="auth-label" htmlFor="auth-password">Password</label>
          <div className="auth-input-wrapper">
            <svg className="auth-field-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <input
              className="auth-input with-left-icon with-right-icon"
              id="auth-password"
              name="password"
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button
              type="button"
              className="auth-pw-toggle-btn"
              id="auth-pw-toggle"
              aria-label="Toggle password visibility"
              title="Show password"
              onClick={() => setShowPassword(!showPassword)}
            >
              {showPassword ? (
                <svg id="auth-pw-icon-eye-off" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
                  <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
                  <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
                  <line x1="2" y1="2" x2="22" y2="22" />
                </svg>
              ) : (
                <svg id="auth-pw-icon-eye" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="auth-error" id="auth-error" role="alert">
            {error}
          </div>
        )}

        <button className="btn btn-primary auth-submit" id="auth-submit" type="submit" disabled={loading}>
          {loading ? 'Signing in...' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>

        <div className="auth-footnote" id="auth-footnote">
          <div className="auth-quick-header">
            <span>Demo Role Access</span>
          </div>
          <div className="auth-quick-actions">
            <button
              type="button"
              className="auth-quick-btn"
              onClick={() => quickFill('admin@acme.co', 'Admin@2026!')}
              title="Sign in as Administrator"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="8" r="4" />
                <path d="M20 21a8 8 0 1 0-16 0" />
              </svg>
              <span>Admin</span>
            </button>
            <button
              type="button"
              className="auth-quick-btn"
              onClick={() => quickFill('approver@acme.co', 'Approver@2026!')}
              title="Sign in as Approver (Checker)"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <polyline points="9 12 11 14 15 10" />
              </svg>
              <span>Approver</span>
            </button>
            <button
              type="button"
              className="auth-quick-btn"
              onClick={() => quickFill('analyst@acme.co', 'Analyst@2026!')}
              title="Sign in as Analyst (Maker)"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="20" x2="18" y2="10" />
                <line x1="12" y1="20" x2="12" y2="4" />
                <line x1="6" y1="20" x2="6" y2="14" />
              </svg>
              <span>Analyst</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};
