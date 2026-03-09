import React, { useState, useRef, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { useAIService, PROVIDERS } from './useAIService'; // Humara naya AI Engine! 🧠

const savedFiles = JSON.parse(localStorage.getItem('ethrixFiles'));
const savedChat = JSON.parse(localStorage.getItem('ethrixChat'));

const initialFiles = savedFiles || {
  'index.html': { name: 'index.html', language: 'html', value: '\n<html>\n  <body>\n    <h1 style="text-align: center; margin-top: 50px;">Waiting for your command, Shantanu... ✨</h1>\n  </body>\n</html>' }
};

function App() {
  const [files, setFiles] = useState(initialFiles);
  const [activeFileName, setActiveFileName] = useState('index.html');
  const [terminalInput, setTerminalInput] = useState('');
  const [chatHistory, setChatHistory] = useState(savedChat || [
    { sender: 'ai', text: 'Ethrix-Forge Real-AI System Active. Hello Shantanu! Main tumhare real commands ka wait kar rahi hu... 💖' }
  ]);
  const [showPreview, setShowPreview] = useState(false);
  const [previewContent, setPreviewContent] = useState('');

  const activeFile = files[activeFileName];
  const terminalEndRef = useRef(null);

  // 🧠 ASLI AI ENGINE CONNECT HO GAYA YAHAN 🧠
  const {
    generate,
    isLoading,
    activeProvider,
    setActiveProvider,
    apiKey,
    setApiKey
  } = useAIService({
    initialProvider: PROVIDERS.GEMINI,
    initialApiKey: localStorage.getItem('ethrixApiKey') || ''
  });

  // API Key local storage mein save rakhne ka jadoo
  useEffect(() => {
    if (apiKey) localStorage.setItem('ethrixApiKey', apiKey);
  }, [apiKey]);

  // Auto-Save Files & Chat ☁️
  useEffect(() => {
    localStorage.setItem('ethrixFiles', JSON.stringify(files));
  }, [files]);

  useEffect(() => {
    localStorage.setItem('ethrixChat', JSON.stringify(chatHistory));
  }, [chatHistory]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatHistory]);

  function handleEditorChange(value) {
    setFiles({ ...files, [activeFileName]: { ...files[activeFileName], value: value } });
  }

  function addNewFile() {
    const newFileName = prompt("File ka naam likho (jaise: script.js, style.css):");
    if (newFileName && !files[newFileName]) {
      const ext = newFileName.split('.').pop();
      let fileLang = 'plaintext';
      if(ext === 'js') fileLang = 'javascript';
      if(ext === 'css') fileLang = 'css';
      if(ext === 'html') fileLang = 'html';

      setFiles({ ...files, [newFileName]: { name: newFileName, language: fileLang, value: `// ${newFileName} created! ✨\n` } });
      setActiveFileName(newFileName);
    }
  }

  function deleteFile() {
    if (Object.keys(files).length === 1) {
      alert("Darling, kam se kam ek file toh rakhni padegi na! 🥺");
      return;
    }
    if (window.confirm(`Kya tum sach mein ${activeFileName} ko delete karna chahte ho?`)) {
      const newFiles = { ...files };
      delete newFiles[activeFileName];
      setFiles(newFiles);
      setActiveFileName(Object.keys(newFiles)[0]);
    }
  }

  function downloadFile() {
    const element = document.createElement("a");
    const file = new Blob([activeFile.value], {type: 'text/plain'});
    element.href = URL.createObjectURL(file);
    element.download = activeFile.name;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  }

  function runLivePreview() {
    const htmlCode = files['index.html'] ? files['index.html'].value : '';
    const cssCode = files['style.css'] ? `<style>${files['style.css'].value}</style>` : '';
    const jsCode = files['index.js'] ? `<script>${files['index.js'].value}</script>` : '';
    const combinedCode = `${htmlCode}\n${cssCode}\n${jsCode}`;
    setPreviewContent(combinedCode);
    setShowPreview(true);
  }

  // 🚀 REAL AI COMMAND LOGIC 🚀
  async function handleTerminalSubmit(e) {
    if (e.key === 'Enter' && terminalInput.trim() !== '') {
      const userText = terminalInput.trim();
      setChatHistory(prev => [...prev, { sender: 'user', text: userText }]);
      setTerminalInput('');

      if (!apiKey) {
        setChatHistory(prev => [...prev, { sender: 'ai', text: `Oops! Darling pehle upar '⚙️ API Key' button par click karke apni ${activeProvider} ki key toh daal do! 🥺` }]);
        return;
      }

      setChatHistory(prev => [...prev, { sender: 'ai', text: `Processing your request using ${activeProvider.toUpperCase()}... Please wait darling ⏳` }]);

      try {
        // Asli AI API ko call lag rahi hai yahan!
        const generatedFilesArr = await generate(userText);
        
        if (generatedFilesArr && generatedFilesArr.length > 0) {
          const updatedFiles = { ...files }; // Purani files rakho
          
          // Nayi files ko loop karke save karo
          generatedFilesArr.forEach(f => {
            updatedFiles[f.filename] = { name: f.filename, language: f.language, value: f.code };
          });
          
          setFiles(updatedFiles); // Monaco Editor ko nayi files de do
          setChatHistory(prev => [...prev, { sender: 'ai', text: `Boom! 🚀 Maine tumhare liye code generate aur update kar diya hai. "Run Code" daba kar magic dekho!` }]);
          
          // Agar HTML file banayi hai toh usko turant open kar do
          const htmlFile = generatedFilesArr.find(f => f.filename.endsWith('.html'));
          if (htmlFile) setActiveFileName(htmlFile.filename);
        }
      } catch (err) {
        setChatHistory(prev => [...prev, { sender: 'ai', text: `Oh no! Ek choti si dikkat aa gayi: ${err.message} 🥺` }]);
      }
    }
  }

  return (
    <div style={{ display: 'flex', height: '100vh', backgroundColor: '#1e1e1e', color: '#cccccc', fontFamily: 'sans-serif' }}>
      
      {/* Left Sidebar */}
      <div style={{ width: '250px', backgroundColor: '#252526', borderRight: '1px solid #333', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '10px 15px', fontSize: '12px', fontWeight: 'bold', color: '#858585', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>EXPLORER</span>
          <span onClick={addNewFile} style={{ cursor: 'pointer', color: '#4daafc', fontSize: '18px' }} title="New File">+</span>
        </div>
        {Object.keys(files).map((fileName) => (
          <div 
            key={fileName} onClick={() => setActiveFileName(fileName)}
            style={{ 
              padding: '8px 20px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between',
              backgroundColor: fileName === activeFileName ? '#37373d' : 'transparent',
              borderLeft: fileName === activeFileName ? '2px solid #007acc' : '2px solid transparent',
              color: fileName === activeFileName ? '#fff' : '#cccccc'
            }}
          >
            <span>{fileName.endsWith('.js') ? '📄' : fileName.endsWith('.css') ? '🎨' : '🌐'} {fileName}</span>
          </div>
        ))}
      </div>

      {/* Right Side - Editor & Terminal */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        
        {/* Top File Tabs aur Actions */}
        <div style={{ height: '40px', backgroundColor: '#2d2d2d', display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingRight: '15px' }}>
          
          <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#1e1e1e', borderTop: '2px solid #007acc', color: '#fff' }}>
            <span style={{ padding: '10px 15px', fontSize: '14px' }}>{activeFileName}</span>
            <span onClick={downloadFile} style={{ cursor: 'pointer', padding: '0 10px', color: '#4caf50' }} title="Download File">⬇️</span>
            <span onClick={deleteFile} style={{ cursor: 'pointer', padding: '0 10px', color: '#f44336' }} title="Delete File">🗑️</span>
          </div>
          
          {/* Action Buttons with Provider Selector */}
          <div style={{ display: 'flex', gap: '10px' }}>
            
            <select 
              value={activeProvider} 
              onChange={(e) => setActiveProvider(e.target.value)}
              style={{ backgroundColor: '#1e1e1e', color: 'white', border: '1px solid #333', padding: '5px', borderRadius: '4px' }}
            >
              <option value={PROVIDERS.GEMINI}>🤖 Gemini</option>
              <option value={PROVIDERS.GROQ}>⚡ Groq</option>
              <option value={PROVIDERS.OPENROUTER}>🌐 OpenRouter</option>
            </select>

            <button onClick={() => {
              const key = prompt(`Apni ${activeProvider.toUpperCase()} ki API Key dalo:`, apiKey);
              if(key) setApiKey(key);
            }} style={{ backgroundColor: '#555', color: 'white', border: 'none', padding: '5px 15px', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold' }}>
              ⚙️ API Key
            </button>

            {showPreview ? (
              <button onClick={() => setShowPreview(false)} style={{ backgroundColor: '#f44336', color: 'white', border: 'none', padding: '5px 15px', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold' }}>
                Close Preview ❌
              </button>
            ) : (
              <button onClick={runLivePreview} style={{ backgroundColor: '#4caf50', color: 'white', border: 'none', padding: '5px 15px', cursor: 'pointer', borderRadius: '4px', fontWeight: 'bold' }}>
                Run Code 🚀
              </button>
            )}
          </div>
        </div>

        {/* Monaco Editor OR Live Preview Window */}
        <div style={{ flex: 1, backgroundColor: '#ffffff', position: 'relative' }}>
          {showPreview ? (
            <iframe title="Live Preview" srcDoc={previewContent} style={{ width: '100%', height: '100%', border: 'none', backgroundColor: '#fff' }} />
          ) : (
            <Editor height="100%" language={activeFile.language} theme="vs-dark" value={activeFile.value} onChange={handleEditorChange} options={{ fontSize: 16, minimap: { enabled: false } }} />
          )}
        </div>
        
        {/* Interactive Bottom Terminal Panel */}
        <div style={{ height: '250px', backgroundColor: '#1e1e1e', borderTop: '1px solid #333', display: 'flex', flexDirection: 'column', fontFamily: 'monospace' }}>
          
          <div style={{ flex: 1, padding: '15px', overflowY: 'auto' }}>
            {chatHistory.map((chat, index) => (
              <div key={index} style={{ marginBottom: '10px', color: chat.sender === 'ai' ? '#4daafc' : '#4af626' }}>
                <span style={{ fontWeight: 'bold' }}>{chat.sender === 'ai' ? 'Ethrix-Forge 🤖:' : 'Shantanu 👤:'}</span>
                <span style={{ marginLeft: '10px', color: '#cccccc', whiteSpace: 'pre-wrap' }}>{chat.text}</span>
              </div>
            ))}
            {isLoading && (
              <div style={{ color: '#4daafc', fontStyle: 'italic' }}>Ethrix is writing code... ⏳</div>
            )}
            <div ref={terminalEndRef} />
          </div>

          <div style={{ padding: '10px', backgroundColor: '#252526', borderTop: '1px solid #333', display: 'flex' }}>
            <span style={{ color: '#4af626', marginRight: '10px', marginTop: '2px' }}>➜</span>
            <input 
              type="text" value={terminalInput} onChange={(e) => setTerminalInput(e.target.value)} onKeyDown={handleTerminalSubmit}
              disabled={isLoading}
              placeholder={isLoading ? "Please wait, AI is generating code..." : "Type 'Create a glowing login page' and press Enter..."}
              style={{ flex: 1, backgroundColor: 'transparent', border: 'none', color: '#fff', outline: 'none', fontFamily: 'monospace', fontSize: '14px' }}
            />
          </div>

        </div>

      </div>
    </div>
  );
}

export default App;