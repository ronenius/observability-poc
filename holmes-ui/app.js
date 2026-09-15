/**
 * HolmesGPT Web GUI Application Logic
 * Interactive Chat & Telemetry Investigation with Gemini Model Selector
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
  const versionTag = document.getElementById('version-tag');
  const toolsetCount = document.getElementById('toolset-count');

  // Model Selector & Modal Elements
  const modelSelect = document.getElementById('model-select');
  const backendModelsOptgroup = document.getElementById('backend-models-optgroup');
  const activeModelIndicator = document.getElementById('active-model-indicator');
  const toast = document.getElementById('toast');
  const customModelModal = document.getElementById('custom-model-modal');
  const customModelInput = document.getElementById('custom-model-input');
  const backendModelsChips = document.getElementById('backend-models-chips');
  const backendModelsCount = document.getElementById('backend-models-count');
  const closeModalBtn = document.getElementById('close-modal-btn');
  const cancelModalBtn = document.getElementById('cancel-modal-btn');
  const saveModalBtn = document.getElementById('save-modal-btn');

  // State
  let conversationHistory = [];
  let isSubmitting = false;

  // --------------------------------------------------
  // Model Selection Logic
  // --------------------------------------------------

  function getModelDisplayName(modelId) {
    if (!modelId || modelId === 'default') return 'Cluster Default';
    const base = modelId.includes('/') ? modelId.split('/').slice(1).join('/') : modelId;
    const formatted = base
      .replace(/[-_]/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    return formatted || modelId;
  }

  let toastTimer = null;
  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add('show');
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.classList.remove('show');
    }, 2500);
  }

  function updateActiveModelDisplay(modelId) {
    if (activeModelIndicator) {
      activeModelIndicator.innerHTML = `Model: <strong>${escapeHtml(getModelDisplayName(modelId))}</strong>`;
    }
  }

  // Load selected model from localStorage (defaults to first backend model when fetched)
  let selectedModel = localStorage.getItem('holmes_selected_model') || null;

  function addCustomOption(val) {
    if (!modelSelect || !val) return null;
    let opt = Array.from(modelSelect.options).find(o => o.value === val);
    if (!opt) {
      opt = document.createElement('option');
      opt.value = val;
      opt.textContent = `${getModelDisplayName(val)} (${val})`;
      let customGroup = modelSelect.querySelector('optgroup[label="Custom Models"]');
      if (!customGroup) {
        customGroup = document.createElement('optgroup');
        customGroup.label = 'Custom Models';
        const configGroup = modelSelect.querySelector('optgroup[label="Configuration"]');
        if (configGroup) {
          modelSelect.insertBefore(customGroup, configGroup);
        } else {
          modelSelect.appendChild(customGroup);
        }
      }
      customGroup.appendChild(opt);
    }
    return opt;
  }

  function applyCustomModel(customVal) {
    if (!customVal) return;
    addCustomOption(customVal);
    selectedModel = customVal;
    if (modelSelect) modelSelect.value = selectedModel;
    localStorage.setItem('holmes_selected_model', selectedModel);
    updateActiveModelDisplay(selectedModel);
    closeCustomModal();
    showToast(`✨ Model set to ${getModelDisplayName(customVal)}`);
  }

  // Synchronize dynamic models strictly from Holmes backend (/api/info)
  let cachedBackendModels = [];
  function syncBackendModels(models) {
    if (!modelSelect) return;
    cachedBackendModels = Array.isArray(models) ? models : [];

    // 1. Update count in modal
    if (backendModelsCount) {
      backendModelsCount.textContent = `${cachedBackendModels.length} model${cachedBackendModels.length === 1 ? '' : 's'}`;
    }

    // 2. Render chips in Custom Model Modal
    if (backendModelsChips) {
      backendModelsChips.innerHTML = '';
      if (cachedBackendModels.length === 0) {
        backendModelsChips.innerHTML = '<div class="backend-models-empty">No models reported by Holmes backend.</div>';
      } else {
        cachedBackendModels.forEach(modelId => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'model-chip' + (selectedModel === modelId ? ' selected' : '');
          chip.title = `Click to choose ${modelId} (${getModelDisplayName(modelId)})`;
          chip.innerHTML = `<span class="model-chip-icon">🤖</span><span>${escapeHtml(modelId)}</span>`;
          
          chip.addEventListener('click', () => {
            backendModelsChips.querySelectorAll('.model-chip').forEach(c => c.classList.remove('selected'));
            chip.classList.add('selected');
            if (customModelInput) {
              customModelInput.value = modelId;
              customModelInput.focus();
            }
          });

          // Double click immediately applies
          chip.addEventListener('dblclick', () => {
            applyCustomModel(modelId);
          });

          backendModelsChips.appendChild(chip);
        });
      }
    }

    // 3. Build dropdown options exclusively from Holmes backend
    modelSelect.innerHTML = '';

    if (cachedBackendModels.length > 0) {
      const backendGroup = document.createElement('optgroup');
      backendGroup.label = 'Holmes Backend Models';
      backendGroup.id = 'backend-models-optgroup';

      cachedBackendModels.forEach(modelId => {
        const opt = document.createElement('option');
        opt.value = modelId;
        opt.textContent = `${getModelDisplayName(modelId)} (${modelId})`;
        backendGroup.appendChild(opt);
      });
      modelSelect.appendChild(backendGroup);
    }

    // Configuration / custom option group
    const configGroup = document.createElement('optgroup');
    configGroup.label = 'Configuration';
    configGroup.id = 'config-optgroup';

    const defaultOpt = document.createElement('option');
    defaultOpt.value = 'default';
    defaultOpt.textContent = 'Cluster Default (Backend Auto)';
    configGroup.appendChild(defaultOpt);

    const customOpt = document.createElement('option');
    customOpt.value = 'custom';
    customOpt.textContent = '+ Custom Model...';
    configGroup.appendChild(customOpt);

    modelSelect.appendChild(configGroup);

    // 4. Resolve default or preserved selection
    if (!selectedModel) {
      // Default to the first model in backend list if available, else 'default'
      selectedModel = cachedBackendModels.length > 0 ? cachedBackendModels[0] : 'default';
    } else if (selectedModel !== 'default') {
      const exists = Array.from(modelSelect.options).some(o => o.value === selectedModel);
      if (!exists) {
        addCustomOption(selectedModel);
      }
    }

    modelSelect.value = selectedModel;
    updateActiveModelDisplay(selectedModel);
  }

  // Model Dropdown Change Handler
  if (modelSelect) {
    modelSelect.addEventListener('change', () => {
      const val = modelSelect.value;
      if (val === 'custom') {
        // Revert select display until confirmed
        modelSelect.value = selectedModel;
        customModelModal.style.display = 'flex';
        customModelInput.value = selectedModel !== 'default' ? selectedModel : '';
        customModelInput.focus();

        // Highlight matching chip if present
        if (backendModelsChips) {
          backendModelsChips.querySelectorAll('.model-chip').forEach(c => {
            const label = c.querySelector('span:last-child')?.textContent || c.textContent.trim();
            if (label === selectedModel) {
              c.classList.add('selected');
            } else {
              c.classList.remove('selected');
            }
          });
        }
      } else {
        selectedModel = val;
        localStorage.setItem('holmes_selected_model', selectedModel);
        updateActiveModelDisplay(selectedModel);
        showToast(`✨ Switched model to ${getModelDisplayName(selectedModel)}`);
      }
    });
  }

  // Custom Modal Handlers
  function closeCustomModal() {
    if (customModelModal) customModelModal.style.display = 'none';
  }
  if (closeModalBtn) closeModalBtn.addEventListener('click', closeCustomModal);
  if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeCustomModal);
  if (customModelModal) {
    customModelModal.addEventListener('click', (e) => {
      if (e.target === customModelModal) closeCustomModal();
    });
  }

  if (saveModalBtn) {
    saveModalBtn.addEventListener('click', () => {
      const customVal = customModelInput.value.trim();
      if (!customVal) {
        customModelInput.focus();
        return;
      }
      applyCustomModel(customVal);
    });
  }

  if (customModelInput) {
    customModelInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        saveModalBtn.click();
      } else if (e.key === 'Escape') {
        closeCustomModal();
      }
    });
  }

  // --------------------------------------------------
  // Chat History & Persistence
  // --------------------------------------------------

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
      showToast('Conversation history reset.');
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

  // --------------------------------------------------
  // Form Submit (Send Message with Selected Model)
  // --------------------------------------------------

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
      // Prepare clean conversation history payload
      const historyToSend = conversationHistory.map(m => ({
        role: m.role,
        content: m.content
      }));
      // Ensure compatibility with OpenAI / LiteLLM format
      if (historyToSend.length > 0 && historyToSend[0].role !== 'system') {
        historyToSend.unshift({ role: 'system', content: '' });
      }

      // Build request body with selected model
      const reqBody = {
        ask: query,
        conversation_history: historyToSend
      };
      if (selectedModel && selectedModel !== 'default') {
        reqBody.model = selectedModel;
      }

      // Call Holmes API via reverse proxy
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(reqBody)
      });

      // Remove typing indicator
      typingIndicator.remove();

      if (!response.ok) {
        const errText = await response.text();
        appendBotMessage(
          `⚠️ **Holmes API Error (${response.status})**\n\n\`\`\`\n${errText || response.statusText}\n\`\`\`\n*Ensure an LLM API key is configured in the secret \`holmes-secrets\`.*`,
          []
        );
        return;
      }

      const data = await response.json();
      const analysis = data.analysis || 'Investigation completed without output.';
      const toolCalls = data.tool_calls || [];

      // Add to conversation history with model metadata
      conversationHistory.push({ role: 'user', content: query });
      conversationHistory.push({ 
        role: 'assistant', 
        content: analysis, 
        tool_calls: toolCalls,
        model: selectedModel 
      });
      saveHistory();

      // Render Bot Message
      appendBotMessage(analysis, toolCalls, selectedModel);

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
  function appendBotMessage(markdownText, toolCalls = [], modelUsed = null) {
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

      toolCalls.forEach((tc) => {
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

    // Metadata + Model Tag + Copy button
    const meta = document.createElement('div');
    meta.className = 'message-meta';

    if (modelUsed) {
      const modelTag = document.createElement('span');
      modelTag.className = 'message-model-tag';
      modelTag.textContent = `✨ ${getModelDisplayName(modelUsed)}`;
      meta.appendChild(modelTag);
    }

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
      <span style="font-size:0.75rem; color:var(--text-muted); margin-left: 8px;">Holmes is investigating with ${escapeHtml(getModelDisplayName(selectedModel))}...</span>
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
        appendBotMessage(msg.content, msg.tool_calls || [], msg.model);
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

  // Format time (HH:MM AM/PM)
  function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // Scroll messages to bottom
  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // HTML escape
  function escapeHtml(str) {
    return String(str)
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

        if (info.models && Array.isArray(info.models) && info.models.length > 0) {
          syncBackendModels(info.models);
          const defaultModelOpt = modelSelect.querySelector('option[value="default"]');
          if (defaultModelOpt) {
            defaultModelOpt.textContent = `Cluster Default (${info.models[0]})`;
          }
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
