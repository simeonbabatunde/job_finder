import { useState, forwardRef, useImperativeHandle, useEffect } from 'react';
import { savePreferences } from '../api/client';

export interface JobPreferencesHandle {
    submitPrefs: (silent?: boolean) => Promise<boolean>;
}

export const JobPreferences = forwardRef<JobPreferencesHandle>((_props, ref) => {
    const [formData, setFormData] = useState({
        role: '',
        experience_level: ['Intermediate'] as string[],
        location: '',
        job_type: ['Full-time'] as string[],
        min_match_score: 70,
        posted_within_days: 7,
    });
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState('');
    const [openDropdown, setOpenDropdown] = useState<'experience_level' | 'job_type' | null>(null);

    useImperativeHandle(ref, () => ({
        submitPrefs: async (silent: boolean = false) => {
            setSaving(true);
            setMessage('');
            try {
                // Convert strings to arrays for API
                const payload = {
                    ...formData,
                    role: formData.role.split(',').map(s => s.trim()).filter(s => s !== ''),
                    location: formData.location.split(',').map(s => s.trim()).filter(s => s !== ''),
                };
                await savePreferences(payload);
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
        setFormData(prev => {
            // Handle numeric fields
            if (name === 'min_match_score' || name === 'posted_within_days') {
                return { ...prev, [name]: parseInt(value) || 0 };
            }
            return { ...prev, [name]: value };
        });
    };

    const handleCheckboxChange = (name: 'job_type' | 'experience_level', value: string) => {
        setFormData(prev => {
            const currentArray = prev[name] as string[];
            const newArray = currentArray.includes(value)
                ? currentArray.filter(item => item !== value)
                : [...currentArray, value];
            return {
                ...prev,
                [name]: newArray
            };
        });
    };

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as HTMLElement;
            if (!target.closest('.relative')) {
                setOpenDropdown(null);
            }
        };

        if (openDropdown) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [openDropdown]);

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
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:border-gray-500 transition-shadow"
                            required
                            placeholder="e.g. Software Engineer, Data Scientist"
                        />
                        <p className="text-xs text-gray-500 mt-1">Separate multiple roles with commas</p>
                    </div>

                    <div className="relative">
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Experience Level</label>
                        <div
                            onClick={() => setOpenDropdown(openDropdown === 'experience_level' ? null : 'experience_level')}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 cursor-pointer hover:bg-gray-100 transition-colors flex justify-between items-center"
                        >
                            <span className="text-sm text-gray-700">
                                {formData.experience_level.length > 0
                                    ? `${formData.experience_level.length} Selected`
                                    : 'Select experience levels'}
                            </span>
                            <svg className="fill-current h-4 w-4 text-gray-700" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
                                <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" />
                            </svg>
                        </div>
                        {openDropdown === 'experience_level' && (
                            <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                                {['Intern', 'Entry-level', 'Intermediate', 'Senior', 'Staff', 'Principal', 'Manager', 'Director', 'Executive'].map(level => (
                                    <label key={level} className="flex items-center space-x-2 px-4 py-2 hover:bg-gray-100 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={formData.experience_level.includes(level)}
                                            onChange={() => handleCheckboxChange('experience_level', level)}
                                            className="w-4 h-4 text-gray-600 border-gray-300 rounded focus:ring-2 focus:ring-gray-500"
                                        />
                                        <span className="text-sm text-gray-700">{level}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Location</label>
                        <input
                            type="text"
                            name="location"
                            value={formData.location}
                            onChange={handleChange}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:border-gray-500 transition-shadow"
                            required
                            placeholder="e.g. Remote, NYC, San Francisco"
                        />
                        <p className="text-xs text-gray-500 mt-1">Separate multiple locations with commas</p>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                    <div className="relative">
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Job Type</label>
                        <div
                            onClick={() => setOpenDropdown(openDropdown === 'job_type' ? null : 'job_type')}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 cursor-pointer hover:bg-gray-100 transition-colors flex justify-between items-center"
                        >
                            <span className="text-sm text-gray-700">
                                {formData.job_type.length > 0
                                    ? `${formData.job_type.length} Selected`
                                    : 'Select job types'}
                            </span>
                            <svg className="fill-current h-4 w-4 text-gray-700" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">
                                <path d="M9.293 12.95l.707.707L15.657 8l-1.414-1.414L10 10.828 5.757 6.586 4.343 8z" />
                            </svg>
                        </div>
                        {openDropdown === 'job_type' && (
                            <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-lg shadow-lg">
                                {['Full-time', 'Contract', 'Part-time'].map(type => (
                                    <label key={type} className="flex items-center space-x-2 px-4 py-2 hover:bg-gray-100 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={formData.job_type.includes(type)}
                                            onChange={() => handleCheckboxChange('job_type', type)}
                                            className="w-4 h-4 text-gray-600 border-gray-300 rounded focus:ring-2 focus:ring-gray-500"
                                        />
                                        <span className="text-sm text-gray-700">{type}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Min Match Score (%)</label>
                        <input
                            type="number"
                            name="min_match_score"
                            min="0"
                            max="100"
                            value={formData.min_match_score}
                            onChange={handleChange}
                            className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:border-gray-500 transition-shadow"
                            required
                        />
                    </div>

                    <div>
                        <label className="block text-sm font-semibold text-gray-700 mb-1">Jobs Posted in the past...</label>
                        <div className="relative">
                            <select
                                name="posted_within_days"
                                value={formData.posted_within_days}
                                onChange={handleChange}
                                className="w-full bg-gray-50 border border-gray-300 rounded-lg px-4 py-2.5 pr-8 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:border-gray-500 appearance-none transition-shadow"
                            >
                                <option value={1}>24 Hrs</option>
                                <option value={2}>48 Hrs</option>
                                <option value={7}>1 Week</option>
                                <option value={14}>2 Weeks</option>
                                <option value={30}>1 Month</option>
                                <option value={90}>3 Months</option>
                                <option value={180}>6 Months</option>
                                <option value={365}>1 Year</option>
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

