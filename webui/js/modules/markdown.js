/**
 * markdown.js — Markdown rendering and message formatting
 */
import { escHtml } from './utils.js';

let _toolCallIdCounter = 0;

export function stripMarkers(text) {
    return (text || '')
        .replace(/\/\*\*[\s\S]*?(?:\*\*\/?|$)/g, '')
        .replace(/\/\*[\s\S]*?(?:\*\/|$)/g, '')
        .replace(/\/\[\[.*?\]\]/g, '')
        .replace(/\/\(\(.*?\)\)/g, '');
}

export function _isErrorText(text) {
    if (!text) return false;
    return text.startsWith('[Error:') || text.startsWith('Error:') ||
           text.includes('[LLM Error') || text.includes('rate limit') ||
           text.includes('API error');
}

export function renderMarkdown(text) {
    if (!text) return '';
    let html = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

export function formatMessage(text) {
    if (!text) return '';

    const toolCards = [];
    const thinkBlocks = [];

    let html = text.replace(
        /\[TOOL_CALL:\s*(\w+)\s*\(([^)]*)\)\]/g,
        (match, name, args) => {
            const id = 'tc-' + (++_toolCallIdCounter);
            const cardHtml = `
                    <div class="tool-call-card" data-tool="${name}" data-tool-call-id="${id}">
                        <div class="tool-call-header">
                            <span class="material-icons-round tool-call-icon">build</span>
                            <span class="tool-call-name">${escHtml(name)}</span>
                            <span class="tool-call-status" data-status="running">
                                <span class="material-icons-round">sync</span>
                                Running...
                            </span>
                        </div>
                        <div class="tool-call-args"><code>${escHtml(args.trim() || '')}</code></div>
                    </div>
            `;
            toolCards.push(cardHtml);
            return `%%TC${toolCards.length}%%`;
        }
    );

    html = html.replace(
        /\[THINKING\]([\s\S]*?)\[\/THINKING\]/g,
        (match, content) => {
            const escapedContent = content.trim();
            const lines = escapedContent.split('\n').length;
            const summary = lines <= 3 ? escapedContent : escapedContent.split('\n').slice(0, 2).join('\n') + '...';
            const blockHtml = `
                <details class="thinking-block" ${lines <= 3 ? 'open' : ''}>
                    <summary class="thinking-summary">
                        <span class="material-icons-round thinking-icon">psychology</span>
                        <span class="thinking-label">Thought <span class="thinking-lines">(${lines} lines)</span></span>
                        <span class="thinking-preview">${renderMarkdown(summary)}</span>
                    </summary>
                    <div class="thinking-content">${renderMarkdown(escapedContent)}</div>
                </details>
            `;
            thinkBlocks.push(blockHtml);
            return `%%TB${thinkBlocks.length}%%`;
        }
    );

    html = renderMarkdown(html);

    toolCards.forEach((card, i) => {
        html = html.replace(`%%TC${i + 1}%%`, () => card);
    });
    thinkBlocks.forEach((block, i) => {
        html = html.replace(`%%TB${i + 1}%%`, () => block);
    });

    return html;
}

export function updateToolCall(toolId, status, result) {
    const card = document.querySelector(`.tool-call-card[data-tool-call-id="${toolId}"]`);
    if (!card) return;

    const statusEl = card.querySelector('.tool-call-status');
    const icons = {
        'running': ['sync', 'Running...'],
        'completed': ['check_circle', 'Completed'],
        'errored': ['error', 'Errored'],
        'retrying': ['refresh', 'Retrying...'],
    };
    const [icon, label] = icons[status] || ['help', status];

    statusEl.innerHTML = `<span class="material-icons-round">${icon}</span> ${label}`;
    statusEl.dataset.status = status;

    if (status === 'completed') {
        card.classList.add('tool-call-completed');
    } else if (status === 'errored') {
        card.classList.add('tool-call-errored');
        if (result) {
            const errorEl = document.createElement('div');
            errorEl.className = 'tool-call-error';
            errorEl.textContent = result;
            card.appendChild(errorEl);
        }
    }
}

export function addToolCallRetry(card, toolName, args) {
    const retryBtn = document.createElement('button');
    retryBtn.className = 'tool-call-retry icon-btn';
    retryBtn.innerHTML = '<span class="material-icons-round">refresh</span> Retry';
    retryBtn.title = 'Retry this tool call';
    retryBtn.addEventListener('click', async () => {
        const { getWs } = await import('./state.js');
        const ws = getWs();
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: 'retry_tool',
                tool: toolName,
                args: args,
            }));
        }
        retryBtn.disabled = true;
        retryBtn.innerHTML = '<span class="material-icons-round">sync</span> Retrying...';
    });
    card.appendChild(retryBtn);
}

export function getMessageHtml(role, text) {
    let bodyHtml;
    if (role === 'assistant') {
        bodyHtml = formatMessage(text || '');
        // Wrap code blocks in .code-block-wrapper with copy button
        bodyHtml = bodyHtml.replace(
            /<pre><code(?:\s+class="([^"]*)")?>([\s\S]*?)<\/code><\/pre>/g,
            (match, langClass, codeContent) => {
                const langAttr = langClass ? ` class="${langClass}"` : '';
                return '<div class="code-block-wrapper">' +
                    '<button class="copy-code-btn" aria-label="Copy code">' +
                        '<span class="material-icons-round" style="font-size:14px;vertical-align:middle">content_copy</span>' +
                    '</button>'
                    `<pre><code${langAttr}>${codeContent}</code></pre>` +
                    '</div>';
            }
        );
    } else {
        const escaped = escHtml(text || '');
        bodyHtml = escaped;
    }
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    return `<div class="msg-body">${bodyHtml}<span class="msg-timestamp">${timeStr}</span></div>` +
        `<div class="msg-actions">` +
            `<button class="msg-action" data-action="copy" title="Copy" aria-label="Copy message">` +
                `<span class="material-icons-round">content_copy</span>` +
            `</button>` +
            `<button class="msg-action" data-action="delete" title="Delete" aria-label="Delete message">` +
                `<span class="material-icons-round">delete</span>` +
            `</button>` +
            `${role === 'user' ? `
                <button class="msg-action" data-action="edit" title="Edit" aria-label="Edit message">
                    <span class="material-icons-round">edit</span>
                </button>
            ` : ''}` +
            `${role === 'assistant' ? `
                <button class="msg-action" data-action="regenerate" title="Regenerate" aria-label="Regenerate response">
                    <span class="material-icons-round">refresh</span>
                </button>
                <button class="msg-action" data-action="speak" title="Speak" aria-label="Speak message aloud">
                    <span class="material-icons-round">volume_up</span>
                </button>
            ` : ''}` +
        `</div>`;
}

/**
 * Apply highlight.js to all code blocks inside a container.
 * Safe to call multiple times — hljs skips already-highlighted elements.
 * Also wires up copy-code-btn click delegation once via module flag.
 */
let _copyBtnDelegationReady = false;
export function highlightCodeBlocks(container) {
    if (typeof window === 'undefined' || !window.hljs) return;
    const root = container || document;
    root.querySelectorAll('.msg-body pre code').forEach(el => {
        hljs.highlightElement(el);
    });

    // Wire copy button click delegation once per document
    if (!_copyBtnDelegationReady) {
        _copyBtnDelegationReady = true;
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('.copy-code-btn');
            if (!btn) return;
            const pre = btn.nextElementSibling;
            const code = pre?.querySelector('code');
            if (!code) return;
            navigator.clipboard.writeText(code.textContent || code.innerText).then(() => {
                btn.classList.add('copied');
                btn.innerHTML = 'Copied';
                setTimeout(() => {
                    btn.classList.remove('copied');
                    btn.innerHTML = '<span class="material-icons-round" style="font-size:14px;vertical-align:middle">content_copy</span>';
                }, 2000);
            });
        });
    }
}
