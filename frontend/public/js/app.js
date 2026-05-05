document.addEventListener('DOMContentLoaded', () => {
    const API_BASE = '/v1';
    
    // Auth Check
    const currentUser = JSON.parse(localStorage.getItem('currentUser') || 'null');
    const path = window.location.pathname;
    
    if (!currentUser && !path.endsWith('index.html') && path !== '/') {
        window.location.href = 'index.html';
        return;
    }
    
    if (currentUser && (path.endsWith('index.html') || path === '/')) {
        window.location.href = 'library.html';
        return;
    }

    // Common Logout
    const logoutBtn = document.getElementById('nav-logout');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('currentUser');
            localStorage.removeItem('chatSessionId');
            window.location.href = 'index.html';
        });
    }

    // --- Index Page (Login & Register) ---
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const toggleRegisterBtn = document.getElementById('toggle-register-btn');
    const authTitle = document.getElementById('auth-title');
    const authSubtitle = document.getElementById('auth-subtitle');

    if (toggleRegisterBtn) {
        toggleRegisterBtn.addEventListener('click', () => {
            if (loginForm.classList.contains('hidden')) {
                loginForm.classList.remove('hidden');
                registerForm.classList.add('hidden');
                toggleRegisterBtn.innerText = 'Need an account? Register here';
                authTitle.innerText = 'Welcome Back';
                authSubtitle.innerText = 'Please enter your username to continue';
            } else {
                loginForm.classList.add('hidden');
                registerForm.classList.remove('hidden');
                toggleRegisterBtn.innerText = 'Already have an account? Login here';
                authTitle.innerText = 'Create Account';
                authSubtitle.innerText = 'Register for the Course Learning Assistant';
            }
        });
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('username').value.trim();
            if (!username) return;

            try {
                const btn = loginForm.querySelector('button');
                const origText = btn.innerHTML;
                btn.innerHTML = 'Connecting...';
                btn.disabled = true;

                const res = await fetch(`/v1/users/user-profile/${username}`);
                if (!res.ok) {
                    if (res.status === 404) {
                        alert('User not found. Please register via the original backend first.');
                    } else {
                        alert('Error connecting to backend.');
                    }
                    btn.innerHTML = origText;
                    btn.disabled = false;
                    return;
                }
                const profile = await res.json();
                if (!profile || Object.keys(profile).length === 0) {
                    alert('User not found. Please check the ID or register a new account.');
                    btn.innerHTML = origText;
                    btn.disabled = false;
                    return;
                }
                localStorage.setItem('currentUser', JSON.stringify(profile));
                window.location.href = 'library.html';
            } catch (err) {
                alert('Network error. Is the backend running?');
            }
        });
    }

    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const username = document.getElementById('reg-username').value.trim();
            const name = document.getElementById('reg-name').value.trim();
            const courses = document.getElementById('reg-courses').value.split(',').map(c => c.trim()).filter(c => c);

            if (!username || !name) return;

            try {
                const btn = registerForm.querySelector('button');
                const origText = btn.innerHTML;
                btn.innerHTML = 'Creating...';
                btn.disabled = true;

                const payload = {
                    user_id: username,
                    name: name,
                    course_intake: courses,
                    interests: []
                };

                const res = await fetch(`/v1/users/user-profile`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!res.ok) {
                    alert('Error creating account.');
                    btn.innerHTML = origText;
                    btn.disabled = false;
                    return;
                }
                
                const profile = await res.json();
                localStorage.setItem('currentUser', JSON.stringify(profile));
                window.location.href = 'library.html';
            } catch (err) {
                alert('Network error. Is the backend running?');
            }
        });
    }

    // --- Library Page ---
    const reportsContainer = document.getElementById('reports-container');
    if (reportsContainer) {
        const loadReports = async () => {
            reportsContainer.innerHTML = '<p class="text-slate-500">Loading reports...</p>';
            try {
                const res = await fetch(`/v1/reports`);
                if (!res.ok) throw new Error('Failed to load reports');
                const reports = await res.json();
                
                if (reports.length === 0) {
                    reportsContainer.innerHTML = '<p class="text-slate-500">No reports found. Ingest a video above!</p>';
                    return;
                }

                // Group by course
                const grouped = reports.reduce((acc, report) => {
                    const course = report.course || 'Summaries';
                    if (!acc[course]) acc[course] = [];
                    acc[course].push(report);
                    return acc;
                }, {});

                reportsContainer.innerHTML = '';
                
                for (const [course, courseReports] of Object.entries(grouped)) {
                    // Create course header
                    const header = document.createElement('h2');
                    header.className = "font-headline-md text-title-lg text-primary mb-4 mt-8 first:mt-0";
                    header.innerText = course;
                    reportsContainer.appendChild(header);

                    courseReports.forEach((report, index) => {
                        const numDisplay = report.lecture_number ? `Lecture ${report.lecture_number}: ` : '';
                        
                        const card = document.createElement('article');
                        card.className = "group bg-surface-container-lowest rounded-xl p-8 border border-slate-200/60 shadow-[0_4px_12px_rgba(78,96,117,0.04)] hover:shadow-[0_8px_24px_rgba(78,96,117,0.08)] transition-all duration-300 mb-4";
                        card.innerHTML = `
                        <div class="flex flex-col md:flex-row md:items-center justify-between gap-8">
                            <div class="flex-1">
                                <div class="flex items-center gap-4 mb-3">
                                    <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center text-blue-500 font-bold text-lg">
                                        <span class="material-symbols-outlined">menu_book</span>
                                    </div>
                                    <h3 class="font-headline-sm text-headline-sm text-slate-800">${numDisplay}${report.lecture_title}</h3>
                                </div>
                                <p class="text-slate-500 font-body-md mb-6 leading-relaxed">
                                    Generated summary document for ${course}.
                                </p>
                                <div class="flex items-center gap-6">
                                    <div class="flex items-center gap-2 text-slate-400">
                                        <span class="material-symbols-outlined text-sm">description</span>
                                        <span class="text-caption font-caption">HTML</span>
                                    </div>
                                </div>
                            </div>
                            <div class="flex items-center gap-3 shrink-0">
                                <a href="/${report.file_path}" target="_blank" class="px-6 py-2.5 rounded-lg border border-primary text-primary font-label-md hover:bg-primary-container/10 transition-colors cursor-pointer inline-block text-center">
                                    View Full Report
                                </a>
                            </div>
                        </div>
                        `;
                        reportsContainer.appendChild(card);
                    });
                }
            } catch (err) {
                reportsContainer.innerHTML = `<p class="text-error">Error loading reports: ${err.message}</p>`;
            }
        };

        loadReports();

        // Ingestion Form
        const ingestForm = document.getElementById('ingest-form');
        const ingestStatus = document.getElementById('ingest-status');
        if (ingestForm) {
            ingestForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const videoLink = document.getElementById('ingest-video-link').value;
                const courseName = document.getElementById('ingest-course-name').value;
                const lectureLabel = document.getElementById('ingest-lecture-label').value;

                const btn = document.getElementById('ingest-button');
                btn.disabled = true;
                btn.innerText = 'Triggering...';
                ingestStatus.innerText = 'Triggering pipeline...';

                try {
                    const res = await fetch(`/v1/reports/ingest`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            video_link: videoLink,
                            course_name: courseName,
                            week_or_lecture: lectureLabel
                        })
                    });
                    
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.detail || 'Ingest failed');
                    
                    ingestStatus.innerHTML = `<span class="text-green-600">Started DAG run for video <b>${data.video_id}</b>. Refresh this page later to see the report!</span>`;
                } catch (err) {
                    ingestStatus.innerHTML = `<span class="text-error">Error: ${err.message}</span>`;
                } finally {
                    btn.disabled = false;
                    btn.innerText = 'Ingest';
                }
            });
        }
    }

    // --- Chatbot Page ---
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendButton = document.getElementById('send-button');
    const streamToggle = document.getElementById('stream-toggle');
    const streamLabel = document.getElementById('stream-label');

    if (chatMessages && chatInput && sendButton) {
        
        if (streamToggle && streamLabel) {
            streamToggle.addEventListener('change', (e) => {
                streamLabel.innerText = e.target.checked ? 'STREAMING' : 'NON-STREAMING';
            });
        }

        // Auto-scroll to bottom
        const scrollToBottom = () => {
            chatMessages.scrollTop = chatMessages.scrollHeight;
        };

        const renderUserMessage = (text) => {
            const div = document.createElement('div');
            div.className = "flex justify-end items-start gap-4";
            div.innerHTML = `
                <div class="max-w-[70%] space-y-1">
                    <div class="bg-[#4e6075] text-white px-5 py-4 rounded-2xl rounded-tr-sm shadow-lg text-body-md whitespace-pre-wrap">${text}</div>
                    <div class="text-[11px] text-slate-400 text-right pr-1">Just now</div>
                </div>
                <div class="w-8 h-8 rounded-full overflow-hidden shrink-0 border border-slate-200 bg-primary-container flex items-center justify-center text-on-primary-container font-bold">
                    ${currentUser.user_id.charAt(0).toUpperCase()}
                </div>
            `;
            chatMessages.appendChild(div);
            scrollToBottom();
        };

        const createBotMessageContainer = () => {
            const div = document.createElement('div');
            div.className = "flex justify-start items-start gap-4";
            div.innerHTML = `
                <div class="w-10 h-10 rounded-2xl bg-primary-container flex items-center justify-center shrink-0 shadow-sm">
                    <span class="material-symbols-outlined text-on-primary-container" style="font-variation-settings: 'FILL' 1;">smart_toy</span>
                </div>
                <div class="max-w-[80%] space-y-3 w-full">
                    <div class="bg-white border border-slate-200/60 px-6 py-5 rounded-2xl rounded-tl-sm shadow-sm text-body-md text-slate-700 leading-relaxed whitespace-pre-wrap ai-content"></div>
                    <div class="text-[11px] text-slate-400 pl-1 ai-meta"></div>
                </div>
            `;
            chatMessages.appendChild(div);
            scrollToBottom();
            return div;
        };

        const handleSend = async () => {
            const text = chatInput.value.trim();
            if (!text) return;

            chatInput.value = '';
            renderUserMessage(text);
            
            // Get or create session ID
            let sessionId = localStorage.getItem('chatSessionId');
            if (!sessionId) {
                sessionId = 'sesh-' + Math.random().toString(36).substr(2, 9);
                localStorage.setItem('chatSessionId', sessionId);
            }

            const isStreaming = streamToggle ? streamToggle.checked : true;
            const endpoint = isStreaming ? `${API_BASE}/agents/personalized-learning/stream` : `${API_BASE}/agents/personalized-learning`;

            const payload = {
                user_input: text,
                session_id: sessionId,
                user_id: currentUser.user_id
            };

            const botContainer = createBotMessageContainer();
            const contentDiv = botContainer.querySelector('.ai-content');
            const metaDiv = botContainer.querySelector('.ai-meta');
            
            contentDiv.innerHTML = '<span class="animate-pulse">Thinking...</span>';

            try {
                if (!isStreaming) {
                    const res = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    if (!res.ok) throw new Error('API Error');
                    const data = await res.json();
                    contentDiv.textContent = data.response || '(No response)';
                    if (data.use_rag) metaDiv.textContent = `use_rag: ${data.use_rag}`;
                    scrollToBottom();
                } else {
                    const res = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });

                    if (!res.ok) throw new Error('API Error');

                    contentDiv.textContent = '';
                    const reader = res.body.getReader();
                    const decoder = new TextDecoder('utf-8');
                    let done = false;
                    let buffer = '';

                    while (!done) {
                        const { value, done: doneReading } = await reader.read();
                        done = doneReading;
                        if (value) {
                            buffer += decoder.decode(value, { stream: true });
                            let lines = buffer.split('\n');
                            buffer = lines.pop(); // keep the last incomplete line
                            
                            for (let line of lines) {
                                if (line.startsWith('data: ')) {
                                    const dataStr = line.substring(6);
                                    if (dataStr === '[DONE]') {
                                        break;
                                    }
                                    try {
                                        const event = JSON.parse(dataStr);
                                        if (event.type === 'token' && event.content) {
                                            contentDiv.textContent += event.content;
                                            scrollToBottom();
                                        } else if (event.type === 'final') {
                                            if (event.response) {
                                                contentDiv.textContent = event.response;
                                            }
                                            if (event.from_cache) {
                                                metaDiv.textContent = 'Served from cache';
                                            } else if (event.use_rag !== undefined) {
                                                metaDiv.textContent = `use_rag: ${event.use_rag}`;
                                            }
                                            scrollToBottom();
                                        } else if (event.type === 'rollback') {
                                            contentDiv.textContent = '';
                                            metaDiv.textContent = 'Retrieval answer replaced after groundedness check';
                                        } else if (event.type === 'error') {
                                            contentDiv.textContent += '\n[Error: ' + event.message + ']';
                                        }
                                    } catch (e) {}
                                }
                            }
                        }
                    }
                }
            } catch (err) {
                contentDiv.textContent = `Error: ${err.message}`;
            }
        };

        sendButton.addEventListener('click', handleSend);
        chatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        });
    }
});
