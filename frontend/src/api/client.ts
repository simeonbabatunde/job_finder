const API_URL = 'http://localhost:8000';

export async function uploadResume(file: File) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${API_URL}/upload-resume`, {
        method: 'POST',
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
        },
    });

    if (!response.ok) {
        throw new Error('Failed to search jobs');
    }

    return response.json();
}
