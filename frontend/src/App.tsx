import { ResumeUpload } from './components/ResumeUpload';
import { JobPreferences } from './components/JobPreferences';
import { JobSearch } from './components/JobSearch';

function App() {
  return (
    <div className="min-h-screen bg-slate-50 bg-[radial-gradient(#e5e7eb_1px,transparent_1px)] [background-size:16px_16px] py-12 px-4 sm:px-6 lg:px-8 flex items-center justify-center">
      <div className="w-full max-w-4xl">
        <div className="bg-white/90 backdrop-blur-xl rounded-2xl shadow-2xl overflow-hidden border border-white/20">
          <div className="px-8 py-10 sm:px-12">
            <div className="text-center mb-12">
              <h1 className="text-4xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600 mb-2">
                Job Finder
              </h1>
              <p className="text-slate-500 text-lg mb-8 max-w-2xl mx-auto">
                Your personal AI job hunter that works while you sleep.
              </p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left">
                <div className="bg-indigo-50/50 p-4 rounded-xl border border-indigo-100 hover:shadow-md transition-shadow">
                  <div className="text-2xl mb-2">⚡️</div>
                  <h3 className="font-semibold text-slate-900 text-sm">Auto-Apply</h3>
                  <p className="text-xs text-slate-500 mt-1">We submit applications to jobs that match your profile instantly.</p>
                </div>
                <div className="bg-emerald-50/50 p-4 rounded-xl border border-emerald-100 hover:shadow-md transition-shadow">
                  <div className="text-2xl mb-2">🎯</div>
                  <h3 className="font-semibold text-slate-900 text-sm">Smart Match</h3>
                  <p className="text-xs text-slate-500 mt-1">Our AI analyzes your skills to find the perfect fit.</p>
                </div>
                <div className="bg-orange-50/50 p-4 rounded-xl border border-orange-100 hover:shadow-md transition-shadow">
                  <div className="text-2xl mb-2">🔔</div>
                  <h3 className="font-semibold text-slate-900 text-sm">24/7 Watch</h3>
                  <p className="text-xs text-slate-500 mt-1">Never miss an opportunity with round-the-clock monitoring.</p>
                </div>
              </div>
            </div>

            <div className="space-y-12">
              <section>
                <div className="flex items-center mb-6">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">1</div>
                  <h2 className="text-xl font-semibold text-gray-800">Upload Resume</h2>
                </div>
                <ResumeUpload />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-6">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">2</div>
                  <h2 className="text-xl font-semibold text-gray-800">Job Preferences</h2>
                </div>
                <JobPreferences />
              </section>

              <div className="border-t border-gray-200"></div>

              <section>
                <div className="flex items-center mb-6">
                  <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold mr-3">3</div>
                  <h2 className="text-xl font-semibold text-gray-800">Search Jobs</h2>
                </div>
                <JobSearch />
              </section>
            </div>
          </div>
          <div className="bg-gray-50 px-8 py-6 sm:px-12 text-center text-sm text-gray-500">
            Powered by FastAPI & SQLModel
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
