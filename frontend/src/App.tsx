import React, { useState, useEffect } from 'react';
import { Sidebar, ViewType } from './components/layout/Sidebar';
import { TopNav } from './components/layout/TopNav';
import { OverviewView } from './views/OverviewView';
import { WorkflowView } from './views/WorkflowView';
import { ExceptionsView } from './views/ExceptionsView';
import { AuditView } from './views/AuditView';
import { AgentsView } from './views/AgentsView';

import { AuthGateModal } from './components/auth/AuthGateModal';
import { SOPRulesDrawer } from './components/drawers/SOPRulesDrawer';
import { AccountingManualDrawer } from './components/drawers/AccountingManualDrawer';
import { ExceptionInvestigateDrawer } from './components/drawers/ExceptionInvestigateDrawer';
import { AIChatbotModal } from './components/qa/AIChatbotModal';

import { useAuth } from './context/AuthContext';
import { batchService, ActiveBatchResponse } from './services/batchService';
import { ExceptionRecord } from './types/exception';
import { CanonicalTransaction } from './types/transaction';

export const App: React.FC = () => {
  const { isAuthenticated } = useAuth();

  const [currentView, setCurrentView] = useState<ViewType>('overview');
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  // Global Drawers & Modals
  const [isSopOpen, setIsSopOpen] = useState(false);
  const [isManualOpen, setIsManualOpen] = useState(false);
  const [isQaOpen, setIsQaOpen] = useState(false);
  const [investigatingException, setInvestigatingException] = useState<ExceptionRecord | null>(null);

  // Active Batch & Telemetry State
  const [activeBatch, setActiveBatch] = useState<ActiveBatchResponse | null>(null);
  const [exceptionsCount, setExceptionsCount] = useState<number>(36);

  useEffect(() => {
    if (isAuthenticated) {
      loadLatestBatch();
    }
  }, [isAuthenticated]);

  const loadLatestBatch = async () => {
    try {
      const batch = await batchService.getLatestBatch();
      if (batch) {
        setActiveBatch(batch);
        if (batch.exceptions_count !== undefined) {
          setExceptionsCount(batch.exceptions_count);
        }
      }
    } catch (e) {
      console.warn('Initial batch load:', e);
    }
  };

  const handleStartInvestigation = (exc: ExceptionRecord) => {
    setInvestigatingException(exc);
  };

  const handleInvestigateTxn = (txn: CanonicalTransaction) => {
    const exc: ExceptionRecord = {
      id: `EXC-${txn.id}`,
      batch_id: activeBatch?.batch_id || 'BATCH-20260831',
      exception_type: txn.status === 'CUTOFF_LAG' ? 'PERIOD_CUTOFF_LAG' : txn.status === 'MDR_FEE' ? 'MDR_FEE_DEDUCTION' : 'MATCH_DISCREPANCY',
      severity: 'MEDIUM',
      state: 'OPEN',
      impact_minor: txn.amount_minor,
      impact_formatted: txn.amount_formatted,
      currency: txn.currency,
      primary_txn_id: txn.id,
      findings: [`Investigating transaction reference: ${txn.raw_reference}`],
      created_at: new Date().toISOString(),
    };
    setInvestigatingException(exc);
  };

  const handleBatchCompleted = (batch: ActiveBatchResponse) => {
    setActiveBatch(batch);
    if (batch.exceptions_count !== undefined) {
      setExceptionsCount(batch.exceptions_count);
    }
  };

  return (
    <>
      {/* Authentication Gate Modal */}
      <AuthGateModal />

      {isAuthenticated && (
        <div className="app-shell">
          {/* Left Navigation Sidebar */}
          <Sidebar
            currentView={currentView}
            onSelectView={(view) => {
              setCurrentView(view);
              setIsSidebarOpen(false);
            }}
            exceptionsCount={exceptionsCount}
            onOpenSop={() => setIsSopOpen(true)}
            onOpenManual={() => setIsManualOpen(true)}
            isOpen={isSidebarOpen}
            onClose={() => setIsSidebarOpen(false)}
          />

          {/* Main App Container */}
          <div className="app-main-wrapper">
            {/* Top Navigation Bar */}
            <TopNav
              currentView={currentView}
              onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
              onOpenQa={() => setIsQaOpen(true)}
            />

            {/* Scrollable View Content */}
            <main className="app-content-body">
              {currentView === 'overview' && (
                <OverviewView
                  batch={activeBatch}
                  onNavigateToWorkflow={() => setCurrentView('workflow')}
                  onNavigateToExceptions={() => setCurrentView('exceptions')}
                />
              )}

              {currentView === 'workflow' && (
                <WorkflowView
                  activeBatch={activeBatch}
                  onBatchCompleted={handleBatchCompleted}
                  onInvestigateException={handleInvestigateTxn}
                />
              )}

              {currentView === 'exceptions' && (
                <ExceptionsView
                  onInvestigate={handleStartInvestigation}
                  activeBatchId={activeBatch?.batch_id}
                />
              )}

              {currentView === 'audit' && <AuditView />}

              {currentView === 'agents' && (
                <AgentsView activeBatchId={activeBatch?.batch_id} />
              )}
            </main>
          </div>

          {/* Global Drawers and Overlays */}
          <SOPRulesDrawer isOpen={isSopOpen} onClose={() => setIsSopOpen(false)} />
          <AccountingManualDrawer
            isOpen={isManualOpen}
            onClose={() => setIsManualOpen(false)}
          />
          <ExceptionInvestigateDrawer
            exception={investigatingException}
            isOpen={!!investigatingException}
            onClose={() => setInvestigatingException(null)}
            onDecisionMade={() => {
              setInvestigatingException(null);
              loadLatestBatch();
            }}
          />
          <AIChatbotModal isOpen={isQaOpen} onClose={() => setIsQaOpen(false)} />
        </div>
      )}
    </>
  );
};
export default App;
