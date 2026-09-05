/**
 * HolmesGPT Web GUI Application Logic
 * Interactive Chat & Telemetry Investigation
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const messagesContainer = document.getElementById('messages-container');
  const emptyState = document.getElementById('empty-state');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const clearChatBtn = document.getElementById('clear-chat-btn');
  const toggleSidebarBtn = document.getElementById('toggle-sidebar-btn');
  const appSidebar = document.getElementById('app-sidebar');
  const systemStatus = document.getElementById('system-status');
  const statusText = document.getElementById('status-text');
  const modelBadge = document.getElementById('model-badge');
  const modelName = document.getElementById('model-name');
  const versionTag = document.getElementById('version-tag');
  const toolsetCount = document.getElementById('toolset-count');

  // State
  let conversationHistory = [];
  let isSubmitting = false;

  // Load history from localStorage
  const savedHistory = localStorage.getItem('holmes_chat_history');
  if (savedHistory) {
    try {
      const parsed = JSON.parse(savedHistory);
      if (Array.isArray(parsed) && parsed.length > 0) {
        conversationHistory = parsed;
        renderHistory();
      }
    } catch (e) {
      console.warn('Failed to parse saved chat history:', e);
    }
  }

  // Auto-resize input textarea
  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
    sendBtn.disabled = chatInput.value.trim() === '';
  });

  // Handle Enter to submit (Shift+Enter for newline)
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (!isSubmitting && chatInput.value.trim()) {
        chatForm.dispatchEvent(new Event('submit'));
      }
    }
  });

  // Toggle Sidebar
  toggleSidebarBtn.addEventListener('click', () => {
    appSidebar.classList.toggle('collapsed');
  });

  // Clear Chat History
  clearChatBtn.addEventListener('click', () => {
    if (confirm('Clear the conversation history and start fresh?')) {
      conversationHistory = [];
      localStorage.removeItem('holmes_chat_history');
      messagesContainer.innerHTML = '';
      messagesContainer.appendChild(emptyState);
      emptyState.style.display = 'flex';
      chatInput.focus();
    }
  });

  // Quick Prompt Chips & Starter Cards Click
  document.querySelectorAll('[data-prompt]').forEach((el) => {
    el.addEventListener('click', () => {
      const prompt = el.getAttribute('data-prompt');
      if (prompt && !isSubmitting) {
        chatInput.value = prompt;
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
        sendBtn.disabled = false;
        chatForm.dispatchEvent(new Event('submit'));
      }
    });
  });

  // Form Submit (Send Message)
  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query || isSubmitting) return;

    // Reset input
    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendBtn.disabled = true;
    isSubmitting = true;

    // Hide empty state
    if (emptyState.style.display !== 'none') {
      emptyState.style.display = 'none';
    }

    // Add User Message to UI
    appendUserMessage(query);

    // Add Thinking / Typing indicator
    const typingIndicator = appendTypingIndicator();

    try {
      // Call Holmes API via reverse proxy
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ask: query,
          conversation_history: conversationHistory
        })
      });

      // Remove typing indicator
      typingIndicator.remove();

      if (!response.ok) {
        const errText = await response.text();
        appendBotMessage(
          `⚠️ **Holmes API Error (${response.status})**\n\n\`\`\`\n${errText || response.statusText}\n\`\`\`\n*Ensure an LLM API key (OPENAI_API_KEY) is configured in the secret \`holmes-secrets\`.*`,
          []
        );
        return;
      }

      const data = await response.json();
      const analysis = data.analysis || 'Investigation completed without output.';
      const toolCalls = data.tool_calls || [];

      // Add to conversation history
      conversationHistory.push({ role: 'user', content: query });
      conversationHistory.push({ role: 'assistant', content: analysis });
      saveHistory();

      // Render Bot Message
      appendBotMessage(analysis, toolCalls);

    } catch (err) {
      typingIndicator.remove();
      appendBotMessage(
        `🚨 **Connection Error**\n\nFailed to reach Holmes API at \`/api/chat\`.\n\`\`\`\n${err.message}\n\`\`\`\n*Please verify that the Holmes backend pod is running.*`,
        []
      );
    } finally {
      isSubmitting = false;
      chatInput.focus();
    }
  });

  // Helper: Append User Message
  function appendUserMessage(text) {
    const row = document.createElement('div');
    row.className = 'message-row user';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;

    const meta = document.createElement('div');
    meta.className = 'message-meta';
    meta.textContent = formatTime(new Date());
    bubble.appendChild(meta);

    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    scrollToBottom();
  }

  // Helper: Append Bot Message
  function appendBotMessage(markdownText, toolCalls = []) {
    const row = document.createElement('div');
    row.className = 'message-row bot';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg>`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    // Tool calls drawer if tools were invoked
    if (toolCalls && toolCalls.length > 0) {
      const toolContainer = document.createElement('div');
      toolContainer.className = 'tool-calls-container';

      toolCalls.forEach((tc, idx) => {
        const item = document.createElement('div');
        item.className = 'tool-call-item';

        const header = document.createElement('div');
        header.className = 'tool-call-header';

        const toolName = tc.tool_name || tc.name || 'Tool Call';
        header.innerHTML = `
          <div class="tool-call-title">
            <span class="tool-badge">Tool</span>
            <span>${escapeHtml(toolName)}</span>
          </div>
          <span class="tool-call-toggle">▼</span>
        `;

        const body = document.createElement('div');
        body.className = 'tool-call-body';
        body.textContent = JSON.stringify(tc.parameters || tc.result || tc, null, 2);

        header.addEventListener('click', () => {
          item.classList.toggle('open');
        });

        item.appendChild(header);
        item.appendChild(body);
        toolContainer.appendChild(item);
      });

      bubble.appendChild(toolContainer);
    }

    // Render markdown content
    const content = document.createElement('div');
    content.className = 'message-content';
    content.innerHTML = renderMarkdown(markdownText);
    bubble.appendChild(content);

    // Metadata + Copy button
    const meta = document.createElement('div');
    meta.className = 'message-meta';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.title = 'Copy response text';
    copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
    copyBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(markdownText);
      copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`;
      setTimeout(() => {
        copyBtn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>`;
      }, 2000);
    });

    const timeSpan = document.createElement('span');
    timeSpan.textContent = formatTime(new Date());

    meta.appendChild(copyBtn);
    meta.appendChild(timeSpan);
    bubble.appendChild(meta);

    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    scrollToBottom();
  }

  // Helper: Append Typing Indicator
  function appendTypingIndicator() {
    const row = document.createElement('div');
    row.className = 'message-row bot typing-row';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="4"/></svg>`;

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    const indicator = document.createElement('div');
    indicator.className = 'typing-indicator';
    indicator.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span style="font-size:0.75rem; color:var(--text-muted); margin-left: 8px;">Holmes is investigating...</span>
    `;

    bubble.appendChild(indicator);
    row.appendChild(avatar);
    row.appendChild(bubble);
    messagesContainer.appendChild(row);
    scrollToBottom();
    return row;
  }

  // Render Saved History
  function renderHistory() {
    emptyState.style.display = 'none';
    conversationHistory.forEach((msg) => {
      if (msg.role === 'user') {
        appendUserMessage(msg.content);
      } else if (msg.role === 'assistant') {
        appendBotMessage(msg.content);
      }
    });
  }

  // Save history to localStorage
  function saveHistory() {
    try {
      localStorage.setItem('holmes_chat_history', JSON.stringify(conversationHistory.slice(-20)));
    } catch (e) {
      console.warn('Could not save chat history to localStorage:', e);
    }
  }

  // Scroll messages to bottom
  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Time formatter
  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // HTML escape
  function escapeHtml(str) {
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Markdown Parser
  function renderMarkdown(md) {
    if (!md) return '';

    // Code blocks with syntax formatting
    let out = md.replace(/```([a-zA-Z0-9_\-]+)?\n([\s\S]*?)```/g, (match, lang, code) => {
      return `<pre><code class="language-${lang || 'text'}">${escapeHtml(code.trim())}</code></pre>`;
    });

    // Inline code
    out = out.replace(/`([^`]+)`/g, (match, code) => {
      return `<code>${escapeHtml(code)}</code>`;
    });

    // Headers
    out = out.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    out = out.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    out = out.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    // Bold and italics
    out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');

    // Unordered lists
    out = out.replace(/^\s*[-*]\s+(.*$)/gim, '<li>$1</li>');
    out = out.replace(/(<li>.*<\/li>)/gims, '<ul>$1</ul>');

    // Paragraphs / line breaks
    out = out.split('\n\n').map(p => {
      if (p.startsWith('<h') || p.startsWith('<pre') || p.startsWith('<ul')) return p;
      return `<p>${p.replace(/\n/g, '<br/>')}</p>`;
    }).join('');

    return out;
  }

  // Fetch Holmes API Info (Periodic Status Check)
  async function checkHolmesStatus() {
    try {
      const res = await fetch('/api/info');
      if (res.ok) {
        const info = await res.json();
        statusText.textContent = `Connected`;
        systemStatus.style.background = 'rgba(16, 185, 129, 0.1)';
        systemStatus.style.borderColor = 'rgba(16, 185, 129, 0.25)';
        systemStatus.style.color = '#34d399';

        if (info.models && info.models.length > 0) {
          modelName.textContent = info.models.join(', ');
        }
        if (info.version) {
          versionTag.textContent = `Holmes v${info.version}`;
        }
        if (info.toolsets_summary && info.toolsets_summary.enabled !== undefined) {
          toolsetCount.textContent = `${info.toolsets_summary.enabled} Active`;
        }
      } else {
        throw new Error('Non-200 status');
      }
    } catch (err) {
      statusText.textContent = 'Disconnected';
      systemStatus.style.background = 'rgba(239, 68, 68, 0.1)';
      systemStatus.style.borderColor = 'rgba(239, 68, 68, 0.25)';
      systemStatus.style.color = '#f87171';
    }
  }

  // Initial check & poll every 15s
  checkHolmesStatus();
  setInterval(checkHolmesStatus, 15000);
});
