import { useState } from 'react';
import { savePreferences } from '../api/client';

export function JobPreferences() {
    const [formData, setFormData] = useState({
        role: '',
        location: '',
        job_type: 'Full-time',
        min_salary: 0,
    });
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState('');

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage('');

        try {
            await savePreferences(formData);
            setMessage('Preferences saved successfully!');
        } catch (error) {
            setMessage('Error saving preferences.');
            console.error(error);
        } finally {
            setSaving(false);
        }
    };

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: name === 'min_salary' ? parseInt(value) || 0 : value
        }));
    };

    return (
        <div className="w-full">
            <form onSubmit={handleSubmit} className="space-y-5">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Target Role</label>
                        <input
                            type="text"
                            name="role"
                            value={formData.role}
                            onChange={handleChange}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                            required
                            placeholder="e.g. Software Engineer"
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Location</label>
                        <input
                            type="text"
                            name="location"
                            value={formData.location}
                            onChange={handleChange}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                            required
                            placeholder="e.g. Remote, NYC"
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Job Type</label>
                        <div className="relative">
                            <select
                                name="job_type"
                                value={formData.job_type}
                                onChange={handleChange}
                                className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 pr-8 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 appearance-none transition-shadow"
                            >
                                <option>Full-time</option>
                                <option>Contract</option>
                                <option>Part-time</option>
                            </select>
                            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700">
                                <svg className="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" /></svg>
                            </div>
                        </div>
                    </div>

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Min Annual Salary ($)</label>
                        <input
                            type="number"
                            name="min_salary"
                            value={formData.min_salary}
                            onChange={handleChange}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-shadow"
                            required
                        />
                    </div>
                </div>

                <button
                    type="submit"
                    disabled={saving}
                    className={`w-full py-3 px-4 rounded-lg text-white font-bold shadow-lg transition-all duration-200 mt-2 ${saving
                            ? 'bg-gray-300 cursor-not-allowed shadow-none'
                            : 'bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 hover:shadow-emerald-500/30 transform hover:-translate-y-0.5'
                        }`}
                >
                    {saving ? 'Saving...' : 'Save Preferences'}
                </button>
                {message && (
                    <div className={`mt-4 p-3 rounded-lg text-sm font-medium text-center ${message.includes('Error') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
                        }`}>
                        {message}
                    </div>
                )}
            </form>
        </div>
    );
}
