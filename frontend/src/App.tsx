import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckCircle2, Circle, FileText, Play, SlidersHorizontal, UserRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import {
  archiveMatchingProfile,
  clearAuthSession,
  createMatchingProfile,
  getErrorMessage,
  getUserStatus,
  hasAuthSession,
  revokeAuthSession,
  updateMatchingProfile,
} from './api/client';
import type {
  AgentQuotaStatus,
  AppUser,
  ApplicationAnswerProfilePayload,
  JobPreferencesPayload,
  MatchingProfile,
  MatchingProfilePayload,
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
import { JobPreferences } from './components/JobPreferences';
import { MatchingProfileSelector } from './components/MatchingProfileSelector';
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

const summarizeList = (items?: string[], fallback = 'Not set') => {
  const cleanItems = (items || []).map(item => item.trim()).filter(Boolean);
  if (!cleanItems.length) return fallback;
  if (cleanItems.length === 1) return cleanItems[0];
  return `${cleanItems[0]} +${cleanItems.length - 1}`;
};

const profileToPreferences = (profile?: MatchingProfile | null): JobPreferencesPayload | null => {
  if (!profile) return null;
  return {
    role: profile.role || [],
    experience_level: profile.experience_level || ['Intermediate'],
    location: profile.location || [],
    job_type: profile.job_type || ['Full-time'],
    target_companies: profile.target_companies || [],
    min_match_score: profile.min_match_score ?? 70,
    posted_within_days: profile.posted_within_days ?? 7,
  };
};

const profileToPayload = (
  profile: MatchingProfile,
  overrides: Partial<MatchingProfilePayload> = {},
): MatchingProfilePayload => ({
  name: (overrides.name ?? profile.name ?? 'Untitled profile').trim() || 'Untitled profile',
  resume_id: overrides.resume_id ?? profile.resume_id ?? profile.resume?.id ?? null,
  is_default: overrides.is_default ?? profile.is_default,
  role: overrides.role ?? profile.role ?? [],
  experience_level: overrides.experience_level ?? profile.experience_level ?? ['Intermediate'],
  location: overrides.location ?? profile.location ?? [],
  job_type: overrides.job_type ?? profile.job_type ?? ['Full-time'],
  target_companies: overrides.target_companies ?? profile.target_companies ?? [],
  min_match_score: overrides.min_match_score ?? profile.min_match_score ?? 70,
  posted_within_days: overrides.posted_within_days ?? profile.posted_within_days ?? 7,
});

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
  const [matchingProfiles, setMatchingProfiles] = useState<MatchingProfile[]>([]);
  const [selectedMatchingProfileId, setSelectedMatchingProfileId] = useState<number | null>(null);
  const [applicationProfileFilterId, setApplicationProfileFilterId] = useState<number | 'all' | null>(null);
  const [profileActionBusy, setProfileActionBusy] = useState(false);
  const [profileActionError, setProfileActionError] = useState<string | null>(null);

  const resumeRef = useRef<ResumeUploadHandle>(null);
  const prefsRef = useRef<JobPreferencesHandle>(null);

  const selectedMatchingProfile = useMemo(() => {
    return matchingProfiles.find(profile => profile.id === selectedMatchingProfileId) || matchingProfiles[0] || null;
  }, [matchingProfiles, selectedMatchingProfileId]);

  const resetSessionState = useCallback(() => {
    clearAuthSession();
    setUser(null);
    setResumeData(null);
    setPrefsData(null);
    setProfileData(null);
    setApplicationProfileData(null);
    setQuotaData(null);
    setMatchingProfiles([]);
    setSelectedMatchingProfileId(null);
    setApplicationProfileFilterId(null);
    setProfileActionError(null);
  }, []);

  const refreshStatus = useCallback(async (showLoading = true) => {
    if (hasAuthSession()) {
      if (showLoading) setLoading(true);
      try {
        const data = await getUserStatus();
        if (data.user) {
          const profiles = data.matching_profiles || [];
          const selectedFromResponse = data.selected_matching_profile
            ? profiles.find(profile => profile.id === data.selected_matching_profile?.id) || data.selected_matching_profile
            : null;
          const selectedProfile = profiles.find(profile => profile.id === selectedMatchingProfileId)
            || selectedFromResponse
            || profiles[0]
            || null;

          setUser(data.user);
          setMatchingProfiles(profiles);
          setSelectedMatchingProfileId(selectedProfile?.id ?? null);
          setResumeData(selectedProfile?.resume ?? data.resume ?? null);
          setPrefsData(profileToPreferences(selectedProfile) ?? data.preferences ?? null);
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
  }, [resetSessionState, selectedMatchingProfileId]);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void refreshStatus(false);
    }, 0);
    return () => window.clearTimeout(timeout);
  }, [refreshStatus]);

  useEffect(() => {
    if (!loading && resumeRef.current) {
      resumeRef.current.setResumeData(resumeData);
    }
  }, [loading, resumeData]);

  useEffect(() => {
    if (!selectedMatchingProfile) return;
    setResumeData(selectedMatchingProfile.resume ?? null);
    setPrefsData(profileToPreferences(selectedMatchingProfile));
    setProfileActionError(null);
  }, [selectedMatchingProfile]);

  useEffect(() => {
    if (applicationProfileFilterId === null && selectedMatchingProfile?.id) {
      setApplicationProfileFilterId(selectedMatchingProfile.id);
    }
  }, [applicationProfileFilterId, selectedMatchingProfile?.id]);

  useEffect(() => {
    if (typeof applicationProfileFilterId !== 'number' || !matchingProfiles.length) return;
    if (!matchingProfiles.some(profile => profile.id === applicationProfileFilterId)) {
      setApplicationProfileFilterId(selectedMatchingProfile?.id ?? null);
    }
  }, [applicationProfileFilterId, matchingProfiles, selectedMatchingProfile?.id]);

  const applicationProfileFilter = useMemo(() => {
    if (typeof applicationProfileFilterId !== 'number') return null;
    return matchingProfiles.find(profile => profile.id === applicationProfileFilterId) || null;
  }, [applicationProfileFilterId, matchingProfiles]);

  const applicationDashboardProfileId = typeof applicationProfileFilterId === 'number'
    ? applicationProfileFilterId
    : null;
  const applicationDashboardMinMatchScore = applicationProfileFilter?.min_match_score
    ?? selectedMatchingProfile?.min_match_score
    ?? prefsData?.min_match_score
    ?? 70;

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

  const handleSelectMatchingProfile = (profileId: number) => {
    const profile = matchingProfiles.find(item => item.id === profileId);
    setSelectedMatchingProfileId(profileId);
    setResumeData(profile?.resume ?? null);
    setPrefsData(profileToPreferences(profile));
  };

  const handleCreateMatchingProfile = async () => {
    setProfileActionBusy(true);
    setProfileActionError(null);
    try {
      const profile = await createMatchingProfile({ name: `Search profile ${matchingProfiles.length + 1}` });
      setMatchingProfiles(prev => [profile, ...prev.filter(item => item.id !== profile.id)]);
      setSelectedMatchingProfileId(profile.id);
      setResumeData(profile.resume ?? null);
      setPrefsData(profileToPreferences(profile));
    } catch (error) {
      setProfileActionError(getErrorMessage(error, 'Failed to create matching profile.'));
    } finally {
      setProfileActionBusy(false);
    }
  };

  const handleDuplicateMatchingProfile = async () => {
    if (!selectedMatchingProfile) return;
    setProfileActionBusy(true);
    setProfileActionError(null);
    try {
      const profile = await createMatchingProfile({
        name: `${selectedMatchingProfile.name} copy`,
        duplicate_from_id: selectedMatchingProfile.id,
      });
      setMatchingProfiles(prev => [profile, ...prev.filter(item => item.id !== profile.id)]);
      setSelectedMatchingProfileId(profile.id);
      setResumeData(profile.resume ?? null);
      setPrefsData(profileToPreferences(profile));
    } catch (error) {
      setProfileActionError(getErrorMessage(error, 'Failed to duplicate matching profile.'));
    } finally {
      setProfileActionBusy(false);
    }
  };

  const handleRenameMatchingProfile = async (name: string) => {
    if (!selectedMatchingProfile) return;
    setProfileActionBusy(true);
    setProfileActionError(null);
    try {
      const profile = await updateMatchingProfile(
        selectedMatchingProfile.id,
        profileToPayload(selectedMatchingProfile, { name }),
      );
      setMatchingProfiles(prev => prev.map(item => item.id === profile.id ? profile : item));
      setSelectedMatchingProfileId(profile.id);
    } catch (error) {
      setProfileActionError(getErrorMessage(error, 'Failed to rename matching profile.'));
    } finally {
      setProfileActionBusy(false);
    }
  };

  const handleArchiveMatchingProfile = async () => {
    if (!selectedMatchingProfile) return;
    setProfileActionBusy(true);
    setProfileActionError(null);
    try {
      await archiveMatchingProfile(selectedMatchingProfile.id);
      await refreshStatus(false);
    } catch (error) {
      setProfileActionError(getErrorMessage(error, 'Failed to archive matching profile.'));
    } finally {
      setProfileActionBusy(false);
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
        ? `${summarizeList(prefsData.role, 'Role')} / ${summarizeList(prefsData.location, 'Market')}`
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
    const applicationFilterValue = applicationProfileFilterId === null
      ? ''
      : applicationProfileFilterId === 'all'
        ? 'all'
        : String(applicationProfileFilterId);
    const applicationFilterRoleSummary = applicationProfileFilter
      ? summarizeList(applicationProfileFilter.role, 'No role targets yet')
      : 'All saved matching profiles';
    const applicationFilterResume = applicationProfileFilter?.resume?.filename || 'Multiple resume signals';
    const applicationFilterControl = user && matchingProfiles.length > 0 ? (
      <div className="min-w-[220px] sm:w-64">
        <label className="mb-1 block text-xs font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">Profile</label>
        <select
          value={applicationFilterValue}
          onChange={(event) => {
            const value = event.target.value;
            setApplicationProfileFilterId(value === 'all' ? 'all' : Number(value));
          }}
          className="min-h-9 w-full rounded-md border border-[var(--line)] bg-white px-3 text-sm text-[var(--ink)] outline-none transition-colors focus:border-[var(--accent)]"
        >
          {applicationProfileFilterId === null && <option value="">Loading profiles</option>}
          {matchingProfiles.map(profile => (
            <option key={profile.id} value={profile.id}>{profile.name}</option>
          ))}
          <option value="all">All profiles</option>
        </select>
      </div>
    ) : null;
    const applicationFilterSummary = user && matchingProfiles.length > 0 ? (
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
        <StatusChip tone={applicationProfileFilterId === 'all' ? 'neutral' : 'accent'}>
          {applicationProfileFilterId === 'all' ? `${matchingProfiles.length} profiles` : applicationProfileFilter?.name || 'Selected profile'}
        </StatusChip>
        <span className="min-w-0 truncate">{applicationFilterRoleSummary}</span>
        <span className="hidden text-[var(--line)] sm:inline">/</span>
        <span className="min-w-0 truncate">{applicationFilterResume}</span>
      </div>
    ) : null;

    return shell(
      <PageShell>
        <SectionHeader
          eyebrow="Pipeline"
          title="Application pipeline"
          description="Track best-fit roles by saved matching profile, manage status, and open generated materials for each application."
        />
        <div className="mt-5">
          <AgentDashboard
            key={`${refreshHistory}-${applicationProfileFilterId ?? 'pending'}`}
            fullPage
            minMatchScore={applicationDashboardMinMatchScore}
            minMatchScoreLabel={applicationProfileFilterId === 'all' ? 'Minimum match score varies by profile' : undefined}
            matchingProfileId={applicationDashboardProfileId}
            profileFilterControl={applicationFilterControl}
            profileFilterSummary={applicationFilterSummary}
          />
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
          description="Manage the profile details and reusable application answers JobMatchKit uses for matching and generated materials."
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
              title="Match better jobs, faster"
              description="JobMatchKit compares roles with your resume and preferences, highlights strong fits, and prepares application materials for review."
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
            description="Give JobMatchKit the resume, targets, and profile details it needs to match roles and write accurate materials."
          />

          {user && (
            <div className="mt-4">
              <MatchingProfileSelector
                profiles={matchingProfiles}
                selectedProfileId={selectedMatchingProfile?.id ?? selectedMatchingProfileId}
                saving={profileActionBusy}
                error={profileActionError}
                onSelect={handleSelectMatchingProfile}
                onCreate={handleCreateMatchingProfile}
                onDuplicate={handleDuplicateMatchingProfile}
                onArchive={handleArchiveMatchingProfile}
                onRename={handleRenameMatchingProfile}
              />
            </div>
          )}

          <div className="mt-4 divide-y divide-[var(--line)] border-t border-[var(--line)]">
            <section className="py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-[var(--ink)]">Resume signal</h3>
                <StatusChip tone={resumeData?.filename ? 'success' : 'neutral'}>
                  {resumeData?.filename ? 'Ready' : 'Upload needed'}
                </StatusChip>
              </div>
              <ResumeUpload ref={resumeRef} initialData={resumeData} matchingProfileId={selectedMatchingProfile?.id ?? selectedMatchingProfileId} />
              <ResumeFeedback hasResume={!!resumeData?.filename} />
            </section>

            <section className="py-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-base font-semibold text-[var(--ink)]">Matching preferences</h3>
                <StatusChip tone={preferencesReady ? 'success' : 'neutral'}>
                  {preferencesReady ? 'Ready' : 'Targets needed'}
                </StatusChip>
              </div>
              <JobPreferences ref={prefsRef} initialData={prefsData} matchingProfileId={selectedMatchingProfile?.id ?? selectedMatchingProfileId} />
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
            </section>
          </div>
        </Panel>

        <aside className="grid min-w-0 gap-4 xl:sticky xl:top-4">
          <Panel className="min-w-0 p-4">
            <SectionHeader
              eyebrow="Action"
              title="Match and package jobs"
              description="Start a matching workflow to search, score, and prepare application packages."
              action={<Play size={19} className="text-[var(--accent)]" />}
            />
            <div className="mt-4">
              <AgentControls
                resumeRef={resumeRef}
                prefsRef={prefsRef}
                isLoggedIn={!!user}
                quota={quotaData}
                matchingProfileId={selectedMatchingProfile?.id ?? selectedMatchingProfileId}
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
            <AgentDashboard key={refreshHistory} limit={5} compact minMatchScore={selectedMatchingProfile?.min_match_score ?? prefsData?.min_match_score ?? 70} matchingProfileId={selectedMatchingProfile?.id ?? selectedMatchingProfileId} />
          </Panel>
        </aside>
      </section>
    </PageShell>,
  );
}

export default App;
