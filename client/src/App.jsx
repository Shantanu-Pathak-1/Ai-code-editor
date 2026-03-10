import React, { useState, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { api } from './apiService';

function App() {
  const [files, setFiles] = useState({
    'index.html': { name: 'index.html', language: 'html', value: '\n<h1>Hello Shantanu ✨</h1>' },
    'style.css': { name: 'style.css', language: 'css', value: '/* Type your CSS here */\nbody {\n  background-color: #1e1e1e;\n  color: white;\n  font-family: sans-serif;\n}' },
    'index.js': { name: 'index.js', language: 'javascript', value: '// Type your JS here\nconsole.log("Ethrix Cloud Terminal Active!");' }
  });
  
  const [activeTab, setActiveTab] = useState('index.html'); 
  const [previewContent, setPreviewContent] = useState('');
  const [activeProvider, setActiveProvider] = useState('gemini');
  const [saveStatus, setSaveStatus] = useState('☁️ Cloud Sync On');
  
  const filesRef = useRef(files); 
  const terminalRef = useRef(null);
  const xtermInstance = useRef(null);

  // Sync state to Ref for Auto-Save
  useEffect(() => { filesRef.current = files; }, [files]);

  // ☁️ MongoDB Auto-Save Logic (Background)
  useEffect(() => {
    const autoSaveTimer = setInterval(async () => {
      try {
        setSaveStatus('🔄 Auto-saving...');
        await api.saveWorkspace("Ethrix_Workspace_1", filesRef.current);
        setSaveStatus('✅ Synced to DB');
        setTimeout(() => setSaveStatus('☁️ Cloud Sync On'), 2000);
      } catch (err) {
        setSaveStatus('❌ Sync Error');
      }
    }, 10000); 
    return () => clearInterval(autoSaveTimer);
  }, []);

  // 🚀 RAM-Friendly Smart Live Previewer
  const runLivePreview = () => {
    const currentFiles = filesRef.current;
    const htmlCode = currentFiles['index.html'] ? currentFiles['index.html'].value : '';
    const cssCode = currentFiles['style.css'] ? currentFiles['style.css'].value : '';
    const jsCode = currentFiles['index.js'] ? currentFiles['index.js'].value : '';

    const combinedCode = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <style>${cssCode}</style>
      </head>
      <body>
        ${htmlCode}
        <script>${jsCode}<\/script>
      </body>
      </html>
    `;
    setPreviewContent(combinedCode);
    setActiveTab('preview'); 
  };

  // ⌨️ KEYBOARD SHORTCUTS (Ctrl+Enter to Run, Ctrl+S to Save)
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.ctrlKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        setSaveStatus('🔄 Manual Saving...');
        api.saveWorkspace("Ethrix_Workspace_1", filesRef.current)
          .then(() => { setSaveStatus('✅ Saved'); setTimeout(() => setSaveStatus('☁️ Cloud Sync On'), 2000); })
          .catch(() => setSaveStatus('❌ Save Failed'));
      }
      if (e.ctrlKey && e.key === 'Enter') {
        e.preventDefault();
        runLivePreview();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 🖥️ VS CODE REAL TERMINAL (Xterm.js via Cloud)
  useEffect(() => {
    if (!terminalRef.current || xtermInstance.current || !window.Terminal) return;

    // Initialize Terminal
    const term = new window.Terminal({
      theme: { background: '#1e1e1e', foreground: '#4af626', cursor: '#ffffff' },
      fontFamily: 'monospace',
      cursorBlink: true,
      fontSize: 13
    });
    
    // Auto-fit to container
    const fitAddon = new window.FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalRef.current);
    fitAddon.fit();
    xtermInstance.current = term;

    // Terminal Boot Sequence
    term.writeln('\x1b[1;36m🤖 Ethrix-Forge Cloud Terminal Initialized!\x1b[0m');
    term.writeln('Type \x1b[33m"help"\x1b[0m for commands or ask AI to write code.\r\n');
    term.write('\x1b[1;32m$\x1b[0m ');

    let inputBuffer = '';

    term.onData(async (key) => {
      // Enter Key Pressed
      if (key === '\r') {
        term.writeln('');
        const command = inputBuffer.trim();
        inputBuffer = '';

        if (command === '') {
          term.write('\x1b[1;32m$\x1b[0m ');
          return;
        }

        if (command.toLowerCase() === 'clear') {
          term.clear();
          term.write('\x1b[1;32m$\x1b[0m ');
          return;
        }

        if (command.toLowerCase() === 'help') {
          term.writeln('  \x1b[36mCtrl + S\x1b[0m      : Cloud Save');
          term.writeln('  \x1b[36mCtrl + Enter\x1b[0m  : Live Preview');
          term.writeln('  \x1b[36mclear\x1b[0m         : Clear Terminal');
          term.writeln('\x1b[33mOr type any prompt to generate code!\x1b[0m');
          term.write('\x1b[1;32m$\x1b[0m ');
          return;
        }

        // Call AI Backend
        term.writeln(`\x1b[35m⏳ Processing via Cloud Gateway...\x1b[0m`);
        try {
          // Note: using your default provider state here
          const generatedFiles = await api.generateCode(command, "gemini");
          if (generatedFiles && generatedFiles.length > 0) {
            const updatedFiles = { ...filesRef.current };
            generatedFiles.forEach(f => {
              updatedFiles[f.filename] = { name: f.filename, language: f.language, value: f.code };
            });
            setFiles(updatedFiles);
            term.writeln('\x1b[32m✅ Code Injected! Press Ctrl+Enter to Preview.\x1b[0m');
          }
        } catch (err) {
          term.writeln(`\x1b[31m❌ Error: ${err.message}\x1b[0m`);
        }
        term.write('\r\n\x1b[1;32m$\x1b[0m ');
      } 
      // Backspace Key Pressed
      else if (key === '\x7F') {
        if (inputBuffer.length > 0) {
          inputBuffer = inputBuffer.slice(0, -1);
          term.write('\b \b');
        }
      } 
      // Normal Typing
      else {
        inputBuffer += key;
        term.write(key);
      }
    });

    // Handle Resize
    const resizeObserver = new ResizeObserver(() => fitAddon.fit());
    resizeObserver.observe(terminalRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  const handleEditorChange = (value) => {
    if (activeTab !== 'preview') {
      setFiles({ ...files, [activeTab]: { ...files[activeTab], value } });
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#1e1e1e', color: '#ccc', fontFamily: 'sans-serif' }}>
      
      {/* 📁 Sidebar */}
      <div style={{ width: '250px', backgroundColor: '#252526', borderRight: '1px solid #333', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '15px', fontSize: '12px', fontWeight: 'bold', color: '#858585' }}>EXPLORER</div>
        {Object.keys(files).map((fileName) => (
          <div 
            key={fileName} onClick={() => setActiveTab(fileName)}
            style={{ 
              padding: '8px 20px', cursor: 'pointer',
              backgroundColor: activeTab === fileName ? '#37373d' : 'transparent',
              borderLeft: activeTab === fileName ? '2px solid #007acc' : '2px solid transparent',
              color: activeTab === fileName ? '#fff' : '#cccccc'
            }}
          >
            📄 {fileName}
          </div>
        ))}
      </div>

      {/* 💻 Main Editor Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        
        {/* 🛠️ Top Control Bar & Tabs */}
        <div style={{ backgroundColor: '#2d2d2d', display: 'flex', flexDirection: 'column' }}>
          
          {/* Action Tools */}
          <div style={{ height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 15px', borderBottom: '1px solid #1e1e1e' }}>
            <div style={{ fontSize: '13px', fontWeight: 'bold', color: saveStatus.includes('Auto-saving') ? '#4daafc' : (saveStatus.includes('Synced') ? '#4af626' : '#858585') }}>
              {saveStatus}
            </div>
            
            <div style={{ display: 'flex', gap: '10px' }}>
              <select value={activeProvider} onChange={(e) => setActiveProvider(e.target.value)} style={{ backgroundColor: '#1e1e1e', color: 'white', border: '1px solid #444', padding: '4px 8px', borderRadius: '4px' }}>
                <option value="gemini">🤖 Gemini</option>
                <option value="groq">⚡ Groq</option>
              </select>
              <button onClick={runLivePreview} style={{ backgroundColor: '#007acc', color: '#fff', border: 'none', padding: '4px 15px', borderRadius: '4px', cursor: 'pointer', fontWeight: 'bold' }}>🚀 Run (Ctrl+Enter)</button>
            </div>
          </div>

          {/* File Tabs */}
          <div style={{ display: 'flex', backgroundColor: '#252526', overflowX: 'auto' }}>
            {Object.keys(files).map(fileName => (
              <div 
                key={fileName} onClick={() => setActiveTab(fileName)}
                style={{
                  padding: '8px 20px', fontSize: '14px', cursor: 'pointer', borderRight: '1px solid #333',
                  backgroundColor: activeTab === fileName ? '#1e1e1e' : 'transparent',
                  color: activeTab === fileName ? '#fff' : '#858585',
                  borderTop: activeTab === fileName ? '2px solid #007acc' : '2px solid transparent'
                }}
              >
                {fileName}
              </div>
            ))}
            {/* The Dedicated Preview Tab */}
            <div 
              onClick={() => setActiveTab('preview')}
              style={{
                padding: '8px 20px', fontSize: '14px', cursor: 'pointer', borderRight: '1px solid #333',
                backgroundColor: activeTab === 'preview' ? '#ffffff' : '#252526',
                color: activeTab === 'preview' ? '#000000' : '#4daafc',
                borderTop: activeTab === 'preview' ? '2px solid #4caf50' : '2px solid transparent',
                fontWeight: 'bold'
              }}
            >
              👁️ Live Preview
            </div>
          </div>
        </div>

        {/* Editor OR Preview Pane */}
        <div style={{ flex: 1, position: 'relative', backgroundColor: activeTab === 'preview' ? '#fff' : '#1e1e1e' }}>
          {activeTab === 'preview' ? (
            <iframe title="Preview" srcDoc={previewContent} style={{ width: '100%', height: '100%', border: 'none' }} />
          ) : (
            <Editor height="100%" language={files[activeTab]?.language || 'plaintext'} theme="vs-dark" value={files[activeTab]?.value || ''} onChange={handleEditorChange} options={{ minimap: { enabled: false } }} />
          )}
        </div>
        
        {/* Real VS Code Terminal Container */}
        <div style={{ height: '250px', backgroundColor: '#1e1e1e', borderTop: '1px solid #333', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '5px 15px', fontSize: '11px', color: '#858585', borderBottom: '1px solid #333', textTransform: 'uppercase', letterSpacing: '1px' }}>TERMINAL</div>
          {/* Ye div hai jiske andar Xterm.js apna jadoo chalayega */}
          <div ref={terminalRef} style={{ flex: 1, padding: '10px 15px', overflow: 'hidden' }}></div>
        </div>

      </div>
    </div>
  );
}

export default App;