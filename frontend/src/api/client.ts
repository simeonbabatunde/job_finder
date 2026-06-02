export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const AUTH_TOKEN_KEY = 'auth_token';
const USER_EMAIL_KEY = 'user_email';

export interface AppUser {
    id?: number;
    email: string;
    subscription_tier: string;
    role: string;
}

export interface ResumeStatus {
    filename: string;
    skills?: string[];
    summary?: string;
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

export interface ApplicationFillReviewResult {
    review_id?: number;
    status: string;
    ats_type: string;
    application_url: string;
    fields_filled: string[];
    fields_missing: string[];
    blockers: string[];
    message: string;
    application_status: string;
}

export interface ApplicationFillReviewRecord {
    id: number;
    application_id: number;
    ats_type: string;
    application_url: string;
    status: string;
    message?: string;
    fields_filled: string[];
    fields_missing: string[];
    blockers: string[];
    created_at: string;
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

export interface UserStatusResponse {
    user?: AppUser;
    resume?: ResumeStatus | null;
    preferences?: JobPreferencesPayload | null;
    profile?: ProfilePayload | null;
    application_profile?: ApplicationAnswerProfilePayload | null;
    quota?: AgentQuotaStatus | null;
}

export interface AuthResponse {
    user: AppUser;
    access_token: string;
    token_type: 'bearer';
}

export interface AgentQuotaStatus {
    agent_runs_used_today: number;
    agent_run_limit: number;
    agent_runs_remaining: number;
    auto_apply_enabled: boolean;
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
    return Boolean(localStorage.getItem(AUTH_TOKEN_KEY));
}

export function clearAuthSession() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(USER_EMAIL_KEY);
}

export function saveAuthSession(data: AuthResponse) {
    localStorage.setItem(AUTH_TOKEN_KEY, data.access_token);
    if (data.user?.email) {
        localStorage.setItem(USER_EMAIL_KEY, data.user.email);
    }
}

export function saveOAuthSession(token: string, email?: string | null) {
    localStorage.setItem(AUTH_TOKEN_KEY, token);
    if (email) {
        localStorage.setItem(USER_EMAIL_KEY, email);
    }
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
    const response = await fetch(`${API_URL}/user/status`, {
        headers: getAuthHeaders()
    });
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

export async function uploadResume(file: File) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_URL}/upload-resume`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
    });

    if (!response.ok) {
        throw new Error('Failed to upload resume');
    }

    return response.json();
}

export async function savePreferences(preferences: JobPreferencesPayload) {
    const response = await fetch(`${API_URL}/preferences`, {
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

export async function resolveApplicationLink(appId: number) {
    const response = await fetch(`${API_URL}/applications/${appId}/resolve-link`, {
        method: 'POST',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to resolve application link'));
    }
    return response.json();
}

export async function fillApplicationForReview(appId: number): Promise<ApplicationFillReviewResult> {
    const response = await fetch(`${API_URL}/applications/${appId}/fill-review`, {
        method: 'POST',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to prepare fill review'));
    }
    return response.json();
}

export async function getApplicationFillReviews(appId: number): Promise<ApplicationFillReviewRecord[]> {
    const response = await fetch(`${API_URL}/applications/${appId}/fill-reviews`, {
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to fetch fill-review history'));
    }
    return response.json();
}

export async function clearApplicationFillReviews(appId: number) {
    const response = await fetch(`${API_URL}/applications/${appId}/fill-reviews`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
    });
    if (!response.ok) {
        throw new Error(await getResponseDetail(response, 'Failed to clear fill-review history'));
    }
    return response.json();
}
