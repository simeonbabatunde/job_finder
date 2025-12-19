import { useState, forwardRef, useImperativeHandle } from 'react';
import { uploadResume } from '../api/client';

export interface ResumeUploadHandle {
  hasFile: boolean;
  setError: (msg: string | null) => void;
  handleUpload: (silent?: boolean) => Promise<boolean>;
}

export const ResumeUpload = forwardRef<ResumeUploadHandle>((_props, ref) => {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [isError, setIsError] = useState(false);

  useImperativeHandle(ref, () => ({
    hasFile: !!file,
    setError: (msg: string | null) => {
      setIsError(!!msg);
      if (msg) setMessage(msg);
    },
    handleUpload: async (silent: boolean = false) => {
      if (!file) return true; // No file is okay if already uploaded or skipped

      setUploading(true);
      setMessage('');
      try {
        await uploadResume(file);
        if (!silent) {
          setMessage('Resume uploaded successfully!');
        }
        setFile(null);
        return true;
      } catch (error) {
        setMessage('Error uploading resume.');
        console.error(error);
        return false;
      } finally {
        setUploading(false);
      }
    }
  }));

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

  return (
    <div className="w-full">
      <div
        className={`relative border-2 border-dashed rounded-xl p-6 text-center transition-all duration-200 ease-in-out ${dragActive
          ? 'border-gray-500 bg-gray-50'
          : isError
            ? 'border-red-500 bg-red-50 animate-pulse'
            : 'border-gray-300 hover:border-indigo-400 hover:bg-gray-50'
          }`}
        onDragEnter={(e) => { handleDrag(e); setIsError(false); setMessage(''); }}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={(e) => { handleDrop(e); setIsError(false); setMessage(''); }}
      >
        <input
          type="file"
          id="file-upload"
          onChange={(e) => { handleChange(e); setIsError(false); setMessage(''); }}
          className="hidden"
        />

        {file ? (
          <div className="flex flex-col items-center">
            <div className="bg-gray-200 text-gray-700 p-3 rounded-full mb-3">
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
            <div className="bg-gray-100 text-gray-400 p-3 rounded-full mb-3 group-hover:bg-gray-200 group-hover:text-gray-600 transition-colors">
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
          <div className="w-full bg-gray-200 rounded-full h-2.5 mb-2 overflow-hidden">
            <div className="bg-gray-600 h-2.5 rounded-full animate-pulse w-full"></div>
          </div>
        )}

        {message && (
          <div className={`mt-2 p-3 rounded-lg text-sm font-medium text-center ${isError ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-700'
            }`}>
            {message}
          </div>
        )}
      </div>
    </div>
  );
});

