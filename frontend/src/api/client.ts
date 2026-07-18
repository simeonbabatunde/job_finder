export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const AUTH_TOKEN_KEY = 'auth_token';
const AUTH_REFRESH_TOKEN_KEY = 'auth_refresh_token';
const AUTH_TOKEN_EXPIRES_AT_KEY = 'auth_token_expires_at';
const AUTH_REFRESH_EXPIRES_AT_KEY = 'auth_refresh_expires_at';
const USER_EMAIL_KEY = 'user_email';

export interface AppUser {
    id?: number;
    email: string;
    subscription_tier: string;
    subscription_status?: string | null;
    subscription_current_period_end?: string | null;
    subscription_cancel_at_period_end?: boolean;
    role: string;
}

export interface ResumeStatus {
    id?: number | null;
    filename: string;
    uploaded_at?: string;
    skills?: string[];
    summary?: string | null;
}

export interface ProfilePayload {
    first_name: string;
    last_name: string;
    email: string;
    phone: string;
    location: string;
    linkedin_url?: string;
    portfolio_url?: string;
    github_url?: string;
    years_experience: number;
    expected_salary?: string;
}

export interface ApplicationAnswerProfilePayload {
    id?: number;
    work_authorized_us: string;
    requires_sponsorship_now: string;
    requires_sponsorship_future: string;
    willing_to_relocate: string;
    remote_preference: string;
    earliest_start_date?: string;
    notice_period?: string;
    desired_salary?: string;
    work_authorization_notes?: string;
    consent_to_use_answers: boolean;
    gender: string;
    race_ethnicity: string;
    veteran_status: string;
    disability_status: string;
    consent_to_use_demographics: boolean;
    updated_at?: string;
}

export interface ApplicationAnswerAuditRecord {
    id?: number;
    action: string;
    access_reason: string;
    source: string;
    application_id?: number | null;
    fields: string[];
    created_at: string;
}

export interface ApplicationPackagePayload {
    cover_letter?: string | null;
    tailored_summary?: string | null;
    resume_improvements?: string[];
    talking_points?: string[];
    qa_answers?: { question: string; answer: string }[];
    interview_questions?: { question: string; suggested_answer: string }[];
    company_brief?: {
        overview?: string;
        mission?: string;
        culture_signals?: string[];
        questions_to_ask?: string[];
    };
}

export interface RegisterProfile {
    first_name: string;
    last_name: string;
    phone: string;
    location: string;
    linkedin_url?: string;
}

export interface JobPreferencesPayload {
    role: string[];
    experience_level: string[];
    location: string[];
    job_type: string[];
    target_companies: string[];
    min_match_score: number;
    posted_within_days: number;
}

export interface MatchingProfilePayload extends JobPreferencesPayload {
    name: string;
    resume_id?: number | null;
    is_default?: boolean;
}

export interface MatchingProfile extends MatchingProfilePayload {
    id: number;
    is_archived: boolean;
    resume?: ResumeStatus | null;
    last_used_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface MatchingProfileCreatePayload extends Partial<MatchingProfilePayload> {
    name: string;
    duplicate_from_id?: number | null;
}

export interface UserStatusResponse {
    user?: AppUser;
    resume?: ResumeStatus | null;
    preferences?: JobPreferencesPayload | null;
    matching_profiles?: MatchingProfile[];
    selected_matching_profile?: MatchingProfile | null;
    profile?: ProfilePayload | null;
    application_profile?: ApplicationAnswerProfilePayload | null;
    quota?: AgentQuotaStatus | null;
}

export interface AuthResponse {
    user: AppUser;
    access_token: string;
    refresh_token?: string | null;
    token_type: 'bearer';
    expires_in?: number | null;
    refresh_expires_in?: number | null;
    message?: string | null;
}

export interface AgentQuotaStatus {
    agent_runs_used_today: number;
    agent_run_limit: number;
    agent_runs_remaining: number;
}

export interface AgentRunRecord {
    id: number;
    status: string;
    auto_apply: boolean;
    matching_profile_id?: number | null;
    matching_profile_name?: string | null;
    resume_id?: number | null;
    logs: string[];
    applications_count: number;
    found_jobs_count: number;
    error?: string | null;
    started_at: string;
    completed_at?: string | null;
}

export interface ApplicationSummary {
    strong_count: number;
    below_threshold_count: number;
    visible_count: number;
    min_match_score: number;
    latest_run?: AgentRunRecord | null;
}

export interface BillingStatus {
    plan: string;
    subscription_status?: string | null;
    subscription_current_period_end?: string | null;
    subscription_cancel_at_period_end: boolean;
    billing_enabled: boolean;
    can_upgrade: boolean;
    can_manage_billing: boolean;
    pro_price_label: string;
    message: string;
}

export interface BillingSession {
    url: string;
}

function getErrorMessage(error: unknown, fallback: string) {
    if (error instanceof Error) return error.message;
    return fallback;
}

async function getResponseDetail(response: Response, fallback: string) {
    const err = await response.json().catch((): Record<string, unknown> => ({}));
    return typeof err.detail === 'string' ? err.detail : fallback;
}

export function getAuthHeaders(): Record<string, string> {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    return token ? { Authorization: `Bearer ${token}` } : {};
}

export function hasAuthSession() {
    return Boolean(localStorage.getItem(AUTH_TOKEN_KEY) || localStorage.getItem(AUTH_REFRESH_TOKEN_KEY));
}

export function clearAuthSession() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
    localStorage.removeItem(AUTH_TOKEN_EXPIRES_AT_KEY);
    localStorage.removeItem(AUTH_REFRESH_EXPIRES_AT_KEY);
    localStorage.removeItem(USER_EMAIL_KEY);
}

export async function revokeAuthSession() {
    const refreshToken = localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
    const response = await fetch(`${API_URL}/auth/logout`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: refreshToken ? JSON.stringify({ refresh_token: refreshToken }) : undefined,
    });
    if (!response.ok && response.status !== 401) {
        throw new Error(await getResponseDetail(response, 'Failed to sign out'));
    }
    return response.ok ? response.json() : null;
}

export function saveAuthSession(data: AuthResponse) {
    localStorage.setItem(AUTH_TOKEN_KEY, data.access_token);
    if (data.refresh_token) {
        localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, data.refresh_token);
    } else {
        localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
    }
    if (data.expires_in) {
        localStorage.setItem(AUTH_TOKEN_EXPIRES_AT_KEY, String(Date.now() + data.expires_in * 1000));
    }
    if (data.refresh_expires_in) {
        localStorage.setItem(AUTH_REFRESH_EXPIRES_AT_KEY, String(Date.now() + data.refresh_expires_in * 1000));
    }
    if (data.user?.email) {
        localStorage.setItem(USER_EMAIL_KEY, data.user.email);
    }
}

export function saveOAuthSession(token: string, refreshToken?: string | null, email?: string | null) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    if (refreshToken) {
        localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken);
    }
    if (email) {
        localStorage.setItem(USER_EMAIL_KEY, email);
    }
}

export async function refreshAuthSession() {
    const refreshToken = localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
    if (!refreshToken) return null;

    const response = await fetch(`${API_URL}/auth/refresh`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
        clearAuthSession();
        return null;
    }

    const data: AuthResponse = await response.json();
    saveAuthSession(data);
    return data;
}

export async function saveProfile(profileData: ProfilePayload) {
    const response = await fetch(`${API_URL}/profile`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
        body: JSON.stringify(profileData),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to save profile'));
    }
    return response.json();
}

export async function getApplicationProfile(): Promise<ApplicationAnswerProfilePayload | null> {
    const response = await fetch(`${API_URL}/application-profile`, {
        headers: getAuthHeaders()
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch application answers'));
    }
    return response.json();
}

export async function getApplicationProfileAudit(limit = 50): Promise<ApplicationAnswerAuditRecord[]> {
    const response = await fetch(`${API_URL}/application-profile/audit?limit=${limit}`, {
        headers: getAuthHeaders()
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch application answer audit'));
    }
    return response.json();
}

export async function saveApplicationProfile(profileData: ApplicationAnswerProfilePayload) {
    const response = await fetch(`${API_URL}/application-profile`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
        body: JSON.stringify(profileData),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to save application answers'));
    }
    return response.json();
}

export async function deleteApplicationProfile() {
    const response = await fetch(`${API_URL}/application-profile`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to reset application answers'));
    }
    return response.json();
}

export async function getResumeFeedback() {
    const response = await fetch(`${API_URL}/agent/resume-feedback`, {
        method: 'POST',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to analyse resume'));
    }
    return response.json();
}

export async function getUserStatus(): Promise<UserStatusResponse> {
    let response = await fetch(`${API_URL}/user/status`, {
        headers: getAuthHeaders()
    });
    if (response.status === 401 && localStorage.getItem(AUTH_REFRESH_TOKEN_KEY)) {
        const refreshed = await refreshAuthSession();
        if (refreshed) {
            response = await fetch(`${API_URL}/user/status`, {
                headers: getAuthHeaders()
            });
        }
    }
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch user status'));
    }
    return response.json();
}

export async function login(email: string, password: string) {
    const response = await fetch(`${API_URL}/auth/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password }),
    });

    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to login'));
    }

    const data: AuthResponse = await response.json();
    saveAuthSession(data);
    return data;
}

export async function register(email: string, password: string, profile: RegisterProfile) {
    const response = await fetch(`${API_URL}/auth/register`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password, profile }),
    });

    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to register'));
    }

    const data: AuthResponse = await response.json();
    saveAuthSession(data);
    return data;
}

export async function socialLogin(email: string, provider: string, first_name: string, last_name: string) {
    const response = await fetch(`${API_URL}/auth/social`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, provider, first_name, last_name }),
    });

    if (!response.ok) {
        throw new Error('Social login failed');
    }

    const data: AuthResponse = await response.json();
    saveAuthSession(data);
    return data;
}

export async function uploadResume(file: File, matchingProfileId?: number | null) {
    const formData = new FormData();
    formData.append('file', file);
    const query = matchingProfileId ? `?matching_profile_id=${matchingProfileId}` : '';

    const response = await fetch(`${API_URL}/upload-resume${query}`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
    });

    if (!response.ok) {
        throw new Error('Failed to upload resume');
    }

    return response.json();
}

export async function savePreferences(preferences: JobPreferencesPayload, matchingProfileId?: number | null) {
    const query = matchingProfileId ? `?matching_profile_id=${matchingProfileId}` : '';
    const response = await fetch(`${API_URL}/preferences${query}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
        body: JSON.stringify(preferences),
    });

    if (!response.ok) {
        throw new Error('Failed to save preferences');
    }

    return response.json();
}

export async function getResumes(): Promise<ResumeStatus[]> {
    const response = await fetch(`${API_URL}/resumes`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch resumes'));
    }
    return response.json();
}

export async function getMatchingProfiles(): Promise<MatchingProfile[]> {
    const response = await fetch(`${API_URL}/matching-profiles`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch matching profiles'));
    }
    return response.json();
}

export async function createMatchingProfile(payload: MatchingProfileCreatePayload): Promise<MatchingProfile> {
    const response = await fetch(`${API_URL}/matching-profiles`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to create matching profile'));
    }
    return response.json();
}

export async function updateMatchingProfile(profileId: number, payload: MatchingProfilePayload): Promise<MatchingProfile> {
    const response = await fetch(`${API_URL}/matching-profiles/${profileId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to update matching profile'));
    }
    return response.json();
}

export async function archiveMatchingProfile(profileId: number): Promise<MatchingProfile> {
    const response = await fetch(`${API_URL}/matching-profiles/${profileId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to archive matching profile'));
    }
    return response.json();
}

export async function searchJobs(query: string, location: string) {
    const params = new URLSearchParams({ query, location });
    const response = await fetch(`${API_URL}/search-jobs?${params}`, {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
    });

    if (!response.ok) {
        throw new Error('Failed to search jobs');
    }

    return response.json();
}

export async function getAgentRuns(limit = 5): Promise<AgentRunRecord[]> {
    const response = await fetch(`${API_URL}/agent/runs?limit=${limit}`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch matching runs'));
    }
    return response.json();
}

export async function getApplicationSummary(matchingProfileId?: number | null): Promise<ApplicationSummary> {
    const query = matchingProfileId ? `?matching_profile_id=${matchingProfileId}` : '';
    const response = await fetch(`${API_URL}/applications/summary${query}`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch application summary'));
    }
    return response.json();
}

export async function forgotPassword(email: string) {
    const response = await fetch(`${API_URL}/auth/forgot-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email }),
    });
    return response.json();
}

export async function resetPassword(token: string, password: string) {
    const response = await fetch(`${API_URL}/auth/reset-password`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ token, password }),
    });

    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to reset password'));
    }

    return response.json();
}

export async function prepareApplication(jobData: {
    app_id: number;
    title: string;
    company: string;
    description?: string;
}) {
    const response = await fetch(`${API_URL}/agent/prepare-application`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
        body: JSON.stringify(jobData),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to prepare application'));
    }
    return response.json();
}

export { getErrorMessage };

export async function downloadCoverLetterPdf(appId: number) {
    const response = await fetch(`${API_URL}/applications/${appId}/cover-letter.pdf`, {
        headers: getAuthHeaders()
    });
    if (!response.ok) throw new Error('Failed to download PDF');
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // Try to get filename from header
    const disposition = response.headers.get('Content-Disposition');
    const match = disposition?.match(/filename="(.+?)"/);
    a.download = match ? match[1] : `cover_letter_${appId}.pdf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}

export async function downloadApplicationPackageZip(appId: number, packageData: ApplicationPackagePayload) {
    const response = await fetch(`${API_URL}/applications/${appId}/package.zip`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders(),
        },
        body: JSON.stringify(packageData),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to download application package'));
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const disposition = response.headers.get('Content-Disposition');
    const match = disposition?.match(/filename="(.+?)"/);
    a.download = match ? match[1] : `application_package_${appId}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
}

export async function updateApplicationStatus(appId: number, status: string) {
    const response = await fetch(`${API_URL}/applications/${appId}/status`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            ...getAuthHeaders()
        },
        body: JSON.stringify({ status }),
    });
    if (!response.ok) throw new Error('Failed to update status');
    return response.json();
}

export async function clearApplications(): Promise<{ message: string }> {
    const response = await fetch(`${API_URL}/applications`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to clear application history'));
    }
    return response.json();
}

export async function getBillingStatus(): Promise<BillingStatus> {
    const response = await fetch(`${API_URL}/billing/status`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch billing status'));
    }
    return response.json();
}

export async function createBillingCheckoutSession(): Promise<BillingSession> {
    const response = await fetch(`${API_URL}/billing/checkout-session`, {
        method: 'POST',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to start Pro checkout'));
    }
    return response.json();
}

export async function createBillingPortalSession(): Promise<BillingSession> {
    const response = await fetch(`${API_URL}/billing/customer-portal`, {
        method: 'POST',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to open billing management'));
    }
    return response.json();
}
