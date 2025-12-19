import { useState, useEffect, useRef } from 'react';
import { ResumeUpload } from './components/ResumeUpload';
import type { ResumeUploadHandle } from './components/ResumeUpload';
import { JobPreferences } from './components/JobPreferences';
import type { JobPreferencesHandle } from './components/JobPreferences';
import { JobSearch } from './components/JobSearch';
import { AgentControls } from './components/AgentControls';
import { AgentDashboard } from './components/AgentDashboard';

function App() {
  const [refreshHistory, setRefreshHistory] = useState(0);
  const [user, setUser] = useState<{ email: string, subscription_tier: string } | null>(null);

  const resumeRef = useRef<ResumeUploadHandle>(null);
  const prefsRef = useRef<JobPreferencesHandle>(null);

  useEffect(() => {
    fetch('http://localhost:8000/user/status')
      .then(res => res.json())
      .then(data => setUser(data))
      .catch(err => console.error("Error fetching user status", err));
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] [background-size:16px_16px] py-12 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      <div className="w-full max-w-4xl">
        <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-2xl overflow-hidden border border-white/20">

          {/* Header & Hero */}
          <div className="px-8 py-8 sm:px-12">
            <div className="flex justify-between items-start mb-8">
              <div className="text-left">
                <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600 mb-2">
                  Job Finder
                </h1>
                <p className="text-slate-500 text-lg max-w-2xl">
                  Your personal AI job hunter.
                </p>
              </div>
              {user && (
                <div className="flex flex-col items-end">
                  <div className={`px-4 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider shadow-sm
                    ${user.subscription_tier === 'pro'
                      ? 'bg-gradient-to-r from-amber-400 to-orange-500 text-white'
                      : 'bg-slate-200 text-slate-600'}`}>
                    {user.subscription_tier} Tier
                  </div>
                  <span className="text-[10px] text-slate-400 mt-1">{user.email}</span>
                </div>
              )}
            </div>

            <div className="space-y-8">
              <section>
                <div className="flex items-center mb-4">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">1</div>
                  <h2 className="text-xl font-semibold text-gray-800">Your Resume</h2>
                </div>
                <ResumeUpload ref={resumeRef} />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-4">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">2</div>
                  <h2 className="text-xl font-semibold text-gray-800">Job Preferences</h2>
                </div>
                <JobPreferences ref={prefsRef} />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-4">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">3</div>
                  <h2 className="text-xl font-semibold text-gray-800">Apply Automatically</h2>
                </div>
                <AgentControls
                  resumeRef={resumeRef}
                  prefsRef={prefsRef}
                  onComplete={() => setRefreshHistory(prev => prev + 1)}
                />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-4">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">4</div>
                  <h2 className="text-xl font-semibold text-gray-800">History & Status</h2>
                </div>
                <AgentDashboard key={refreshHistory} />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-4">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">5</div>
                  <h2 className="text-xl font-semibold text-gray-800">Manual Search</h2>
                </div>
                <JobSearch />
              </section>
            </div>
          </div>

          <div className="bg-gray-50 px-8 py-6 sm:px-12 text-center text-sm text-gray-500">
            Powered by LangGraph, FastAPI & SQLModel
          </div>
        </div>
      </div>
    </div>
  )
}

export default App


