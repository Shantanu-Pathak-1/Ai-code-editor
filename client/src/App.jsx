import React, { useState, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { api } from './apiService';

const getFileIcon = (filename) => {
  if (filename.endsWith('.html')) return <i className="fab fa-html5" style={{ color: '#e34c26' }}></i>;
  if (filename.endsWith('.css')) return <i className="fab fa-css3-alt" style={{ color: '#264de4' }}></i>;
  if (filename.endsWith('.js') || filename.endsWith('.jsx')) return <i className="fab fa-js" style={{ color: '#f7df1e' }}></i>;
  if (filename.endsWith('.json')) return <i className="fas fa-brackets-curly" style={{ color: '#cb3837' }}></i>;
  if (filename.endsWith('.py')) return <i className="fab fa-python" style={{ color: '#306998' }}></i>;
  return <i className="fas fa-file-code" style={{ color: '#8b949e' }}></i>;
};

const getLanguage = (filename) => {
  if (filename.endsWith('.html')) return 'html';
  if (filename.endsWith('.css')) return 'css';
  if (filename.endsWith('.js')) return 'javascript';
  return 'plaintext';
};

function App() {
  const [files, setFiles] = useState({
    'index.html': { name: 'index.html', language: 'html', value: '\n<h1>Hello Shantanu ✨</h1>' },
    'style.css': { name: 'style.css', language: 'css', value: '/* Type your CSS here */\nbody {\n  background-color: #1e1e1e;\n  color: white;\n}' },
    'script.js': { name: 'script.js', language: 'javascript', value: 'console.log("Ethrix Cloud Terminal Active!");' }
  });
  
  const [activeTab, setActiveTab] = useState('index.html'); 
  const [saveStatus, setSaveStatus] = useState('☁️ Synced');
  
  // UI Toggles
  const [showTerminal, setShowTerminal] = useState(true);
  const [isTerminalMinimized, setIsTerminalMinimized] = useState(false);
  const [showExplorer, setShowExplorer] = useState(true); 
  const [websiteTheme, setWebsiteTheme] = useState('Auto Theme');
  const [activeMode, setActiveMode] = useState('Copilot Mode');

  // File Creation & Rename States
  const [isCreatingFile, setIsCreatingFile] = useState(false);
  const [newFileName, setNewFileName] = useState('');
  const [renamingFile, setRenamingFile] = useState(null);
  const [renameInput, setRenameInput] = useState('');

  // AI Chat Workflow States
  const [chatMessages, setChatMessages] = useState([{ role: 'ai', text: 'Hi Shantanu! 🖤 Main Shanvika hu. Aaj kis theme ki website banani hai?' }]);
  const [aiInput, setAiInput] = useState('');
  const [aiWorkflowStatus, setAiWorkflowStatus] = useState(''); 
  const [isTyping, setIsTyping] = useState(false);
  
  const filesRef = useRef(files); 
  const terminalRef = useRef(null);
  const xtermInstance = useRef(null);
  const fitAddonRef = useRef(null); 
  const chatEndRef = useRef(null);

  useEffect(() => { filesRef.current = files; }, [files]);
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [chatMessages, aiWorkflowStatus]);

  const runLivePreview = () => {
    const currentFiles = filesRef.current;
    const combinedCode = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <title>Ethrix-Forge Live Preview</title>
        <style>${currentFiles['style.css']?.value || ''}</style>
      </head>
      <body>
        ${currentFiles['index.html']?.value || ''}
        <script>${currentFiles['script.js']?.value || ''}<\/script>
      </body>
      </html>
    `;
    const previewWindow = window.open('', 'EthrixLivePreview');
    if (previewWindow) {
      previewWindow.document.open();
      previewWindow.document.write(combinedCode);
      previewWindow.document.close();
    }
  };

  const handleCreateFile = (e) => {
    if (e.key === 'Enter' && newFileName.trim() !== '') {
      const fileName = newFileName.trim();
      if (!files[fileName]) {
        setFiles({ ...files, [fileName]: { name: fileName, language: getLanguage(fileName), value: '' } });
        setActiveTab(fileName);
      }
      setIsCreatingFile(false);
      setNewFileName('');
    } else if (e.key === 'Escape') {
      setIsCreatingFile(false);
    }
  };

  const startRename = (fileName, e) => {
    e.stopPropagation();
    setRenamingFile(fileName);
    setRenameInput(fileName);
  };

  const handleRenameFile = (e, oldFileName) => {
    if (e.key === 'Enter' && renameInput.trim() !== '' && renameInput !== oldFileName) {
      const newName = renameInput.trim();
      const newFiles = { ...files };
      newFiles[newName] = { ...newFiles[oldFileName], name: newName, language: getLanguage(newName) };
      delete newFiles[oldFileName];
      setFiles(newFiles);
      if (activeTab === oldFileName) setActiveTab(newName);
      setRenamingFile(null);
    } else if (e.key === 'Escape') {
      setRenamingFile(null);
    }
  };

  const deleteFile = (fileName, e) => {
    e.stopPropagation();
    const newFiles = { ...files };
    delete newFiles[fileName];
    setFiles(newFiles);
    if (activeTab === fileName) setActiveTab(Object.keys(newFiles)[0] || '');
  };

  // 🚀 THE NEW AGENTIC WORKFLOW SUBMIT LOGIC 🚀
  const handleAISubmit = async (e) => {
    if (e.key === 'Enter' && aiInput.trim() !== '') {
      const prompt = aiInput.trim();
      setAiInput('');
      setChatMessages(prev => [...prev, { role: 'user', text: prompt }]);
      setAiWorkflowStatus('🧠 Reading context & planning architecture...');

      try {
        // ✨ Context Builder: Saari current files ko array mein convert kar rahe hain
        const existingFilesArray = Object.values(filesRef.current).map(f => ({
          filename: f.name,
          language: f.language,
          code: f.value
        }));
        
        const agenticPrompt = `Theme: ${websiteTheme}. Mode: ${activeMode}. User Request: ${prompt}`;

        // apiService mein naya update bhej rahe hain
        const generatedFiles = await api.generateCode(agenticPrompt, existingFilesArray, "gemini");
        
        if (generatedFiles && generatedFiles.length > 0) {
          setAiWorkflowStatus(`📄 Writing code in ${generatedFiles.length} files...`);
          
          const updatedFiles = { ...filesRef.current };
          generatedFiles.forEach(f => {
            updatedFiles[f.filename] = { name: f.filename, language: f.language || 'plaintext', value: f.code };
          });
          
          setTimeout(() => {
            setFiles(updatedFiles);
            // Open HTML or the first changed file
            const fileToOpen = generatedFiles.find(f => f.filename.endsWith('.html'))?.filename || generatedFiles[0].filename;
            setActiveTab(fileToOpen);
            
            if (!showExplorer) setShowExplorer(true);
            setAiWorkflowStatus(''); 
            setChatMessages(prev => [...prev, { role: 'ai', text: `✅ Maine ${generatedFiles.length} file(s) mein code update kar diya hai! ✨ Press Run in New Tab to check.` }]);
          }, 1000);
        }
      } catch (err) {
        setAiWorkflowStatus('');
        setChatMessages(prev => [...prev, { role: 'ai', text: `Oops! Error: ${err.message} 🥺` }]);
      }
    }
  };

  // ✨ FIX 1: Terminal Expand/Minimize Logic 
  const toggleTerminalSize = () => {
    setIsTerminalMinimized(!isTerminalMinimized);
  };

  // Jab terminal minimize se wapas bada ho, usko resize karo taaki UI na fate
  useEffect(() => {
    if (!isTerminalMinimized && fitAddonRef.current) {
      setTimeout(() => {
        fitAddonRef.current.fit();
      }, 350); // CSS transition ke baad resize
    }
  }, [isTerminalMinimized]);

  const clearTerminal = () => { 
    if (xtermInstance.current) { xtermInstance.current.clear(); xtermInstance.current.write('user@ethrix:~$ '); } 
  };

  // ✨ FIX 2: Terminal ko wapas laane ka function
  const reopenTerminal = () => {
    setShowTerminal(true);
    setIsTerminalMinimized(false);
  };

  // Real Terminal Lifecycle
  useEffect(() => {
    if (!showTerminal || !terminalRef.current) return;
    
    // Agar terminal already nahi bana hai toh naya banao
    if (!xtermInstance.current) {
      const term = new window.Terminal({ theme: { background: '#0d1117', foreground: '#c9d1d9' }, fontFamily: '"Fira Code", monospace', fontSize: 13 });
      const fitAddon = new window.FitAddon.FitAddon();
      fitAddonRef.current = fitAddon;

      term.loadAddon(fitAddon);
      term.open(terminalRef.current);
      fitAddon.fit();
      xtermInstance.current = term;

      term.writeln('\x1b[1;32mEthrix Local Terminal Started.\x1b[0m');
      term.write('user@ethrix:~$ ');

      let inputBuffer = '';
      term.onData((key) => {
        if (key === '\r') {
          term.writeln('');
          if (inputBuffer.trim() === 'clear') { term.clear(); }
          else if (inputBuffer.trim() !== '') { term.writeln(`bash: ${inputBuffer}: command not found`); }
          inputBuffer = '';
          term.write('user@ethrix:~$ ');
        } else if (key === '\x7F') {
          if (inputBuffer.length > 0) { inputBuffer = inputBuffer.slice(0, -1); term.write('\b \b'); }
        } else { inputBuffer += key; term.write(key); }
      });

      const resizeObserver = new ResizeObserver(() => {
        if (fitAddonRef.current && !isTerminalMinimized) fitAddonRef.current.fit();
      });
      resizeObserver.observe(terminalRef.current);
      
      return () => resizeObserver.disconnect();
    }
  }, [showTerminal]);

  // Cleanup jab terminal close (X) dabaya jaye
  useEffect(() => {
    if (!showTerminal && xtermInstance.current) {
      xtermInstance.current.dispose();
      xtermInstance.current = null;
      fitAddonRef.current = null;
    }
  }, [showTerminal]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: '#0d1117', color: '#c9d1d9', fontFamily: 'sans-serif', overflow: 'hidden' }}>
      
      {/* 🚀 MAIN CONTENT AREA (3 Panels) */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        
        {/* 📁 LEFT PANE: Smart File Explorer */}
        {showExplorer && (
          <div style={{ width: '250px', backgroundColor: '#010409', borderRight: '1px solid #30363d', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '12px 15px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #30363d', backgroundColor: '#161b22' }}>
              <span style={{ fontSize: '11px', fontWeight: 'bold', color: '#8b949e', letterSpacing: '1px' }}>EXPLORER</span>
              <div style={{ display: 'flex', gap: '12px', color: '#c9d1d9', fontSize: '13px' }}>
                <i className="fas fa-file-plus" onClick={() => setIsCreatingFile(true)} style={{ cursor: 'pointer' }} title="New File"></i>
                <i className="fas fa-folder-plus" onClick={() => alert("Folder logic connecting soon!")} style={{ cursor: 'pointer' }} title="New Folder"></i>
                <i className="fas fa-upload" onClick={() => alert("Upload connected soon!")} style={{ cursor: 'pointer' }} title="Upload"></i>
                <i className="fas fa-download" onClick={() => alert("Download connected soon!")} style={{ cursor: 'pointer' }} title="Download"></i>
                {/* ✨ FIX 3: GitHub Icon Wapas Aa Gaya! ✨ */}
                <i className="fab fa-github" onClick={() => alert("GitHub Sync soon!")} style={{ cursor: 'pointer' }} title="GitHub"></i>
              </div>
            </div>
            
            <div style={{ padding: '10px 5px', overflowY: 'auto' }}>
              {isCreatingFile && (
                <div style={{ padding: '5px 10px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: '#161b22', borderRadius: '4px', marginBottom: '5px' }}>
                  <i className="fas fa-file" style={{ color: '#8b949e' }}></i>
                  <input autoFocus type="text" value={newFileName} onChange={(e) => setNewFileName(e.target.value)} onKeyDown={handleCreateFile} onBlur={() => setIsCreatingFile(false)} placeholder="name.js" style={{ background: 'transparent', border: 'none', color: '#fff', outline: 'none', width: '100%', fontSize: '13px' }} />
                </div>
              )}
              
              {Object.keys(files).map((fileName) => (
                <div key={fileName} onClick={() => setActiveTab(fileName)} style={{ padding: '8px 10px', cursor: 'pointer', borderRadius: '4px', backgroundColor: activeTab === fileName ? 'rgba(88, 166, 255, 0.1)' : 'transparent', color: activeTab === fileName ? '#58a6ff' : '#c9d1d9', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: 0 }}>
                    {getFileIcon(fileName)}
                    {renamingFile === fileName ? (
                      <input autoFocus type="text" value={renameInput} onChange={(e) => setRenameInput(e.target.value)} onKeyDown={(e) => handleRenameFile(e, fileName)} onBlur={() => setRenamingFile(null)} style={{ background: '#161b22', border: '1px solid #58a6ff', color: '#fff', outline: 'none', width: '100%', fontSize: '13px', padding: '2px 4px' }} />
                    ) : (
                      <span style={{ fontSize: '13px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{fileName}</span>
                    )}
                  </div>
                  {renamingFile !== fileName && (
                    <div style={{ display: 'flex', gap: '8px', opacity: activeTab === fileName ? 1 : 0.3 }}>
                      <i className="fas fa-edit" onClick={(e) => startRename(fileName, e)} style={{ fontSize: '11px', color: '#8b949e', cursor: 'pointer' }} title="Rename"></i>
                      <i className="fas fa-trash" onClick={(e) => deleteFile(fileName, e)} style={{ fontSize: '11px', color: '#8b949e', cursor: 'pointer' }} title="Delete"></i>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 💻 MIDDLE PANE: Editor & Terminal */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          
          <div style={{ height: '45px', backgroundColor: '#0d1117', borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 15px' }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <div onClick={() => setShowExplorer(!showExplorer)} style={{ padding: '0 15px 0 0', cursor: 'pointer', color: showExplorer ? '#58a6ff' : '#8b949e', borderRight: '1px solid #30363d', marginRight: '10px' }}>
                <i className="fas fa-bars" style={{ fontSize: '15px' }}></i>
              </div>
              {Object.keys(files).map(fileName => (
                <div key={fileName} onClick={() => setActiveTab(fileName)} style={{ padding: '10px 20px', fontSize: '13px', cursor: 'pointer', backgroundColor: activeTab === fileName ? '#161b22' : 'transparent', borderTop: activeTab === fileName ? '2px solid #58a6ff' : '2px solid transparent', color: activeTab === fileName ? '#c9d1d9' : '#8b949e', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {getFileIcon(fileName)} {fileName}
                </div>
              ))}
            </div>
            <button onClick={runLivePreview} style={{ backgroundColor: '#238636', color: '#fff', border: 'none', padding: '6px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 'bold' }}>
               <i className="fas fa-external-link-alt" style={{ marginRight: '6px' }}></i> Run in New Tab
            </button>
          </div>

          <div style={{ flex: 1, backgroundColor: '#0d1117', position: 'relative' }}>
             <Editor height="100%" language={files[activeTab]?.language || 'plaintext'} theme="vs-dark" value={files[activeTab]?.value || ''} onChange={(val) => setFiles({ ...files, [activeTab]: { ...files[activeTab], value: val } })} options={{ minimap: { enabled: false }, fontSize: 14 }} />
          </div>
          
          {/* ✨ FIXED TERMINAL PANE ✨ */}
          {showTerminal && (
            <div style={{ height: isTerminalMinimized ? '35px' : '220px', transition: 'height 0.3s ease', backgroundColor: '#010409', borderTop: '1px solid #30363d', display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '8px 15px', fontSize: '11px', color: '#8b949e', borderBottom: '1px solid #30363d', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#161b22', userSelect: 'none' }}>
                <div style={{ display: 'flex', gap: '15px' }}>
                  <span style={{ borderBottom: isTerminalMinimized ? 'none' : '1px solid #58a6ff', color: '#c9d1d9', fontWeight: 'bold' }}>TERMINAL</span>
                  {!isTerminalMinimized && <span style={{ cursor: 'pointer' }}>OUTPUT</span>}
                </div>
                
                <div style={{ display: 'flex', gap: '15px', fontSize: '14px' }}>
                  <i className="fas fa-trash-alt" onClick={clearTerminal} style={{ cursor: 'pointer', color: '#c9d1d9' }} title="Clear Terminal"></i>
                  <i className={`fas ${isTerminalMinimized ? 'fa-chevron-up' : 'fa-chevron-down'}`} onClick={toggleTerminalSize} style={{ cursor: 'pointer', color: '#c9d1d9' }} title={isTerminalMinimized ? "Expand" : "Minimize"}></i>
                  <i className="fas fa-times" onClick={() => setShowTerminal(false)} style={{ cursor: 'pointer', color: '#c9d1d9' }} title="Close"></i>
                </div>
              </div>
              
              {/* CSS Hack: Height 0 instead of display:none preserves Canvas memory! */}
              <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
                 <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, opacity: isTerminalMinimized ? 0 : 1, pointerEvents: isTerminalMinimized ? 'none' : 'auto', transition: 'opacity 0.2s' }}>
                    <div ref={terminalRef} style={{ width: '100%', height: '100%', padding: '10px' }}></div>
                 </div>
              </div>
            </div>
          )}
        </div>

        {/* 🤖 RIGHT PANE: AI Chat Panel */}
        <div style={{ width: '320px', backgroundColor: '#010409', borderLeft: '1px solid #30363d', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '15px', borderBottom: '1px solid #30363d', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{ width: '30px', height: '30px', borderRadius: '50%', background: 'linear-gradient(45deg, #ff00cc, #3333ff)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 'bold' }}>S</div>
              <span style={{ fontSize: '14px', fontWeight: 'bold', color: '#c9d1d9' }}>Shanvika AI</span>
            </div>
            
            <select value={websiteTheme} onChange={(e) => setWebsiteTheme(e.target.value)} style={{ backgroundColor: '#161b22', color: '#8b949e', border: '1px solid #30363d', padding: '4px 8px', borderRadius: '4px', outline: 'none', fontSize: '11px', cursor: 'pointer' }}>
              <option>Auto Theme</option>
              <option>Professional</option>
              <option>Sci-Fi</option>
              <option>Fantasy</option>
              <option>Minimalist</option>
            </select>
          </div>

          <div style={{ flex: 1, padding: '15px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '15px' }}>
            {chatMessages.map((msg, idx) => (
              <div key={idx} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
                <div style={{ fontSize: '11px', color: '#8b949e', marginBottom: '4px', textAlign: msg.role === 'user' ? 'right' : 'left' }}>
                  {msg.role === 'user' ? 'Shantanu' : 'Shanvika'}
                </div>
                <div style={{ padding: '10px 14px', borderRadius: '8px', fontSize: '13px', lineHeight: '1.4', backgroundColor: msg.role === 'user' ? '#1f6feb' : '#161b22', color: '#c9d1d9', border: msg.role === 'ai' ? '1px solid #30363d' : 'none' }}>
                  {msg.text}
                </div>
              </div>
            ))}
            
            {aiWorkflowStatus && (
              <div style={{ alignSelf: 'flex-start', maxWidth: '85%' }}>
                <div style={{ padding: '8px 12px', borderRadius: '8px', fontSize: '12px', backgroundColor: 'rgba(88, 166, 255, 0.1)', color: '#58a6ff', border: '1px solid rgba(88, 166, 255, 0.2)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <i className="fas fa-circle-notch fa-spin"></i> {aiWorkflowStatus}
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          <div style={{ padding: '15px', borderTop: '1px solid #30363d', backgroundColor: '#0d1117' }}>
            <div style={{ position: 'relative' }}>
              <textarea value={aiInput} onChange={(e) => setAiInput(e.target.value)} onKeyDown={handleAISubmit} disabled={!!aiWorkflowStatus} placeholder="E.g., Make a portfolio website..." style={{ width: '100%', height: '80px', backgroundColor: '#010409', border: '1px solid #30363d', borderRadius: '8px', color: '#c9d1d9', padding: '10px', fontSize: '13px', resize: 'none', outline: 'none', opacity: aiWorkflowStatus ? 0.5 : 1 }} />
              <button onClick={() => handleAISubmit({ key: 'Enter' })} disabled={!!aiWorkflowStatus || !aiInput.trim()} style={{ position: 'absolute', bottom: '10px', right: '10px', background: 'transparent', border: 'none', color: '#58a6ff', cursor: 'pointer', fontSize: '16px', opacity: (aiWorkflowStatus || !aiInput.trim()) ? 0.5 : 1 }}>
                <i className="fas fa-paper-plane"></i>
              </button>
            </div>
          </div>
        </div>

      </div>

      {/* 🚀 VS CODE STYLE BOTTOM STATUS BAR */}
      <div style={{ height: '24px', backgroundColor: '#010409', borderTop: '1px solid #30363d', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 15px', fontSize: '11px', color: '#c9d1d9', zIndex: 10 }}>
        <div style={{ display: 'flex', gap: '20px', alignItems: 'center' }}>
          
          {/* ✨ Yahan Se Terminal Wapas Aayega ✨ */}
          <div onClick={reopenTerminal} style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', color: showTerminal ? '#58a6ff' : '#8b949e', transition: 'color 0.2s' }} title="Reopen Terminal">
            <i className="fas fa-terminal"></i> Terminal
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '5px', color: saveStatus.includes('Error') ? '#f85149' : '#3fb950' }}>
            <i className="fas fa-cloud"></i> {saveStatus}
          </div>
        </div>

        <div style={{ display: 'flex', gap: '15px', alignItems: 'center' }}>
          <select value={activeMode} onChange={(e) => setActiveMode(e.target.value)} style={{ background: 'transparent', border: 'none', color: '#8b949e', outline: 'none', fontSize: '11px', cursor: 'pointer' }}>
            <option>Copilot Mode</option>
            <option>God Mode (Auto)</option>
            <option>Debug Mode</option>
          </select>
          <div><i className="fas fa-code-branch" style={{ marginRight: '5px' }}></i> main</div>
          <div><i className="fas fa-check-double" style={{ marginRight: '5px', color: '#3fb950' }}></i> Ethrix Prettier</div>
        </div>
      </div>

    </div>
  );
}

export default App;