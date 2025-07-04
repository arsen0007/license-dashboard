import React, { useState, useEffect, useRef } from 'react';
import { UploadCloud, BarChart2, Download, Play, XCircle, CheckCircle, AlertTriangle, Cpu, Calendar, User, Link as LinkIcon, Loader } from 'lucide-react';
import Papa from 'papaparse';

// Helper Components
const Card = ({ children, className = '' }) => (<div className={`card ${className}`}>{children}</div>);
const StatCard = ({ icon, title, value, color }) => (<Card className="p-4 flex-col"><div className="stat-card-header"><p>{title}</p>{React.cloneElement(icon, { className: `icon ${color}` })}</div><p className="stat-card-value">{value}</p></Card>);
const LogDisplay = ({ logs }) => {
  const logContainerRef = useRef(null);
  useEffect(() => { if (logContainerRef.current) { logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight; } }, [logs]);
  const formatLog = (log) => {
    if (typeof log !== 'string') return "log-default";
    if (log.includes("-> EXACT MATCH FOUND!")) return "log-success";
    if (log.includes("-> STATUS: Admit Date Mismatch")) return "log-warning";
    if (log.includes("-> STATUS: Not Found")) return "log-error";
    if (log.includes("--- [Module Stop]")) return "log-orange";
    if (log.includes("--- [Module")) return "log-module";
    if (log.includes("-> WARNING:") || log.includes("ERROR:") || log.includes("!!!")) return "log-orange";
    return "log-default";
  };
  return (<div ref={logContainerRef} className="log-display-container">{logs.map((log, index) => { if (typeof log !== 'string') return null; return (<p key={index} className={formatLog(log)} style={{ textIndent: log.startsWith('  ') ? '1em' : '0' }}>{log}</p>); })}</div>);
};

// Column Mapping Modal Component
const ColumnMappingModal = ({ isOpen, onClose, headers, onConfirm }) => {
    const [mapping, setMapping] = useState({ 'first name': '', 'last name': '', 'admit date': '' });
    useEffect(() => {
        const autoMap = (header) => {
            const lowerHeader = header.toLowerCase();
            if (lowerHeader.includes('first')) return 'first name';
            if (lowerHeader.includes('last')) return 'last name';
            if (lowerHeader.includes('admit') || lowerHeader.includes('admission')) return 'admit date';
            return null;
        };
        const newMapping = { 'first name': '', 'last name': '', 'admit date': '' };
        headers.forEach(header => {
            const targetField = autoMap(header);
            if (targetField && !newMapping[targetField]) { newMapping[targetField] = header; }
        });
        setMapping(newMapping);
    }, [headers]);
    if (!isOpen) return null;
    const handleConfirm = () => {
        if (!mapping['first name'] || !mapping['last name'] || !mapping['admit date']) { alert('Please map all required fields.'); return; }
        onConfirm(mapping);
    };
    const renderSelect = (field) => ( <div className="modal-field" key={field}><label htmlFor={field}>Map to "{field}"</label><select id={field} value={mapping[field]} onChange={(e) => setMapping(prev => ({ ...prev, [field]: e.target.value }))}><option value="" disabled>Select a column...</option>{headers.map(header => (<option key={header} value={header}>{header}</option>))}</select></div> );
    return ( <div className="modal-overlay"><div className="modal-content"><h2 className="modal-title">Map Your CSV Columns</h2><p className="modal-subtitle">Select which columns from your file correspond to the required data fields.</p><div className="modal-body">{Object.keys(mapping).map(renderSelect)}</div><div className="modal-footer"><button onClick={onClose} className="modal-button-secondary">Cancel</button><button onClick={handleConfirm} className="modal-button-primary">Confirm & Start</button></div></div></div> );
};

// Main App Component
export default function App() {
  const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:5001';
  
  const [file, setFile] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [selectedState, setSelectedState] = useState('georgia');
  const [logs, setLogs] = useState(["Awaiting process start..."]);
  const [results, setResults] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [isFinished, setIsFinished] = useState(false);
  const [error, setError] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [csvHeaders, setCsvHeaders] = useState([]);
  const [jobId, setJobId] = useState(null);
  const pollingIntervalRef = useRef(null);

  useEffect(() => {
    return () => {
        if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
        }
    };
  }, []);

  const handleFileChange = (e) => {
    const uploadedFile = e.target.files[0];
    if (uploadedFile && (uploadedFile.type === "text/csv" || uploadedFile.name.endsWith('.csv'))) {
        setFile(uploadedFile);
        setError('');
        Papa.parse(uploadedFile, {
            header: true, skipEmptyLines: true, preview: 1,
            complete: (result) => {
                if (result.data[0]) {
                    setCsvHeaders(Object.keys(result.data[0]));
                    setIsModalOpen(true);
                } else { setError("Could not read headers from CSV."); }
            }
        });
    } else { setError("Please upload a valid .csv file."); setFile(null); }
    e.target.value = null;
  };

  const handleDragOver = (e) => e.preventDefault();
  const handleDrop = (e) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile && (droppedFile.type === "text/csv" || droppedFile.name.endsWith('.csv'))) {
        setFile(droppedFile);
        setError('');
        Papa.parse(droppedFile, {
            header: true, skipEmptyLines: true, preview: 1,
            complete: (result) => {
                if (result.data[0]) {
                    setCsvHeaders(Object.keys(result.data[0]));
                    setIsModalOpen(true);
                } else { setError("Could not read headers from CSV."); }
            }
        });
    } else { setError("Please upload a valid .csv file."); setFile(null); }
  };

  const pollJobStatus = (id) => {
    pollingIntervalRef.current = setInterval(async () => {
        try {
            const res = await fetch(`${API_BASE_URL}/status/${id}`);
            if (!res.ok) {
                clearInterval(pollingIntervalRef.current);
                setError("Could not retrieve job status.");
                setIsRunning(false);
                return;
            }
            const data = await res.json();
            setLogs(data.logs || []);
            
            const jobStatus = data.status;
            if (jobStatus === 'finished' || jobStatus === 'failed') {
                clearInterval(pollingIntervalRef.current);
                setIsRunning(false);
                setIsFinished(true);
                if (data.meta && data.meta.results) {
                    setResults(JSON.parse(data.meta.results));
                }
                if (jobStatus === 'failed') {
                    setError(data.meta.error || "Job failed without a specific error message.");
                }
            }
        } catch (e) {
            clearInterval(pollingIntervalRef.current);
            setError("Error checking job status.");
            setIsRunning(false);
        }
    }, 3000);
  };

  const startJob = async (columnMapping) => {
    if (!file || !apiKey || !columnMapping) { setError("Missing file, API key, or column mapping."); return; }
    
    setIsModalOpen(false);
    setError(''); setIsRunning(true); setIsFinished(false); setLogs(["Submitting job to the queue..."]); setResults([]);
    if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('apiKey', apiKey);
    formData.append('state', selectedState);
    formData.append('mapping', JSON.stringify(columnMapping));

    try {
      const response = await fetch(`${API_BASE_URL}/start-scraping`, { method: 'POST', body: formData });
      if (!response.ok) { const errData = await response.json(); throw new Error(errData.error || 'Backend error'); }
      
      const { job_id } = await response.json();
      setJobId(job_id);
      setLogs(prev => [...prev, `Job successfully submitted with ID: ${job_id}`, "Waiting for worker to start..."]);
      pollJobStatus(job_id);

    } catch (e) {
      setError(`Failed to start job: ${e.message}`);
      setIsRunning(false);
    }
  };
  
  // --- THESE FUNCTIONS ARE NOW CORRECTLY INCLUDED ---
  const downloadCSV = () => {
    if(results.length === 0) return;
    const headers = Object.keys(results[0]);
    const csvContent = [ headers.join(','), ...results.map(row => headers.map(header => `"${row[header] || ''}"`).join(',')) ].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', `verification_results_${selectedState}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const getStats = () => {
    const total = results.length;
    if (total === 0) return { total: 0, matched: 0, notFound: 0, mismatch: 0 };
    const matched = results.filter(r => r.status && (r.status.toLowerCase().includes('active') || r.status.toLowerCase().includes('inactive'))).length;
    const notFound = results.filter(r => r.status && r.status.toLowerCase().includes('not found')).length;
    const mismatch = results.filter(r => r.status && (r.status.toLowerCase().includes('mismatch') || r.status.toLowerCase().includes('failed'))).length;
    return { total, matched, notFound, mismatch };
  };
  const stats = getStats();
  // --- END OF INCLUDED FUNCTIONS ---

  return (
    <>
      <ColumnMappingModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} headers={csvHeaders} onConfirm={startJob} />
      <div className="app-container">
        <div className="main-content">
          <header>
            <h1 className="main-title">License Verification Dashboard</h1>
            <p className="subtitle">Automated verification with Background Worker</p>
          </header>
          <main className="grid-container">
            <div className="controls-column">
              <Card className="p-6">
                <h2 className="section-title"><span className="step-number">1</span>Configuration</h2>
                <div className="config-section"><label className="label">Select State</label><div className="state-selection">{['georgia', 'california'].map(state => (<button key={state} onClick={() => setSelectedState(state)} disabled={isRunning} className={`state-button ${selectedState === state ? 'active' : ''}`}>{state}</button>))}</div></div>
                <div className="config-section"><label htmlFor="api-key" className="label">Gemini API Key</label><input type="password" id="api-key" value={apiKey} onChange={e => setApiKey(e.target.value)} disabled={isRunning} className="input-field" placeholder="Enter your API key" /></div>
                <div className="config-section"><label className="label">Upload CSV File</label><div onDrop={isRunning ? null : handleDrop} onDragOver={isRunning ? null : handleDragOver} className={`dropzone ${isRunning ? 'disabled' : ''}`} onClick={isRunning ? null : () => document.getElementById('file-upload').click()}><input type="file" id="file-upload" className="hidden" onChange={handleFileChange} accept=".csv" disabled={isRunning} /><UploadCloud className="dropzone-icon" /><p className="dropzone-text">{file ? 'File ready:' : 'Drag & drop or click to upload'}</p>{file && <p className="filename">{file.name}</p>}</div></div>
                {error && <div className="error-message"><AlertTriangle size={16} /> {error}</div>}
                <div className="button-group">{isRunning && (<div className="running-indicator"><Loader className="spinner"/>Processing...</div>)}</div>
              </Card>
            </div>
            <div className="results-column">
              <Card className="p-6">
                  <h2 className="section-title"><span className="step-number">2</span>Live Process Log</h2>
                  <LogDisplay logs={logs} />
              </Card>
              {isFinished && (
                <Card className="p-6 animate-fade-in">
                    <div className="results-header"><div><h2 className="section-title"><span className="step-number">3</span>Results & Download</h2><p className="subtitle">Verification process completed.</p></div><button onClick={downloadCSV} className="download-button"><Download size={16} /> Download CSV</button></div>
                    <div className="stats-grid"><StatCard icon={<BarChart2 />} title="Total Processed" value={stats.total} color="text-cyan" /><StatCard icon={<CheckCircle />} title="Matched" value={stats.matched} color="text-green" /><StatCard icon={<XCircle />} title="Not Found" value={stats.notFound} color="text-red" /><StatCard icon={<AlertTriangle />} title="Mismatch" value={stats.mismatch} color="text-yellow" /></div>
                    <div className="table-container"><table className="results-table"><thead><tr><th><User size={14} />Name</th><th><Calendar size={14} />Admit Date</th><th><Cpu size={14} />Status</th><th>Discipline</th><th><LinkIcon size={14} />Links</th></tr></thead>
                          <tbody>{results.map((row, index) => (<tr key={index}><td>{row['first name']} {row['last name']}</td><td>{row['admit date']}</td><td><span className={`status-pill ${row.status && row.status.toLowerCase().includes('active') ? 'status-green' : row.status && row.status.toLowerCase().includes('inactive') ? 'status-gray' : row.status && row.status.toLowerCase().includes('not found') ? 'status-red' : row.status && (row.status.toLowerCase().includes('mismatch') || row.status.toLowerCase().includes('failed')) ? 'status-yellow' : 'status-gray'}`}>{row.status || 'N/A'}</span></td><td>{row.discipline || 'N/A'}</td><td>{row['profile links'] && <a href={row['profile links']} target="_blank" rel="noopener noreferrer" className="link">Profile</a>}{row['unmatched profile links'] && <a href={row['unmatched profile links']} target="_blank" rel="noopener noreferrer" className="link-yellow">Unmatched</a>}</td></tr>))}</tbody>
                    </table></div>
                </Card>
              )}
            </div>
          </main>
        </div>
      </div>
    </>
  );
}