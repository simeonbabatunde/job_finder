import { useState } from 'react';
import { uploadResume } from '../api/client';

export function ResumeUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;

    setUploading(true);
    setMessage('');
    try {
      await uploadResume(file);
      setMessage('Resume uploaded successfully!');
      setFile(null);
    } catch (error) {
      setMessage('Error uploading resume.');
      console.error(error);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="w-full">
      <div
        className={`relative border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 ease-in-out ${dragActive
          ? 'border-indigo-500 bg-indigo-50'
          : 'border-gray-300 hover:border-indigo-400 hover:bg-gray-50'
          }`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <input
          type="file"
          id="file-upload"
          onChange={handleChange}
          className="hidden"
        />

        {file ? (
          <div className="flex flex-col items-center">
            <div className="bg-indigo-100 text-indigo-600 p-3 rounded-full mb-3">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <p className="text-sm font-medium text-gray-900 mb-1">{file.name}</p>
            <p className="text-xs text-gray-500 mb-4">{(file.size / 1024).toFixed(0)} KB</p>
            <button
              onClick={() => setFile(null)}
              className="text-xs text-red-500 hover:text-red-700 font-medium"
            >
              Remove file
            </button>
          </div>
        ) : (
          <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center">
            <div className="bg-gray-100 text-gray-400 p-3 rounded-full mb-3 group-hover:bg-indigo-100 group-hover:text-indigo-500 transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <p className="text-sm font-medium text-gray-700">
              <span className="text-indigo-600 hover:text-indigo-700">Click to upload</span> or drag and drop
            </p>
            <p className="text-xs text-gray-500 mt-1">PDF, DOCX, or TXT (MAX. 5MB)</p>
          </label>
        )}
      </div>

      <div className="mt-4">
        {uploading && (
          <div className="w-full bg-gray-200 rounded-full h-2.5 mb-4 overflow-hidden">
            <div className="bg-indigo-600 h-2.5 rounded-full animate-pulse w-full"></div>
          </div>
        )}

        <button
          onClick={handleUpload}
          disabled={!file || uploading}
          className={`w-full py-3 px-4 rounded-lg text-white font-bold shadow-lg transition-all duration-200 ${!file || uploading
            ? 'bg-gray-300 cursor-not-allowed shadow-none'
            : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 hover:shadow-indigo-500/30 transform hover:-translate-y-0.5'
            }`}
        >
          {uploading ? 'Processing...' : 'Analyze Resume'}
        </button>
        {message && (
          <div className={`mt-4 p-3 rounded-lg text-sm font-medium text-center ${message.includes('Error') ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
            }`}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
}
