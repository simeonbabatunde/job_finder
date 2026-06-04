import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, Circle, FileText, Play, SlidersHorizontal, UserRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { clearAuthSession, downloadAccountDataExport, getErrorMessage, getUserStatus, hasAuthSession, revokeAuthSession } from './api/client';
import type {
  AgentQuotaStatus,
  AppUser,
  ApplicationAnswerProfilePayload,
  JobPreferencesPayload,
  ProfilePayload,
  ResumeStatus,
} from './api/client';
import { AppHeader } from './components/AppHeader';
import { ResumeUpload } from './components/ResumeUpload';
import type { ResumeUploadHandle } from './components/ResumeUpload';
import { ResumeFeedback } from './components/ResumeFeedback';
import { UserProfile } from './components/UserProfile';
import { ProfileSettings } from './components/ProfileSettings';
import { ApplicationAnswers } from './components/ApplicationAnswers';
import { SubmissionSettings } from './components/SubmissionSettings';
import { JobPreferences } from './components/JobPreferences';
import type { JobPreferencesHandle } from './components/JobPreferences';
import { AgentControls } from './components/AgentControls';
import { AgentDashboard } from './components/AgentDashboard';
import { Login } from './components/Login';
import { AdminPanel } from './components/AdminPanel';
import { ResetPassword } from './components/ResetPassword';
import { OAuthCallback } from './components/OAuthCallback';
import { Button, PageShell, Panel, SectionHeader, StatusChip } from './components/ui';

interface OverviewItem {
  label: string;
  detail: string;
  ready: boolean;
  icon: LucideIcon;
}

function App() {
  const currentPath = window.location.pathname;
  const [refreshHistory, setRefreshHistory] = useState(0);
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(() => hasAuthSession());
  const [showAuth, setShowAuth] = useState<'login' | 'register' | null>(null);
  const [resumeData, setResumeData] = useState<ResumeStatus | null>(null);
  const [prefsData, setPrefsData] = useState<JobPreferencesPayload | null>(null);
  const [profileData, setProfileData] = useState<ProfilePayload | null>(null);
  const [applicationProfileData, setApplicationProfileData] = useState<ApplicationAnswerProfilePayload | null>(null);
  const [quotaData, setQuotaData] = useState<AgentQuotaStatus | null>(null);
  const [exportingAccountData, setExportingAccountData] = useState(false);

  const resumeRef = useRef<ResumeUploadHandle>(null);
  const prefsRef = useRef<JobPreferencesHandle>(null);

  const resetSessionState = useCallback(() => {
    clearAuthSession();
    setUser(null);
    setResumeData(null);
    setPrefsData(null);
    setProfileData(null);
    setApplicationProfileData(null);
    setQuotaData(null);
  }, []);

  const refreshStatus = useCallback(async (showLoading = true) => {
    if (hasAuthSession()) {
      if (showLoading) setLoading(true);
      try {
        const data = await getUserStatus();
        if (data.user) {
          setUser(data.user);
          setResumeData(data.resume ?? null);
          setPrefsData(data.preferences ?? null);
          setProfileData(data.profile ?? null);
          setApplicationProfileData(data.application_profile ?? null);
          setQuotaData(data.quota ?? null);
        }
      } catch (err) {
        console.error('Error fetching user status', err);
        resetSessionState();
      } finally {
        setLoading(false);
      }
    } else {
      setLoading(false);
    }
  }, [resetSessionState]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void refreshStatus(false);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [refreshStatus]);

  useEffect(() => {
    if (!loading && resumeData && resumeRef.current) {
      resumeRef.current.setResumeData(resumeData);
    }
  }, [loading, resumeData]);

  const handleLogout = async () => {
    try {
      await revokeAuthSession();
    } catch (error) {
      console.warn('Logout session revoke failed:', error);
    } finally {
      resetSessionState();
    }
  };

  const handleLoginSuccess = (u: AppUser) => {
    setUser(u);
    setShowAuth(null);
    refreshStatus();
  };

  const handleExportAccountData = async () => {
    setExportingAccountData(true);
    try {
      await downloadAccountDataExport();
    } catch (error) {
      window.alert(getErrorMessage(error, 'Failed to export account data'));
    } finally {
      setExportingAccountData(false);
    }
  };

  const profileComplete = useMemo(() => {
    if (!profileData) return false;
    const requiredFields: Array<keyof ProfilePayload> = ['first_name', 'last_name', 'email', 'phone', 'location'];
    return requiredFields.every(
      key => String(profileData[key] || '').trim() !== '',
    );
  }, [profileData]);

  const preferencesReady = useMemo(() => {
    if (!prefsData) return false;
    return Boolean(prefsData.role?.length && prefsData.location?.length);
  }, [prefsData]);

  const overviewItems: OverviewItem[] = [
    {
      label: 'Resume',
      ready: !!resumeData?.filename,
      detail: resumeData?.filename || 'Matching signal needed',
      icon: FileText,
    },
    {
      label: 'Profile',
      ready: profileComplete,
      detail: profileComplete ? 'Complete' : 'Contact details needed',
      icon: UserRound,
    },
    {
      label: 'Preferences',
      ready: preferencesReady,
      detail: prefsData
        ? `${prefsData.role?.[0] || 'Role'} / ${prefsData.location?.[0] || 'Market'}`
        : 'Matching targets needed',
      icon: SlidersHorizontal,
    },
    {
      label: 'Daily runs',
      ready: Boolean(quotaData && quotaData.agent_runs_remaining > 0),
      detail: quotaData
        ? `${quotaData.agent_runs_remaining}/${quotaData.agent_run_limit} runs left today`
        : 'Sign in to view quota',
      icon: Play,
    },
  ];

  if (currentPath === '/oauth-callback') {
    return <OAuthCallback />;
  }

  if (currentPath === '/reset-password') {
    return <ResetPassword />;
  }

  if (currentPath === '/admin') {
    return <AdminPanel />;
  }

  if (loading && hasAuthSession()) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--page)]">
        <div className="h-10 w-10 animate-spin rounded-full border-2 border-[var(--line)] border-t-[var(--accent)]" />
      </div>
    );
  }

  const shell = (children: ReactNode) => (
    <div className="min-h-screen bg-[var(--page)] text-[var(--ink)]">
      <AppHeader
        user={user}
        currentPath={currentPath}
        onLogin={() => setShowAuth('login')}
        onLogout={handleLogout}
        onExportData={user ? handleExportAccountData : undefined}
        exportingData={exportingAccountData}
      />
      {children}
      {showAuth && (
        <Login
          initialMode={showAuth}
          onLoginSuccess={handleLoginSuccess}
          onClose={() => setShowAuth(null)}
        />
      )}
    </div>
  );

  if (currentPath === '/applications') {
    return shell(
      <PageShell>
        <SectionHeader
          eyebrow="Pipeline"
          title="Application pipeline"
          description="Track every best-fit role, manage status, and open the generated materials for each application."
        />
        <div className="mt-5">
          <AgentDashboard key={refreshHistory} fullPage minMatchScore={prefsData?.min_match_score ?? 70} />
        </div>
      </PageShell>,
    );
  }

  if (currentPath === '/settings') {
    return shell(
      <PageShell>
        <SectionHeader
          eyebrow="Account"
          title="Account settings"
          description="Manage the profile details, reusable application answers, and submission guardrails the assistant uses for job matching and application prep."
        />
        <div className="mt-5">
          {user ? (
            <ProfileSettings />
          ) : (
            <Panel className="p-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <StatusChip tone="warning">Sign in required</StatusChip>
                  <p className="mt-3 text-sm leading-6 text-[var(--muted)]">
                    Account settings are available after you sign in or create an account.
                  </p>
                </div>
                <Button onClick={() => setShowAuth('login')}>
                  Sign in
                </Button>
              </div>
            </Panel>
          )}
        </div>
      </PageShell>,
    );
  }

  return shell(
    <PageShell className="space-y-4">
      <Panel className="p-4">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,0.72fr)_minmax(560px,1fr)] xl:items-center">
          <div>
            <SectionHeader
              eyebrow="Dashboard"
              title="Smart job search assistant"
              description="Use your resume and preferences to find aligned roles, score fit, and package application materials automatically."
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {user ? (
                <StatusChip tone={user.subscription_tier === 'pro' ? 'accent' : 'neutral'}>
                  {user.subscription_tier} plan
                </StatusChip>
              ) : (
                <StatusChip tone="warning">Sign in required</StatusChip>
              )}
              {quotaData && (
                <StatusChip tone={quotaData.agent_runs_remaining === 0 ? 'danger' : 'neutral'}>
                  {quotaData.agent_runs_remaining} runs left today
                </StatusChip>
              )}
            </div>
          </div>

          <div className="grid gap-px overflow-hidden rounded-md bg-[var(--line)] text-sm sm:grid-cols-2 lg:grid-cols-4">
            {overviewItems.map((item) => {
              const Icon = item.icon;
              return (
                <div key={item.label} className="flex min-h-[68px] items-center gap-3 bg-[var(--page)] p-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-white text-[var(--accent)]">
                    <Icon size={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="font-semibold text-[var(--ink)]">{item.label}</p>
                      {item.ready ? (
                        <CheckCircle2 className="shrink-0 text-[var(--positive)]" size={15} />
                      ) : (
                        <Circle className="shrink-0 text-[var(--muted)]" size={15} />
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-[var(--muted)]">{item.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Panel>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] xl:items-start">
        <Panel className="min-w-0 p-4">
          <SectionHeader
            eyebrow="Setup"
            title="Workspace setup"
            description="Give the assistant the resume, targets, and profile details it needs to match roles and write accurate materials."
          />

          <div className="mt-4 divide-y divide-[var(--line)] border-t border-[var(--line)]">
            <section className="py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-[var(--ink)]">Resume signal</h3>
                <StatusChip tone={resumeData?.filename ? 'success' : 'neutral'}>
                  {resumeData?.filename ? 'Ready' : 'Upload needed'}
                </StatusChip>
              </div>
              <ResumeUpload ref={resumeRef} initialData={resumeData} />
              <ResumeFeedback hasResume={!!resumeData?.filename} />
            </section>

            <section className="py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-[var(--ink)]">Matching preferences</h3>
                <StatusChip tone={preferencesReady ? 'success' : 'neutral'}>
                  {preferencesReady ? 'Ready' : 'Targets needed'}
                </StatusChip>
              </div>
              <JobPreferences ref={prefsRef} initialData={prefsData} />
            </section>

            <section className="pt-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-[var(--ink)]">Candidate profile</h3>
                <StatusChip tone={profileComplete ? 'success' : 'warning'}>
                  {profileComplete ? 'Complete' : 'Incomplete'}
                </StatusChip>
              </div>
              <UserProfile initialData={profileData} userEmail={user?.email} />
              <div className="mt-4 border-t border-[var(--line)] pt-4">
                <ApplicationAnswers
                  initialData={applicationProfileData}
                  onSaved={setApplicationProfileData}
                />
              </div>
              <div className="mt-4 border-t border-[var(--line)] pt-4">
                <SubmissionSettings />
              </div>
            </section>
          </div>
        </Panel>

        <aside className="grid min-w-0 gap-4 xl:sticky xl:top-4">
          <Panel className="min-w-0 p-4">
            <SectionHeader
              eyebrow="Action"
              title="Match and package jobs"
              description="Launch the assistant to search, score, and prepare application kits."
              action={<Play size={19} className="text-[var(--accent)]" />}
            />
            <div className="mt-4">
              <AgentControls
                resumeRef={resumeRef}
                prefsRef={prefsRef}
                isLoggedIn={!!user}
                quota={quotaData}
                subscriptionTier={user?.subscription_tier}
                userRole={user?.role}
                onAuthRequired={() => setShowAuth('register')}
                onComplete={() => {
                  setRefreshHistory(prev => prev + 1);
                  refreshStatus();
                }}
              />
            </div>
          </Panel>

          <Panel className="min-w-0 overflow-hidden p-4">
            <SectionHeader
              eyebrow="Recent"
              title="Best-fit jobs"
              description="Latest roles scored against your resume and preferences."
            />
            <AgentDashboard key={refreshHistory} limit={5} compact minMatchScore={prefsData?.min_match_score ?? 70} />
          </Panel>
        </aside>
      </section>
    </PageShell>,
  );
}

export default App;
