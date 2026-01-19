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
      .then(data => {
        if (data.user) {
          setUser(data.user);
          if (data.resume && resumeRef.current) {
            resumeRef.current.setExistingResume(data.resume.filename);
          }
        }
      })
      .catch(err => console.error("Error fetching user status", err));
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] [background-size:16px_16px] py-6 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      <div className="w-full max-w-4xl">
        <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-2xl overflow-hidden border border-white/20">

          {/* Header & Hero */}
          <div className="relative px-8 py-6 sm:px-12 bg-gray-800 overflow-hidden">
            {/* Decorative elements - subtle geometric patterns */}

            <div className="relative z-10 flex justify-between items-start">
              <div className="text-left">
                {/* Icon + Title */}
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-12 h-12 bg-white/25 backdrop-blur-sm rounded-xl flex items-center justify-center shadow-lg border border-white/30">
                    <svg className="w-7 h-7 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <h1 className="text-5xl font-black text-white tracking-tight drop-shadow-sm">
                    Job Hunter
                  </h1>
                </div>

                {/* Subtitle */}
                <p className="text-blue-50 text-lg font-medium max-w-2xl ml-15">
                  Your AI-powered career companion that finds and applies to your dream jobs on your behalf.
                </p>

                {/* Stats/Features */}
                <div className="flex gap-6 mt-6 ml-15">
                  <div className="flex items-center gap-2 text-white/95">
                    <div className="w-5 h-5 rounded-full bg-emerald-400/30 flex items-center justify-center border border-emerald-300/30">
                      <svg className="w-3 h-3 text-emerald-100" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <span className="text-sm font-semibold">AI-Powered</span>
                  </div>
                  <div className="flex items-center gap-2 text-white/95">
                    <div className="w-5 h-5 rounded-full bg-cyan-400/30 flex items-center justify-center border border-cyan-300/30">
                      <svg className="w-3 h-3 text-cyan-100" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <span className="text-sm font-semibold">Auto-Apply</span>
                  </div>
                  <div className="flex items-center gap-2 text-white/95">
                    <div className="w-5 h-5 rounded-full bg-purple-400/30 flex items-center justify-center border border-purple-300/30">
                      <svg className="w-3 h-3 text-purple-100" fill="currentColor" viewBox="0 0 20 20">
                        <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <span className="text-sm font-semibold">Smart Matching</span>
                  </div>
                </div>
              </div>

              {user && (
                <div className="flex flex-col items-end">
                  <div className={`px-5 py-2 rounded-lg text-xs font-bold uppercase tracking-wider shadow-lg border backdrop-blur-sm
                    ${user.subscription_tier === 'pro'
                      ? 'bg-gradient-to-r from-amber-400 to-orange-500 text-white border-amber-300/50'
                      : 'bg-white/20 text-white border-white/30'}`}>
                    {user.subscription_tier} Tier
                  </div>
                  <span className="text-xs text-blue-100 mt-2 font-medium">{user.email}</span>
                </div>
              )}
            </div>
          </div>
          <div className="px-8 py-6 sm:px-12 space-y-6">
            <section>
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-700 font-bold mr-3">1</div>
                <h2 className="text-xl font-semibold text-gray-800">Your Resume</h2>
              </div>
              <ResumeUpload ref={resumeRef} />
            </section>

            <div className="border-t border-gray-200"></div>

            <section>
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-700 font-bold mr-3">2</div>
                <h2 className="text-xl font-semibold text-gray-800">Job Preferences</h2>
              </div>
              <JobPreferences ref={prefsRef} />
            </section>

            <div className="border-t border-gray-200"></div>

            <section>
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-700 font-bold mr-3">3</div>
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
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-700 font-bold mr-3">4</div>
                <h2 className="text-xl font-semibold text-gray-800">History & Status</h2>
              </div>
              <AgentDashboard key={refreshHistory} />
            </section>

            <div className="border-t border-gray-200"></div>

            <section>
              <div className="flex items-center mb-3">
                <div className="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-700 font-bold mr-3">5</div>
                <h2 className="text-xl font-semibold text-gray-800">Manual Search</h2>
              </div>
              <JobSearch />
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App


