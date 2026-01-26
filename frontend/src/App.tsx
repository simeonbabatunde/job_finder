import { useState, useEffect, useRef } from 'react';
import { ResumeUpload } from './components/ResumeUpload';
import type { ResumeUploadHandle } from './components/ResumeUpload';
import { JobPreferences } from './components/JobPreferences';
import type { JobPreferencesHandle } from './components/JobPreferences';
import { AgentControls } from './components/AgentControls';
import { AgentDashboard } from './components/AgentDashboard';
import { Login } from './components/Login';

function App() {
  const [refreshHistory, setRefreshHistory] = useState(0);
  const [user, setUser] = useState<{ email: string, subscription_tier: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAuth, setShowAuth] = useState<'login' | 'register' | null>(null);

  const resumeRef = useRef<ResumeUploadHandle>(null);
  const prefsRef = useRef<JobPreferencesHandle>(null);

  const refreshStatus = () => {
    const email = localStorage.getItem('user_email');
    if (email) {
      setLoading(true);
      fetch('http://localhost:8000/user/status', {
        headers: { 'X-User-Email': email }
      })
        .then(res => res.json())
        .then(data => {
          if (data.user) {
            setUser(data.user);
            if (data.resume && resumeRef.current) {
              resumeRef.current.setResumeData({
                filename: data.resume.filename,
                skills: data.resume.skills,
                summary: data.resume.summary
              });
            }
          }
        })
        .catch(err => console.error("Error fetching user status", err))
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshStatus();
  }, []);

  const handleLogout = () => {
    localStorage.removeItem('user_email');
    setUser(null);
  };

  const handleLoginSuccess = (u: any) => {
    setUser(u);
    setShowAuth(null);
    refreshStatus();
  };

  if (loading && localStorage.getItem('user_email')) return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-indigo-600"></div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] [background-size:16px_16px] py-6 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      <div className="w-full max-w-4xl">
        <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-2xl overflow-hidden border border-white/20">

          {/* Header & Hero */}
          <div className="relative px-8 py-8 sm:px-12 bg-slate-900 overflow-hidden">
            {/* Decorative background effects */}
            <div className="absolute top-0 right-0 -mt-20 -mr-20 w-96 h-96 bg-indigo-500/20 rounded-full blur-3xl"></div>
            <div className="absolute bottom-0 left-0 -mb-20 -ml-20 w-80 h-80 bg-violet-500/20 rounded-full blur-3xl"></div>

            <div className="relative z-10 flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
              <div className="text-left">
                {/* Icon + Title */}
                <div className="flex items-center gap-4 mb-3">
                  <div className="w-14 h-14 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-2xl flex items-center justify-center shadow-xl border border-white/20">
                    <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                    </svg>
                  </div>
                  <div>
                    <h1 className="text-4xl font-black text-white tracking-tight">
                      Job Hunter
                    </h1>
                    <div className="h-1 w-20 bg-indigo-500 rounded-full mt-1"></div>
                  </div>
                </div>

                {/* Subtitle */}
                <p className="text-slate-400 text-lg font-medium max-w-xl">
                  Your smart assistant that works 24/7 to find jobs, analyze fit, and apply automatically—while you focus on what matters.
                </p>
              </div>

              <div className="flex flex-col items-end">
                {user ? (
                  <>
                    <div className={`px-5 py-2 rounded-xl text-[10px] font-bold uppercase tracking-widest shadow-lg border backdrop-blur-md
                        ${user.subscription_tier === 'pro'
                        ? 'bg-gradient-to-r from-amber-400 to-orange-500 text-white border-amber-300/50'
                        : 'bg-white/10 text-white border-white/20'}`}>
                      {user.subscription_tier} Tier
                    </div>
                    <span className="text-[10px] text-slate-500 mt-2 font-mono">{user.email}</span>
                    <button onClick={handleLogout} className="text-[10px] text-indigo-400 font-bold uppercase mt-2 hover:text-indigo-300 tracking-widest">Sign Out</button>
                  </>
                ) : (
                  <button
                    onClick={() => setShowAuth('login')}
                    className="px-5 py-2 rounded-xl text-[10px] font-bold uppercase tracking-widest shadow-lg border backdrop-blur-md bg-white/10 text-white border-white/20 hover:bg-white/20 transition-all"
                  >
                    Sign In
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="px-8 py-10 sm:px-12 space-y-12">
            <section className="relative">
              <div className="flex items-center mb-6">
                <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-800 font-bold mr-4 border border-slate-200 shadow-sm">1</div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Your Resume</h2>
                  <p className="text-sm text-slate-500">Upload your latest experience to guide the AI.</p>
                </div>
              </div>
              <ResumeUpload ref={resumeRef} />
            </section>

            <section className="relative">
              <div className="flex items-center mb-6">
                <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-800 font-bold mr-4 border border-slate-200 shadow-sm">2</div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Job Preferences</h2>
                  <p className="text-sm text-slate-500">Define what roles and locations interest you.</p>
                </div>
              </div>
              <JobPreferences ref={prefsRef} />
            </section>

            <section className="relative">
              <div className="flex items-center mb-6">
                <div className="w-10 h-10 rounded-xl bg-indigo-50 flex items-center justify-center text-indigo-600 font-bold mr-4 border border-indigo-100 shadow-sm">3</div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-900 tracking-tight text-indigo-600">Search & Apply Automatically</h2>
                  <p className="text-sm text-slate-500">Let the agent handle the difficult part of job hunting for you.</p>
                </div>
              </div>
              <AgentControls
                resumeRef={resumeRef}
                prefsRef={prefsRef}
                isLoggedIn={!!user}
                onAuthRequired={() => setShowAuth('register')}
                onComplete={() => {
                  setRefreshHistory(prev => prev + 1);
                  refreshStatus();
                }}
              />
            </section>

            <section className="relative bg-slate-50/50 rounded-3xl p-8 border border-slate-100">
              <div className="flex items-center mb-6">
                <div className="w-10 h-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-800 font-bold mr-4 border border-slate-200 shadow-sm">4</div>
                <div>
                  <h2 className="text-2xl font-bold text-slate-900 tracking-tight">History & Status</h2>
                  <p className="text-sm text-slate-500">Track and view your generated applications.</p>
                </div>
              </div>
              <AgentDashboard key={refreshHistory} />
            </section>

          </div>
        </div>
      </div>

      {showAuth && (
        <Login
          initialMode={showAuth}
          onLoginSuccess={handleLoginSuccess}
          onClose={() => setShowAuth(null)}
        />
      )}
    </div>
  );
}

export default App
