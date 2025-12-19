import { useState, forwardRef, useImperativeHandle } from 'react';
import { savePreferences } from '../api/client';

export interface JobPreferencesHandle {
    submitPrefs: (silent?: boolean) => Promise<boolean>;
}

export const JobPreferences = forwardRef<JobPreferencesHandle>((_props, ref) => {
    const [formData, setFormData] = useState({
        role: '',
        experience_level: 'Intermediate',
        location: '',
        job_type: 'Full-time',
        min_salary: 0,
        posted_within_weeks: 1,
    });
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState('');

    useImperativeHandle(ref, () => ({
        submitPrefs: async (silent: boolean = false) => {
            setSaving(true);
            setMessage('');
            try {
                await savePreferences(formData);
                if (!silent) {
                    setMessage('Preferences saved successfully!');
                }
                return true;
            } catch (error) {
                setMessage('Error saving preferences.');
                console.error(error);
                return false;
            } finally {
                setSaving(false);
            }
        }
    }));

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;
        setFormData(prev => ({
            ...prev,
            [name]: (name === 'min_salary' || name === 'posted_within_weeks') ? parseInt(value) || 0 : value
        }));
    };

    return (
        <div className="w-full">
            <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
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
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Experience Level</label>
                        <div className="relative">
                            <select
                                name="experience_level"
                                value={formData.experience_level}
                                onChange={handleChange}
                                className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 pr-8 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 appearance-none transition-shadow"
                            >
                                <option>Intern</option>
                                <option>Entry-level</option>
                                <option>Intermediate</option>
                                <option>Senior</option>
                                <option>Staff</option>
                                <option>Principal</option>
                                <option>Manager</option>
                                <option>Director</option>
                                <option>Executive</option>
                            </select>
                            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700">
                                <svg className="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" /></svg>
                            </div>
                        </div>
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

                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
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

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Jobs Posted in the past...</label>
                        <div className="relative">
                            <select
                                name="posted_within_weeks"
                                value={formData.posted_within_weeks}
                                onChange={handleChange}
                                className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 pr-8 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 appearance-none transition-shadow"
                            >
                                <option value={1}>1 Week</option>
                                <option value={2}>2 Weeks</option>
                                <option value={3}>3 Weeks</option>
                                <option value={4}>4 Weeks</option>
                                <option value={5}>5 Weeks</option>
                                <option value={6}>6 Weeks</option>
                                <option value={7}>7 Weeks</option>
                                <option value={8}>8 Weeks</option>
                                <option value={9}>9 Weeks</option>
                                <option value={10}>10 Weeks</option>
                            </select>
                            <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-gray-700">
                                <svg className="fill-current h-4 w-4" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20"><path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" /></svg>
                            </div>
                        </div>
                    </div>
                </div>

                {saving && (
                    <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2 overflow-hidden">
                        <div className="bg-emerald-500 h-2.5 rounded-full animate-pulse w-full"></div>
                    </div>
                )}

                {message && (
                    <div className={`mt-4 p-3 rounded-lg text-sm font-medium text-center ${message.includes('Error') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
                        }`}>
                        {message}
                    </div>
                )}
            </div>
        </div>
    );
});

