(function () {
    'use strict';

    // Guard against the script being included more than once on the same page.
    if (window.__stratumChatbotLoaded) return;
    window.__stratumChatbotLoaded = true;

    const currentScript = document.currentScript;

    // Read a data-* attribute from our own <script> tag, falling back to a default.
    function attr(name, fallback) {
        const v = currentScript && currentScript.getAttribute(name);
        return (v !== null && v !== undefined && v !== '') ? v : fallback;
    }

    // Origin of the server that actually served THIS script. When the widget is
    // embedded on a different site/instance than the API, this is the right default
    // because the API lives on the same server that hosts chatbot.js.
    function scriptOrigin() {
        try {
            return new URL(currentScript.src, window.location.href).origin;
        } catch (e) {
            return null;
        }
    }

    const projectSlug = attr('data-project-slug', 'demo-project');
    // Priority: explicit data-base-url > origin the script was served from > page origin.
    const baseUrl = attr('data-base-url', null) || scriptOrigin() || window.location.origin;

    // Configuration - overridable per-site via data-* attributes on the <script> tag.
    const CONFIG = {
        API_URL: `${baseUrl}/api/${projectSlug}/v1/chat/completions`,
        // Injected server-side from .env when served via /static/chatbot.js; a
        // data-api-key attribute overrides it for other deployments.
        API_KEY: attr('data-api-key', "__CHATBOT_API_KEY__"),
        TIMEOUT: parseInt(attr('data-timeout', ''), 10) || 120000,
        BRAND_NAME: attr('data-brand-name', "Stratum"),
        BRAND_SUBTITLE: attr('data-brand-subtitle', "Grounded answers · Local LLM"),
        // No default logo shipped: the widget falls back to the brand mark.
        // Point data-logo at your own image URL to show a logo.
        LOGO_PATH: attr('data-logo', ""),
        WELCOME: attr('data-welcome', "Hi! Ask me anything about the documents in this knowledge base. I answer only from what's actually in them — with sources, tables and charts when they help."),
        // Pipe-separated quick-start chips shown under the welcome message.
        SUGGESTIONS: attr('data-suggestions',
            "What topics can you answer questions about?|Summarize the key points as a table|What are the most important rules I must follow?"),
        // BCP-47 language for voice input (falls back to the browser language).
        VOICE_LANG: attr('data-voice-lang', (navigator.language || 'en-US')),
    };

    // Returns an abort signal that fires after `ms`. Uses the native AbortSignal.timeout
    // when available, otherwise falls back to AbortController for older browsers.
    function timeoutSignal(ms) {
        if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
            return AbortSignal.timeout(ms);
        }
        const controller = new AbortController();
        setTimeout(() => controller.abort(), ms);
        return controller.signal;
    }

    // ------------------------------------------------------------------
    // Lucide icons (inlined, ISC license) — stroke inherits currentColor.
    // ------------------------------------------------------------------
    function icon(name, size) {
        const paths = {
            layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
            x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
            send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
            mic: '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" x2="12" y1="19" y2="22"/>',
            rotateCcw: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
            copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
            check: '<path d="M20 6 9 17l-5-5"/>',
            table: '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/>',
            chart: '<path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
            sparkle: '<path d="M12 3l1.9 5.8a2 2 0 0 0 1.3 1.3L21 12l-5.8 1.9a2 2 0 0 0-1.3 1.3L12 21l-1.9-5.8a2 2 0 0 0-1.3-1.3L3 12l5.8-1.9a2 2 0 0 0 1.3-1.3Z"/>',
        };
        const s = size || 18;
        return `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ''}</svg>`;
    }

    // ------------------------------------------------------------------
    // Widget styles. `:host { all: initial }` resets inheritance from the
    // host page so the site's CSS can't bleed through the shadow boundary.
    // ------------------------------------------------------------------
    const styleText = `
        :host { all: initial; }

        :host {
            /* Stratum soft identity — charcoal base, small navy/red touches */
            --st-accent:     #232327;
            --st-accent-2:   #3E3E45;
            --st-link:       #1E3A8A;
            --st-bg:         #FFFFFF;   /* window chrome (header/composer) */
            --st-canvas:     #F6F6F7;   /* soft grey conversation canvas   */
            --st-surface:    #FFFFFF;   /* assistant bubbles, cards        */
            --st-surface-2:  #F2F2F4;   /* hover / raised                  */
            --st-line:       #ECECEE;
            --st-ink:        #232327;
            --st-ink-2:      #5C5C64;
            --st-ink-3:      #A6A6AD;
            --st-user-bub:   #2E2E34;   /* soft charcoal user bubble       */
            --st-user-ink:   #FFFFFF;
            --st-danger:     #B91C1C;
            --st-danger-bg:  rgba(185, 28, 28, .06);
            --st-ok:         #5C5C64;
            --st-font:       Inter, "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
            --st-mono:       Consolas, "Cascadia Code", ui-monospace, monospace;
            --st-shadow:     0 18px 50px rgba(20, 20, 25, .14), 0 4px 14px rgba(20, 20, 25, .06);
        }

        /* ---------- Launcher bubble ---------- */
        .st-bubble {
            position: fixed; bottom: 28px; right: 28px;
            width: 58px; height: 58px; border-radius: 50%;
            background: var(--st-accent);
            border: none;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; z-index: 2147483000;
            color: #fff;
            box-shadow: 0 8px 24px rgba(20, 20, 25, .18), 0 2px 6px rgba(20, 20, 25, .12);
            transition: transform .22s ease, box-shadow .22s ease, background .18s;
            font-family: var(--st-font);
        }
        .st-bubble:hover {
            transform: translateY(-2px) scale(1.03);
            background: var(--st-accent-2);
            box-shadow: 0 14px 32px rgba(20, 20, 25, .2);
        }
        .st-bubble .st-b-open, .st-bubble .st-b-close {
            position: absolute; display: flex;
            transition: opacity .25s, transform .35s cubic-bezier(.68,-.55,.26,1.55);
        }
        .st-bubble .st-b-close { opacity: 0; transform: scale(.4) rotate(-90deg); }
        .st-bubble.open .st-b-open { opacity: 0; transform: scale(.4) rotate(90deg); }
        .st-bubble.open .st-b-close { opacity: 1; transform: scale(1) rotate(0); }
        .st-bubble img { width: 32px; height: 32px; border-radius: 9px; object-fit: cover; }

        /* ---------- Window ---------- */
        .st-window {
            position: fixed; bottom: 102px; right: 28px;
            width: 430px; height: 680px; max-height: calc(100vh - 130px);
            background: var(--st-bg);
            border: 1px solid var(--st-line);
            border-radius: 20px; overflow: hidden;
            display: none; flex-direction: column;
            z-index: 2147483000; box-shadow: var(--st-shadow);
            font-family: var(--st-font);
            color: var(--st-ink);
        }
        .st-window.active { display: flex; animation: stRise .28s cubic-bezier(.2,.9,.3,1); }
        @keyframes stRise { from { opacity: 0; transform: translateY(16px) scale(.98); } to { opacity: 1; transform: none; } }

        /* ---------- Header ---------- */
        .st-header {
            padding: 16px 18px 14px;
            background: var(--st-bg);
            display: flex; align-items: center; gap: 12px;
            border-bottom: 1px solid var(--st-line);
            position: relative;
        }
        .st-logo {
            width: 40px; height: 40px; border-radius: 12px; flex: none;
            background: var(--st-accent);
            color: #fff; display: flex; align-items: center; justify-content: center;
            overflow: hidden;
        }
        .st-logo img { width: 100%; height: 100%; object-fit: cover; }
        .st-head-info { flex: 1; min-width: 0; }
        .st-head-title {
            font-size: 15.5px; font-weight: 700; letter-spacing: -.01em; color: var(--st-ink);
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .st-head-sub {
            display: flex; align-items: center; gap: 6px;
            font-size: 12px; color: var(--st-ink-2); margin-top: 2px;
        }
        .st-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--st-link); flex: none; }
        .st-head-btn {
            width: 34px; height: 34px; border-radius: 10px; border: none; flex: none;
            background: transparent; color: var(--st-ink-2); cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: background .18s, color .18s;
        }
        .st-head-btn:hover { background: var(--st-surface-2); color: var(--st-ink); }

        /* ---------- Messages ---------- */
        .st-msgs {
            flex: 1; overflow-y: auto; padding: 18px 16px 8px;
            background: var(--st-canvas);
            scrollbar-width: thin; scrollbar-color: #D4D4D8 transparent;
        }
        .st-msgs::-webkit-scrollbar { width: 6px; }
        .st-msgs::-webkit-scrollbar-thumb { background: #D4D4D8; border-radius: 3px; }

        .st-welcome { margin-bottom: 16px; }
        .st-hello {
            background: var(--st-surface); border: 1px solid var(--st-line);
            border-radius: 18px 18px 18px 6px; padding: 14px 16px;
            font-size: 13.5px; line-height: 1.6; color: var(--st-ink);
            box-shadow: 0 1px 3px rgba(20, 20, 25, .05);
        }
        .st-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
        .st-chip {
            border: 1px solid var(--st-line); background: var(--st-bg);
            color: var(--st-ink-2); border-radius: 999px; padding: 8px 15px;
            font-size: 12.5px; font-weight: 500; cursor: pointer; font-family: inherit;
            transition: background .18s, border-color .18s, color .18s;
            text-align: left; box-shadow: 0 1px 3px rgba(20, 20, 25, .05);
        }
        .st-chip:hover { background: var(--st-surface-2); border-color: #D8D8DC; color: var(--st-ink); }

        .st-msg { display: flex; margin-bottom: 14px; animation: stFade .25s ease-out; }
        @keyframes stFade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
        .st-msg.user { justify-content: flex-end; }
        .st-msg-content {
            max-width: 86%; padding: 11px 15px; border-radius: 18px;
            font-size: 13.5px; line-height: 1.6; word-wrap: break-word; min-width: 0;
        }
        .st-msg.user .st-msg-content {
            background: var(--st-user-bub); color: var(--st-user-ink);
            border-radius: 18px 18px 6px 18px; font-weight: 450;
            box-shadow: 0 2px 6px rgba(20, 20, 25, .12);
        }
        .st-msg.assistant { flex-direction: column; align-items: flex-start; }
        .st-msg.assistant .st-msg-content {
            background: var(--st-surface); color: var(--st-ink);
            border: 1px solid var(--st-line); border-radius: 18px 18px 18px 6px;
            box-shadow: 0 1px 3px rgba(20, 20, 25, .05);
        }

        /* message actions (copy) shown under finished assistant messages */
        .st-msg-actions { display: flex; gap: 6px; margin: 4px 0 0 4px; opacity: 0; transition: opacity .15s; }
        .st-msg.assistant:hover .st-msg-actions { opacity: 1; }
        .st-act-btn {
            display: inline-flex; align-items: center; gap: 5px;
            border: none; background: transparent; color: var(--st-ink-3);
            font-size: 11px; font-family: var(--st-mono); cursor: pointer; padding: 3px 6px; border-radius: 6px;
        }
        .st-act-btn:hover { background: var(--st-surface-2); color: var(--st-ink-2); }

        /* ---------- Markdown ---------- */
        .st-msg-content div + div { margin-top: 4px; }
        .st-gap { height: 6px; }
        .st-h { font-weight: 700; margin: 8px 0 2px; letter-spacing: -.01em; }
        .st-h1 { font-size: 15px; } .st-h2 { font-size: 14.5px; } .st-h3, .st-h4 { font-size: 13.5px; }
        .st-hr { height: 1px; background: var(--st-line); margin: 10px 0; }
        .st-msg-content ul, .st-msg-content ol { margin: 6px 0; padding-left: 20px; }
        .st-msg-content li { margin: 3px 0; }
        .st-msg-content code {
            background: var(--st-surface-2); padding: 1px 5px; border-radius: 4px;
            font-size: 12.5px; font-family: var(--st-mono);
        }
        .st-msg-content a { color: var(--st-link); text-decoration: underline; text-underline-offset: 2px; }
        .st-code {
            background: var(--st-surface-2); border: 1px solid var(--st-line); border-radius: 12px;
            padding: 10px 12px; margin: 8px 0; overflow-x: auto;
            font-family: var(--st-mono); font-size: 12px; line-height: 1.5; color: var(--st-ink);
        }
        .st-code code { background: transparent; padding: 0; font-size: inherit; }

        /* tables */
        .st-tblblock { margin: 8px 0; max-width: 100%; }
        .st-tbl-tools { display: flex; justify-content: flex-end; gap: 4px; margin-bottom: 4px; }
        .st-tbl-tools button {
            display: inline-flex; align-items: center; gap: 5px;
            border: 1px solid var(--st-line); background: transparent; color: var(--st-ink-3);
            font-size: 10.5px; font-family: var(--st-mono); font-weight: 600;
            padding: 3px 8px; border-radius: 6px; cursor: pointer;
        }
        .st-tbl-tools button.on { color: var(--st-ink); border-color: var(--st-ink-3); background: var(--st-surface-2); }
        .st-tablewrap { overflow-x: auto; border: 1px solid var(--st-line); border-radius: 12px; }
        table.st-table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
        .st-table th, .st-table td { padding: 7px 10px; text-align: left; white-space: nowrap; }
        .st-table th {
            background: var(--st-surface-2); color: var(--st-ink-2); font-weight: 700;
            font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
            border-bottom: 1px solid var(--st-line);
        }
        .st-table td { border-bottom: 1px solid var(--st-line); color: var(--st-ink); font-variant-numeric: tabular-nums; }
        .st-table tr:last-child td { border-bottom: none; }

        /* charts */
        .st-chartblock { margin: 8px 0; }
        .st-chart-card { background: var(--st-surface); border: 1px solid var(--st-line); border-radius: 12px; padding: 10px 10px 8px; }
        .st-chart-title { font-family: var(--st-mono); font-size: 11px; color: var(--st-ink-2); margin: 0 0 6px 2px; }
        .st-chart-card svg { display: block; width: 100%; height: auto; }
        .st-legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 6px 2px 0; }
        .st-legend span { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--st-ink-2); }
        .st-legend i { width: 9px; height: 9px; border-radius: 3px; flex: none; }

        /* ---------- Typing indicator ---------- */
        .st-typing {
            display: inline-flex; gap: 4px; padding: 13px 15px;
            background: var(--st-surface); border: 1px solid var(--st-line);
            border-radius: 18px 18px 18px 6px;
            box-shadow: 0 1px 3px rgba(20, 20, 25, .05);
        }
        .st-typing span {
            width: 7px; height: 7px; border-radius: 50%; background: var(--st-ink-3);
            animation: stPulse 1.2s infinite ease-in-out both;
        }
        .st-typing span:nth-child(2) { animation-delay: .15s; }
        .st-typing span:nth-child(3) { animation-delay: .3s; }
        @keyframes stPulse { 0%, 70%, 100% { transform: scale(.55); opacity: .4; } 35% { transform: scale(1); opacity: 1; } }

        /* ---------- Composer ---------- */
        .st-composer { padding: 12px 14px 10px; border-top: 1px solid var(--st-line); background: var(--st-bg); }
        .st-error {
            display: none; margin-bottom: 8px; padding: 8px 12px; border-radius: 10px;
            background: var(--st-danger-bg); border: 1px solid rgba(185,28,28,.25);
            color: var(--st-danger); font-size: 12px;
        }
        .st-error.active { display: block; }
        .st-input-row {
            display: flex; align-items: center; gap: 6px;
            background: var(--st-canvas); border: 1px solid var(--st-line);
            border-radius: 999px; padding: 5px 5px 5px 17px;
            transition: border-color .18s, box-shadow .18s, background .18s;
        }
        .st-input-row:focus-within { background: var(--st-bg); border-color: rgba(30,58,138,.4); box-shadow: 0 0 0 4px rgba(30,58,138,.07); }
        .st-input {
            flex: 1; min-width: 0; border: none; outline: none; background: transparent;
            color: var(--st-ink); font-size: 13.5px; font-family: inherit; padding: 9px 0;
        }
        .st-input::placeholder { color: var(--st-ink-3); }
        .st-icon-btn {
            width: 38px; height: 38px; border-radius: 50%; border: none; flex: none;
            display: flex; align-items: center; justify-content: center; cursor: pointer;
            background: transparent; color: var(--st-ink-2);
            transition: background .18s, color .18s, transform .15s;
        }
        .st-icon-btn:hover { background: var(--st-surface-2); color: var(--st-ink); }
        .st-icon-btn:disabled { opacity: .45; cursor: not-allowed; }
        .st-mic.listening {
            color: #fff; background: var(--st-danger);
            animation: stMic 1.2s infinite;
        }
        @keyframes stMic {
            0%, 100% { box-shadow: 0 0 0 0 rgba(185,28,28,.35); }
            60% { box-shadow: 0 0 0 9px rgba(185,28,28,0); }
        }
        .st-send {
            background: var(--st-accent); color: #fff;
            box-shadow: 0 2px 6px rgba(20, 20, 25, .16);
        }
        .st-send:hover:not(:disabled) { background: var(--st-accent-2); color: #fff; transform: scale(1.05); }
        .st-foot {
            display: flex; align-items: center; justify-content: center; gap: 6px;
            margin-top: 8px; font-size: 11px; color: var(--st-ink-3);
        }
        .st-foot svg { opacity: .7; }

        @media (max-width: 768px) {
            .st-window { width: calc(100vw - 20px); right: 10px; bottom: 96px; height: 76vh; }
            .st-bubble { bottom: 20px; right: 20px; }
        }
    `;

    // ------------------------------------------------------------------
    // Markup
    // ------------------------------------------------------------------
    const suggestionChips = CONFIG.SUGGESTIONS.split('|').map(s => s.trim()).filter(Boolean)
        .map(s => `<button class="st-chip" data-message="${s.replace(/"/g, '&quot;')}">${s.replace(/</g, '&lt;')}</button>`).join('');

    const chatHTML = `
        <div class="st-bubble" id="stBubble" role="button" aria-label="Open chat" tabindex="0">
            <span class="st-b-open">${CONFIG.LOGO_PATH ? `<img src="${CONFIG.LOGO_PATH}" alt="">` : icon('layers', 28)}</span>
            <span class="st-b-close">${icon('x', 26)}</span>
        </div>

        <div class="st-window" id="stWindow" role="dialog" aria-label="${CONFIG.BRAND_NAME} chat">
            <div class="st-header">
                <div class="st-logo">${CONFIG.LOGO_PATH ? `<img src="${CONFIG.LOGO_PATH}" alt="">` : icon('layers', 24)}</div>
                <div class="st-head-info">
                    <div class="st-head-title">${CONFIG.BRAND_NAME}</div>
                    <div class="st-head-sub"><span class="st-dot"></span>${CONFIG.BRAND_SUBTITLE}</div>
                </div>
                <button class="st-head-btn" id="stReset" title="New conversation">${icon('rotateCcw', 17)}</button>
                <button class="st-head-btn" id="stClose" title="Close">${icon('x', 19)}</button>
            </div>

            <div class="st-msgs" id="stMsgs">
                <div class="st-welcome" id="stWelcome">
                    <div class="st-hello">${CONFIG.WELCOME}</div>
                    <div class="st-chips">${suggestionChips}</div>
                </div>
            </div>

            <div class="st-composer">
                <div class="st-error" id="stError"></div>
                <div class="st-input-row">
                    <input type="text" class="st-input" id="stInput" placeholder="Ask about your documents…" autocomplete="off">
                    <button class="st-icon-btn st-mic" id="stMic" title="Voice input">${icon('mic', 18)}</button>
                    <button class="st-icon-btn st-send" id="stSend" title="Send">${icon('send', 17)}</button>
                </div>
                <div class="st-foot">${icon('layers', 11)} ${CONFIG.BRAND_NAME} · hybrid retrieval · answers grounded in your documents</div>
            </div>
        </div>
    `;

    // Shadow root that hosts the widget. Created during mount() (once the document
    // body exists) so the host page's CSS can't affect the widget and vice-versa.
    let root = null;

    // ==================================================================
    // Markdown -> HTML
    // Escapes HTML first (so model output can't inject markup), then renders
    // headings, lists, GFM tables, fenced code, chart fences and inline marks.
    // ==================================================================
    function escapeHtml(s) {
        return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function unescapeHtml(s) {
        return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    }

    function inline(s) {
        return s
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
            .replace(/(^|\s)(https?:\/\/[^\s]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
    }

    function renderMarkdown(text) {
        const lines = escapeHtml(text).split('\n');
        let html = '';
        let list = null;           // 'ul' | 'ol' | null
        let i = 0;
        const closeList = () => { if (list) { html += `</${list}>`; list = null; } };

        while (i < lines.length) {
            const line = lines[i];

            // fenced code block  ```lang
            const fence = line.match(/^\s*```(\w*)\s*$/);
            if (fence) {
                closeList();
                const lang = (fence[1] || '').toLowerCase();
                const buf = [];
                i++;
                while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
                const closed = i < lines.length;
                if (closed) i++;
                const body = buf.join('\n');
                if (lang === 'chart') {
                    // Rendered later by hydrateCharts() once the JSON is complete.
                    html += `<div class="st-chartblock" data-spec="${encodeURIComponent(unescapeHtml(body))}" data-closed="${closed ? 1 : 0}"></div>`;
                } else {
                    html += `<pre class="st-code"><code>${body}</code></pre>`;
                }
                continue;
            }

            // GFM table: a | row followed by a |---|---| separator
            if (/^\s*\|/.test(line) && i + 1 < lines.length &&
                /^\s*\|?[\s:|-]+$/.test(lines[i + 1]) && lines[i + 1].includes('-') && lines[i + 1].includes('|')) {
                closeList();
                const rows = [line];
                i += 2; // skip separator
                while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(lines[i]); i++; }
                html += renderTable(rows);
                continue;
            }

            // heading
            const h = line.match(/^\s*(#{1,6})\s+(.*)$/);
            if (h) { closeList(); html += `<div class="st-h st-h${Math.min(h[1].length, 4)}">${inline(h[2])}</div>`; i++; continue; }

            // horizontal rule
            if (/^\s*---+\s*$/.test(line)) { closeList(); html += '<div class="st-hr"></div>'; i++; continue; }

            // lists
            const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
            const ordered = line.match(/^\s*\d+[.)]\s+(.*)$/);
            if (bullet) { if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; } html += `<li>${inline(bullet[1])}</li>`; i++; continue; }
            if (ordered) { if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; } html += `<li>${inline(ordered[1])}</li>`; i++; continue; }

            closeList();
            if (line.trim() === '') html += '<div class="st-gap"></div>';
            else html += `<div>${inline(line)}</div>`;
            i++;
        }
        closeList();
        return html;
    }

    function splitRow(row) {
        let cells = row.trim().split('|');
        if (cells.length && cells[0].trim() === '') cells.shift();
        if (cells.length && cells[cells.length - 1].trim() === '') cells.pop();
        return cells.map(c => c.trim());
    }

    function renderTable(rows) {
        const head = splitRow(rows[0]);
        const body = rows.slice(1).map(splitRow);
        let t = '<div class="st-tblblock"><div class="st-tablewrap"><table class="st-table"><thead><tr>';
        head.forEach(c => t += `<th>${inline(c)}</th>`);
        t += '</tr></thead><tbody>';
        body.forEach(r => {
            t += '<tr>';
            for (let c = 0; c < head.length; c++) t += `<td>${inline(r[c] !== undefined ? r[c] : '')}</td>`;
            t += '</tr>';
        });
        t += '</tbody></table></div></div>';
        return t;
    }

    // ==================================================================
    // Charts — tiny dependency-free SVG renderer.
    // Monochrome greyscale palette (fixed slot order): adjacent slots
    // alternate dark/light so series stay distinguishable without hue;
    // tables stay one toggle away, so the data always has a text view.
    // ==================================================================
    const CHART_COLORS = ['#1E3A8A', '#8B97B8', '#232327', '#C6CDDE', '#5C5C64', '#D8D8DC'];
    // per-slot label ink: white on dark slots, near-black on light slots
    const CHART_LABEL_INK = ['#FFFFFF', '#FFFFFF', '#FFFFFF', '#232327', '#FFFFFF', '#232327'];
    const CHART_GRID = '#E4E4E7';
    const CHART_SURFACE = '#FFFFFF';
    const CHART_INK = '#71717A';

    function fmtNum(v) {
        if (!isFinite(v)) return '';
        const a = Math.abs(v);
        if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
        if (a >= 1e4) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
        return (Math.round(v * 100) / 100).toLocaleString();
    }

    function niceMax(v) {
        if (v <= 0) return 1;
        const p = Math.pow(10, Math.floor(Math.log10(v)));
        for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]) {
            if (m * p >= v) return m * p;
        }
        return 10 * p;
    }

    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }

    // spec: { type: 'bar'|'line'|'donut'|'pie', title?, labels: [], series: [{name, data: []}] }
    function buildChart(spec) {
        const type = (spec.type || 'bar').toLowerCase();
        const labels = (spec.labels || []).map(String);
        let series = (spec.series || []).filter(s => Array.isArray(s.data) && s.data.length);
        if (!labels.length || !series.length) return '';
        series = series.slice(0, CHART_COLORS.length); // fixed palette, never cycled

        let svg = '';
        if (type === 'donut' || type === 'pie') svg = donutSvg(labels, series[0]);
        else if (type === 'line') svg = lineSvg(labels, series);
        else svg = barSvg(labels, series);
        if (!svg) return '';

        let legend = '';
        const legendItems = (type === 'donut' || type === 'pie') ? labels : (series.length > 1 ? series.map(s => s.name || '') : []);
        if (legendItems.length) {
            legend = '<div class="st-legend">' + legendItems.map((n, ix) =>
                `<span><i style="background:${CHART_COLORS[ix % CHART_COLORS.length]}"></i>${esc(n || ('Series ' + (ix + 1)))}</span>`).join('') + '</div>';
        }
        const title = spec.title ? `<div class="st-chart-title">${esc(spec.title)}</div>` : '';
        return `<div class="st-chart-card">${title}${svg}${legend}</div>`;
    }

    function barSvg(labels, series) {
        const W = 360, H = 200, padL = 38, padR = 8, padT = 14, padB = 26;
        const iw = W - padL - padR, ih = H - padT - padB;
        const max = niceMax(Math.max(...series.flatMap(s => s.data.map(v => +v || 0)), 0));
        const y = v => padT + ih - (v / max) * ih;
        let out = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
        // recessive grid: 4 hairlines + baseline
        for (let g = 1; g <= 4; g++) {
            const gy = padT + ih - (g / 4) * ih;
            out += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="${CHART_GRID}" stroke-width="1"/>`;
            out += `<text x="${padL - 5}" y="${gy + 3}" font-size="9" fill="${CHART_INK}" text-anchor="end" font-family="Consolas,monospace">${fmtNum(max * g / 4)}</text>`;
        }
        out += `<line x1="${padL}" y1="${padT + ih}" x2="${W - padR}" y2="${padT + ih}" stroke="#D4D4D8" stroke-width="1"/>`;

        const groupW = iw / labels.length;
        const barGap = 2;                                   // 2px surface gap between adjacent bars
        const barW = Math.min(26, Math.max(4, (groupW * 0.72 - barGap * (series.length - 1)) / series.length));
        const totalBars = labels.length * series.length;
        labels.forEach((lab, li) => {
            const gx = padL + li * groupW + (groupW - (barW * series.length + barGap * (series.length - 1))) / 2;
            series.forEach((s, si) => {
                const v = +s.data[li] || 0;
                const x = gx + si * (barW + barGap);
                const top = y(Math.max(v, 0));
                const hgt = Math.max(padT + ih - top, 0);
                const r = Math.min(4, barW / 2, hgt);       // rounded data-end, anchored baseline
                out += `<path d="M${x},${padT + ih} L${x},${top + r} Q${x},${top} ${x + r},${top} L${x + barW - r},${top} Q${x + barW},${top} ${x + barW},${top + r} L${x + barW},${padT + ih} Z" fill="${CHART_COLORS[si]}"><title>${esc(lab)} · ${esc(s.name || '')}: ${fmtNum(v)}</title></path>`;
                if (totalBars <= 8 && hgt > 0) {
                    out += `<text x="${x + barW / 2}" y="${top - 4}" font-size="9.5" fill="#52525B" text-anchor="middle" font-family="Consolas,monospace">${fmtNum(v)}</text>`;
                }
            });
            // x labels (trimmed)
            const short = lab.length > 9 ? lab.slice(0, 8) + '…' : lab;
            out += `<text x="${padL + li * groupW + groupW / 2}" y="${H - 8}" font-size="9.5" fill="${CHART_INK}" text-anchor="middle">${esc(short)}</text>`;
        });
        return out + '</svg>';
    }

    function lineSvg(labels, series) {
        const W = 360, H = 200, padL = 38, padR = 14, padT = 14, padB = 26;
        const iw = W - padL - padR, ih = H - padT - padB;
        const max = niceMax(Math.max(...series.flatMap(s => s.data.map(v => +v || 0)), 0));
        const x = ix => labels.length === 1 ? padL + iw / 2 : padL + (ix / (labels.length - 1)) * iw;
        const y = v => padT + ih - (v / max) * ih;
        let out = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
        for (let g = 1; g <= 4; g++) {
            const gy = padT + ih - (g / 4) * ih;
            out += `<line x1="${padL}" y1="${gy}" x2="${W - padR}" y2="${gy}" stroke="${CHART_GRID}" stroke-width="1"/>`;
            out += `<text x="${padL - 5}" y="${gy + 3}" font-size="9" fill="${CHART_INK}" text-anchor="end" font-family="Consolas,monospace">${fmtNum(max * g / 4)}</text>`;
        }
        out += `<line x1="${padL}" y1="${padT + ih}" x2="${W - padR}" y2="${padT + ih}" stroke="#D4D4D8" stroke-width="1"/>`;
        series.forEach((s, si) => {
            const pts = s.data.map((v, ix) => `${x(ix)},${y(+v || 0)}`).join(' ');
            out += `<polyline points="${pts}" fill="none" stroke="${CHART_COLORS[si]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
            s.data.forEach((v, ix) => {
                out += `<circle cx="${x(ix)}" cy="${y(+v || 0)}" r="3.5" fill="${CHART_COLORS[si]}" stroke="${CHART_SURFACE}" stroke-width="2"><title>${esc(labels[ix])} · ${esc(s.name || '')}: ${fmtNum(+v || 0)}</title></circle>`;
            });
            // direct label on the last point of each series
            const lv = +s.data[s.data.length - 1] || 0;
            out += `<text x="${Math.min(x(s.data.length - 1) + 6, W - 2)}" y="${y(lv) - 6}" font-size="9.5" fill="#52525B" font-family="Consolas,monospace">${fmtNum(lv)}</text>`;
        });
        // sparse x labels: first, middle, last
        [0, Math.floor((labels.length - 1) / 2), labels.length - 1].filter((v, ix, a) => a.indexOf(v) === ix).forEach(ix => {
            const short = labels[ix].length > 10 ? labels[ix].slice(0, 9) + '…' : labels[ix];
            out += `<text x="${x(ix)}" y="${H - 8}" font-size="9.5" fill="${CHART_INK}" text-anchor="middle">${esc(short)}</text>`;
        });
        return out + '</svg>';
    }

    function donutSvg(labels, s0) {
        const W = 360, H = 190, cx = W / 2, cy = H / 2, R = 66, r = 40;
        const vals = labels.map((_, ix) => Math.max(+s0.data[ix] || 0, 0));
        const total = vals.reduce((a, b) => a + b, 0);
        if (total <= 0) return '';
        let out = `<svg viewBox="0 0 ${W} ${H}" role="img">`;
        let a0 = -Math.PI / 2;
        vals.forEach((v, ix) => {
            const frac = v / total;
            const a1 = a0 + frac * Math.PI * 2;
            const large = frac > 0.5 ? 1 : 0;
            const p = (a, rad) => `${cx + rad * Math.cos(a)},${cy + rad * Math.sin(a)}`;
            out += `<path d="M${p(a0, R)} A${R},${R} 0 ${large} 1 ${p(a1, R)} L${p(a1, r)} A${r},${r} 0 ${large} 0 ${p(a0, r)} Z" fill="${CHART_COLORS[ix % CHART_COLORS.length]}" stroke="${CHART_SURFACE}" stroke-width="2"><title>${esc(labels[ix])}: ${fmtNum(v)} (${Math.round(frac * 100)}%)</title></path>`;
            if (frac >= 0.07) {
                const mid = (a0 + a1) / 2, lr = (R + r) / 2;
                out += `<text x="${cx + lr * Math.cos(mid)}" y="${cy + lr * Math.sin(mid) + 3}" font-size="9.5" fill="${CHART_LABEL_INK[ix % CHART_LABEL_INK.length]}" font-weight="700" text-anchor="middle" font-family="Consolas,monospace">${Math.round(frac * 100)}%</text>`;
            }
            a0 = a1;
        });
        out += `<text x="${cx}" y="${cy + 4}" font-size="12" fill="#18181B" text-anchor="middle" font-family="Consolas,monospace">${fmtNum(total)}</text>`;
        return out + '</svg>';
    }

    // Render any ```chart fences whose JSON is complete.
    function hydrateCharts(container) {
        container.querySelectorAll('.st-chartblock:not([data-done])').forEach(el => {
            if (el.getAttribute('data-closed') !== '1') return; // still streaming
            let spec = null;
            try { spec = JSON.parse(decodeURIComponent(el.getAttribute('data-spec'))); } catch (e) { /* not valid JSON */ }
            const html = spec ? buildChart(spec) : '';
            el.innerHTML = html || '<pre class="st-code"><code>chart: invalid spec</code></pre>';
            el.setAttribute('data-done', '1');
        });
    }

    // Extract chartable data from a rendered markdown table.
    // First column = labels; every column where most cells parse as numbers = a series.
    function tableToSpec(tableEl) {
        const head = Array.from(tableEl.querySelectorAll('thead th')).map(th => th.textContent.trim());
        const rows = Array.from(tableEl.querySelectorAll('tbody tr')).map(tr =>
            Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim()));
        if (head.length < 2 || !rows.length || rows.length > 14) return null;
        const parseNum = t => {
            const n = parseFloat(t.replace(/[,%$€£₹\s]/g, ''));
            return isFinite(n) ? n : null;
        };
        const series = [];
        for (let c = 1; c < head.length; c++) {
            const nums = rows.map(r => parseNum(r[c] || ''));
            const ok = nums.filter(n => n !== null).length;
            if (ok >= Math.max(2, Math.ceil(rows.length * 0.6))) {
                series.push({ name: head[c], data: nums.map(n => n === null ? 0 : n) });
            }
        }
        if (!series.length) return null;
        return { type: 'bar', labels: rows.map(r => r[0] || ''), series: series };
    }

    // After a message finishes streaming: add table<->chart toggles + copy action.
    function finalizeMessage(contentDiv, rawText) {
        hydrateCharts(contentDiv);

        contentDiv.querySelectorAll('.st-tblblock').forEach(block => {
            const table = block.querySelector('table');
            const spec = table && tableToSpec(table);
            if (!spec) return;
            const tools = document.createElement('div');
            tools.className = 'st-tbl-tools';
            tools.innerHTML = `
                <button class="st-vt on" data-v="table">${icon('table', 12)} table</button>
                <button class="st-vc" data-v="chart">${icon('chart', 12)} chart</button>`;
            const chartHost = document.createElement('div');
            chartHost.style.display = 'none';
            chartHost.innerHTML = buildChart(spec);
            const wrap = block.querySelector('.st-tablewrap');
            block.insertBefore(tools, wrap);
            block.appendChild(chartHost);
            const bT = tools.querySelector('.st-vt'), bC = tools.querySelector('.st-vc');
            bT.addEventListener('click', () => { wrap.style.display = ''; chartHost.style.display = 'none'; bT.classList.add('on'); bC.classList.remove('on'); });
            bC.addEventListener('click', () => { wrap.style.display = 'none'; chartHost.style.display = ''; bC.classList.add('on'); bT.classList.remove('on'); });
        });

        // copy-answer action
        const msg = contentDiv.closest('.st-msg');
        if (msg && !msg.querySelector('.st-msg-actions')) {
            const actions = document.createElement('div');
            actions.className = 'st-msg-actions';
            const btn = document.createElement('button');
            btn.className = 'st-act-btn';
            btn.innerHTML = `${icon('copy', 12)} copy`;
            btn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(rawText);
                    btn.innerHTML = `${icon('check', 12)} copied`;
                    setTimeout(() => { btn.innerHTML = `${icon('copy', 12)} copy`; }, 1500);
                } catch (e) { /* clipboard unavailable */ }
            });
            actions.appendChild(btn);
            msg.appendChild(actions);
        }
    }

    // ==================================================================
    // Chatbot logic
    // ==================================================================
    class StratumChatbot {
        constructor() {
            this.messages = [];
            this.isProcessing = false;

            // All lookups are scoped to the shadow root, not the host document.
            this.chatBubble = root.getElementById('stBubble');
            this.chatWindow = root.getElementById('stWindow');
            this.closeButton = root.getElementById('stClose');
            this.resetButton = root.getElementById('stReset');
            this.chatMessages = root.getElementById('stMsgs');
            this.chatInput = root.getElementById('stInput');
            this.sendButton = root.getElementById('stSend');
            this.micButton = root.getElementById('stMic');
            this.errorMessage = root.getElementById('stError');

            this.initVoice();
            this.init();
        }

        init() {
            this.chatBubble.addEventListener('click', () => this.toggleChat());
            this.chatBubble.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') this.toggleChat(); });
            this.closeButton.addEventListener('click', () => this.toggleChat());
            this.resetButton.addEventListener('click', () => this.resetConversation());
            this.sendButton.addEventListener('click', () => this.handleSend());
            this.chatInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !this.isProcessing) {
                    this.handleSend();
                }
            });

            // Suggestion chip handlers
            root.querySelectorAll('.st-chip').forEach(button => {
                button.addEventListener('click', (e) => {
                    this.chatInput.value = e.currentTarget.getAttribute('data-message');
                    this.handleSend();
                });
            });
        }

        // ---- Voice input (Web Speech API; button hidden when unsupported) ----
        initVoice() {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SR) { this.micButton.style.display = 'none'; return; }
            this.recognition = new SR();
            this.recognition.lang = CONFIG.VOICE_LANG;
            this.recognition.interimResults = true;
            this.recognition.continuous = false;
            this.listening = false;

            this.recognition.onresult = (ev) => {
                let text = '';
                for (const res of ev.results) text += res[0].transcript;
                this.chatInput.value = text;
            };
            this.recognition.onend = () => this.setListening(false);
            this.recognition.onerror = () => this.setListening(false);

            this.micButton.addEventListener('click', () => {
                if (this.listening) { this.recognition.stop(); return; }
                try {
                    this.chatInput.value = '';
                    this.recognition.start();
                    this.setListening(true);
                } catch (e) { this.setListening(false); }
            });
        }

        setListening(on) {
            this.listening = on;
            this.micButton.classList.toggle('listening', on);
            this.chatInput.placeholder = on ? 'Listening…' : 'Ask about your documents…';
        }

        toggleChat() {
            this.chatWindow.classList.toggle('active');
            this.chatBubble.classList.toggle('open');

            if (this.chatWindow.classList.contains('active')) {
                this.chatInput.focus();
            }
        }

        resetConversation() {
            if (this.isProcessing) return;
            this.messages = [];
            this.hideError();
            // Remove everything except the welcome section, then re-show it.
            Array.from(this.chatMessages.children).forEach(el => { if (el.id !== 'stWelcome') el.remove(); });
            const welcome = root.getElementById('stWelcome');
            if (welcome) welcome.style.display = '';
            this.chatInput.focus();
        }

        async handleSend() {
            const userMessage = this.chatInput.value.trim();

            if (!userMessage || this.isProcessing) return;
            if (this.listening && this.recognition) this.recognition.stop();

            this.chatInput.value = '';
            this.hideError();
            this.addMessage('user', userMessage);

            this.messages.push({
                role: 'user',
                content: userMessage
            });

            this.showTypingIndicator();
            this.setProcessing(true);

            try {
                const response = await fetch(CONFIG.API_URL, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${CONFIG.API_KEY}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        messages: this.messages
                    }),
                    signal: timeoutSignal(CONFIG.TIMEOUT)
                });

                if (!response.ok) {
                    throw new Error(`API error: ${response.status}`);
                }

                // Keep the typing indicator visible until the FIRST token actually
                // arrives, then swap it for the assistant bubble. This avoids the
                // "empty bubble" gap while Ollama is still doing prompt-eval.
                let assistantMessage = "";
                let contentDiv = null;

                // Parse SSE stream
                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop(); // keep incomplete line in buffer

                    for (const line of lines) {
                        if (line.trim() === '') continue;
                        if (line.startsWith('data: ')) {
                            const dataStr = line.slice(6);
                            if (dataStr === '[DONE]') break;
                            try {
                                const data = JSON.parse(dataStr);
                                if (data.content) {
                                    if (!contentDiv) {
                                        // First token: replace dots with the real bubble.
                                        this.hideTypingIndicator();
                                        const messageDiv = document.createElement('div');
                                        messageDiv.className = `st-msg assistant`;
                                        contentDiv = document.createElement('div');
                                        contentDiv.className = 'st-msg-content';
                                        messageDiv.appendChild(contentDiv);
                                        this.chatMessages.appendChild(messageDiv);
                                    }
                                    assistantMessage += data.content;
                                    contentDiv.innerHTML = renderMarkdown(assistantMessage);
                                    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                                }
                            } catch (e) {
                                console.error('SSE parse error:', e, dataStr);
                            }
                        }
                    }
                }

                // Safety: if the stream ended without any content, clear the indicator.
                this.hideTypingIndicator();

                if (contentDiv) {
                    finalizeMessage(contentDiv, assistantMessage);
                    this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
                }

                this.messages.push({
                    role: 'assistant',
                    content: assistantMessage
                });

            } catch (error) {
                console.error('Error:', error);
                this.hideTypingIndicator();

                let errorText = 'Failed to get response. Please try again.';
                if (error.name === 'TimeoutError' || error.name === 'AbortError') {
                    errorText = 'Request timed out. Please try again.';
                } else if (error.message.includes('Failed to fetch')) {
                    errorText = 'Cannot connect to server. Please check if the API is running.';
                }

                this.showError(errorText);
                this.messages.pop();
            } finally {
                this.setProcessing(false);
            }
        }

        addMessage(role, content) {
            // Hide the welcome section once a conversation begins.
            const welcome = root.getElementById('stWelcome');
            if (welcome) welcome.style.display = 'none';

            const messageDiv = document.createElement('div');
            messageDiv.className = `st-msg ${role}`;

            const contentDiv = document.createElement('div');
            contentDiv.className = 'st-msg-content';
            contentDiv.textContent = content;

            messageDiv.appendChild(contentDiv);
            this.chatMessages.appendChild(messageDiv);
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }

        showTypingIndicator() {
            const indicator = document.createElement('div');
            indicator.className = 'st-msg assistant';
            indicator.id = 'stTypingIndicator';

            const typingDiv = document.createElement('div');
            typingDiv.className = 'st-typing';
            typingDiv.innerHTML = '<span></span><span></span><span></span>';

            indicator.appendChild(typingDiv);
            this.chatMessages.appendChild(indicator);
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }

        hideTypingIndicator() {
            const indicator = root.getElementById('stTypingIndicator');
            if (indicator) indicator.remove();
        }

        showError(text) {
            this.errorMessage.textContent = text;
            this.errorMessage.classList.add('active');
        }

        hideError() {
            this.errorMessage.classList.remove('active');
        }

        setProcessing(processing) {
            this.isProcessing = processing;
            this.sendButton.disabled = processing;
            this.chatInput.disabled = processing;
        }
    }

    // Build the Shadow DOM host, inject styles + markup, and wire up the widget.
    // Runs only once the <body> is available.
    function boot() {
        const host = document.createElement('div');
        host.id = 'stratum-chatbot-host';
        document.body.appendChild(host);
        root = host.attachShadow({ mode: 'open' });

        const style = document.createElement('style');
        style.textContent = styleText;
        root.appendChild(style);

        const container = document.createElement('div');
        container.innerHTML = chatHTML;
        root.appendChild(container);

        const bot = new StratumChatbot();
        window.StratumOpen = function () {
            if (!bot.chatWindow.classList.contains('active')) bot.toggleChat();
        };
        // Open the widget and send a message programmatically (used by demo pages).
        window.StratumAsk = function (text) {
            window.StratumOpen();
            if (bot.isProcessing) return;
            bot.chatInput.value = String(text || '');
            bot.handleSend();
        };
    }

    // `document.currentScript` was already read above (synchronously); it's safe to
    // defer the DOM work until the body exists, even if the script is in <head>.
    if (document.body) {
        boot();
    } else {
        document.addEventListener('DOMContentLoaded', boot);
    }

})();
