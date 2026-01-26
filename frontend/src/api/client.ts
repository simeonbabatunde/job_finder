const API_URL = 'http://localhost:8000';

export function getAuthHeaders(): Record<string, string> {
    const email = localStorage.getItem('user_email');
    return email ? { 'X-User-Email': email } : {};
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
        const error = await response.json();
        throw new Error(error.detail || 'Failed to login');
    }

    const data = await response.json();
    localStorage.setItem('user_email', data.user.email);
    return data;
}

export async function register(email: string, password: string, profile: any) {
    const response = await fetch(`${API_URL}/auth/register`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ email, password, profile }),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to register');
    }

    const data = await response.json();
    localStorage.setItem('user_email', data.user.email);
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

    const data = await response.json();
    localStorage.setItem('user_email', data.user.email);
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

export async function savePreferences(preferences: any) {
    const response = await fetch(`${API_URL}/preferences`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            ...(getAuthHeaders() as any)
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
