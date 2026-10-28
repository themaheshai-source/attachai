/* AttachAI website widget. The public client ID is an identifier, never a secret credential. */
(() => {
  'use strict';
  const script = document.currentScript;
  if (!script) return;
  const clientId = (script.dataset.clientId || '').trim();
  if (!clientId) { console.error('AttachAI widget: missing data-client-id'); return; }
  const apiBase = new URL(script.src, window.location.href).origin;
  if (document.querySelector(`[data-attachai-widget-root="${CSS.escape(clientId)}"]`)) return;

  const host = document.createElement('div');
  host.dataset.attachaiWidgetRoot = clientId;
  host.style.cssText = 'position:fixed;z-index:2147483000;bottom:18px;right:18px;left:auto;font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = `
    :host{all:initial}
    .launcher{width:58px;height:58px;border:0;border-radius:20px;color:#fff;background:var(--primary,#6558e8);box-shadow:0 8px 28px #10102b35;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:25px;transition:transform .16s,box-shadow .16s;font-family:inherit}
    .launcher:hover{transform:translateY(-2px);box-shadow:0 12px 34px #10102b45}
    .panel{position:absolute;bottom:73px;right:0;width:var(--panel-width,360px);height:var(--panel-height,520px);max-width:calc(100vw - 24px);max-height:calc(100vh - 105px);display:none;flex-direction:column;background:var(--surface,#fff);color:var(--text,#24263c);border:1px solid var(--border,#e8e8f0);border-radius:18px;overflow:hidden;box-shadow:0 22px 72px #11122b30}
    .panel.open{display:flex}
    .head{background:var(--primary,#6558e8);color:#fff;padding:17px 17px 15px;display:flex;gap:12px;align-items:center;flex-shrink:0}
    .brand-dot{width:36px;height:36px;background:#ffffff25;border-radius:12px;display:grid;place-items:center;font-weight:850;font-size:15px}
    .brand-copy{min-width:0;flex:1}.brand-name{font-weight:800;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.brand-status{font-size:10px;opacity:.85;margin-top:4px}
    .close{border:0;background:#ffffff20;color:#fff;width:30px;height:30px;border-radius:9px;font-size:19px;cursor:pointer}
    .messages{flex:1;min-height:0;overflow:auto;padding:16px 13px;display:flex;flex-direction:column;gap:12px;background:var(--surface,#fff)}
    .msg{max-width:89%;padding:11px 12px;border-radius:12px;font-size:12px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
    .msg.bot{align-self:flex-start;background:var(--muted-bg,#f2f3f8);color:var(--text,#24263c);border-bottom-left-radius:4px}.msg.user{align-self:flex-end;background:var(--primary,#6558e8);color:#fff;border-bottom-right-radius:4px}
    .suggestions{display:flex;flex-wrap:wrap;gap:7px;margin-top:2px}.suggestion{background:transparent;border:1px solid var(--primary,#6558e8);color:var(--primary,#6558e8);border-radius:99px;padding:7px 9px;font-size:10px;cursor:pointer;max-width:100%;text-align:left}
    .composer{padding:12px;border-top:1px solid var(--border,#e8e8f0);display:flex;gap:8px;background:var(--surface,#fff);flex-shrink:0}
    .entry{min-width:0;flex:1;resize:none;border:1px solid var(--border,#dedfea);background:var(--surface,#fff);color:var(--text,#24263c);border-radius:11px;padding:11px 12px;font-family:inherit;font-size:12px;line-height:1.4;outline:none;max-height:90px}
    .entry:focus{border-color:var(--primary,#6558e8)}.send{flex-shrink:0;width:42px;border:0;border-radius:11px;background:var(--primary,#6558e8);color:#fff;font-size:18px;cursor:pointer}.send:disabled{opacity:.5;cursor:wait}
    .contact-link{border:0;border-top:1px solid var(--border,#e8e8f0);background:var(--surface,#fff);color:var(--primary,#6558e8);padding:9px 12px;font-family:inherit;font-size:10px;font-weight:700;cursor:pointer;text-align:center;flex-shrink:0}
    .lead-form{min-height:0;overflow:auto;padding:18px 14px;display:flex;flex-direction:column;gap:12px;background:var(--surface,#fff);flex:1}.lead-form[hidden]{display:none}.lead-title{font-size:14px;font-weight:800}.lead-copy{font-size:11px;line-height:1.6;color:var(--hint,#858aa0);margin-top:-5px}
    .lead-field{display:flex;flex-direction:column;gap:5px;font-size:10px;font-weight:750}.lead-field input,.lead-field textarea{width:100%;min-width:0;border:1px solid var(--border,#dedfea);border-radius:8px;padding:10px;background:var(--surface,#fff);color:var(--text,#24263c);font:12px/1.4 inherit}.lead-field textarea{min-height:70px;resize:vertical;font-family:inherit}.consent{display:flex;gap:8px;align-items:flex-start;font-size:10px;line-height:1.5;color:var(--hint,#858aa0)}.consent input{margin-top:2px}.lead-submit{border:0;border-radius:9px;background:var(--primary,#6558e8);color:white;padding:11px;font-weight:750;font-size:11px;cursor:pointer}.lead-submit:disabled{opacity:.5}.lead-success{padding:14px;background:var(--muted-bg,#f2f3f8);border-radius:10px;font-size:12px;line-height:1.6;color:var(--text,#24263c)}
    .foot{font-size:9px;text-align:center;color:var(--hint,#8b90a4);padding:0 10px 8px;background:var(--surface,#fff);flex-shrink:0}.typing{color:var(--hint,#8b90a4);font-size:11px;padding:0 4px}.error{align-self:flex-start;color:#b73543;background:#fff0f0;border-radius:9px;padding:9px;font-size:11px}
    .panel.dark{--surface:#202133;--text:#f3f3fa;--border:#3a3c50;--muted-bg:#303246;--hint:#a4a7bd;color:var(--text)}
    @media(max-width:480px){.panel{position:fixed;inset:8px;width:auto!important;height:auto!important;max-width:none;max-height:none;border-radius:15px;bottom:8px;right:8px;left:8px;top:8px}}
  `;

  const panel = document.createElement('section');
  panel.className = 'panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'AttachAI chat assistant');
  const launcher = document.createElement('button');
  launcher.className = 'launcher';
  launcher.type = 'button';
  launcher.setAttribute('aria-label', 'Open chat assistant');
  launcher.setAttribute('aria-expanded', 'false');
  launcher.textContent = '✦';
  host.append(style, panel, launcher);
  document.documentElement.appendChild(host);

  let config = null;
  let sessionId = sessionStorage.getItem(`attachai_session_${clientId}`) || '';
  let sending = false;
  let hasWelcomed = false;
  let messageInput = null;
  let messageSend = null;
  let messages = null;
  let contactLink = null;
  let leadPanel = null;
  let composer = null;

  function node(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  }
  function setStyle() {
    if (!config) return;
    const w = config.widget || {};
    const color = /^#[0-9a-fA-F]{6}$/.test(w.primary_color || '') ? w.primary_color : '#6558e8';
    host.style.right = w.position === 'left' ? 'auto' : '18px';
    host.style.left = w.position === 'left' ? '18px' : 'auto';
    host.style.bottom = '18px';
    host.style.setProperty('--primary', color);
    panel.style.setProperty('--panel-width', `${Math.min(520, Math.max(300, Number(w.width) || 360))}px`);
    panel.style.setProperty('--panel-height', `${Math.min(760, Math.max(360, Number(w.height) || 520))}px`);
    if (w.theme === 'dark') panel.classList.add('dark'); else panel.classList.remove('dark');
  }
  function addMessage(role, text) {
    const bubble = node('div', `msg ${role === 'user' ? 'user' : 'bot'}`, String(text || ''));
    messages.appendChild(bubble);
    messages.scrollTop = messages.scrollHeight;
    return bubble;
  }
  function showChat() {
    messages.hidden = false;
    composer.hidden = false;
    contactLink.hidden = false;
    leadPanel.hidden = true;
    if (messageInput) messageInput.focus();
  }
  function showLeadForm() {
    messages.hidden = true;
    composer.hidden = true;
    contactLink.hidden = true;
    leadPanel.hidden = false;
  }
  function buildLeadForm() {
    const section = node('div', 'lead-form');
    section.hidden = true;
    section.append(node('div', 'lead-title', 'Request a follow-up'));
    section.append(node('div', 'lead-copy', 'Share your contact details and the business team can get back to you.'));
    const form = node('form', 'lead-fields');
    form.style.cssText = 'display:flex;flex-direction:column;gap:12px;';
    const name = node('input'); name.name = 'name'; name.maxLength = 120; name.required = true; name.autocomplete = 'name'; name.placeholder = 'Your name';
    const email = node('input'); email.name = 'email'; email.type = 'email'; email.maxLength = 254; email.required = true; email.autocomplete = 'email'; email.placeholder = 'you@example.com';
    const phone = node('input'); phone.name = 'phone'; phone.type = 'tel'; phone.maxLength = 50; phone.autocomplete = 'tel'; phone.placeholder = 'Optional';
    const message = node('textarea'); message.name = 'message'; message.maxLength = 2000; message.placeholder = 'How can we help? (optional)';
    function field(label, input) { const box = node('label', 'lead-field', label); box.appendChild(input); return box; }
    form.append(field('Name *', name), field('Email *', email), field('Phone', phone), field('Message', message));
    const consentLabel = node('label', 'consent');
    const consent = node('input'); consent.type = 'checkbox'; consent.required = true; consent.name = 'consent';
    consentLabel.append(consent, node('span', '', 'I agree to be contacted about this enquiry.'));
    const submit = node('button', 'lead-submit', 'Send contact request'); submit.type = 'submit';
    form.append(consentLabel, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (submit.disabled) return;
      submit.disabled = true; submit.textContent = 'Sending…';
      try {
        const response = await fetch(`${apiBase}/api/client/leads`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            client_id: clientId, name: name.value, email: email.value, phone: phone.value,
            message: message.value, consent: consent.checked,
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || 'The contact request could not be sent.');
        section.replaceChildren(node('div', 'lead-success', data.message || 'Thank you. Your contact request has been submitted.'));
        section.appendChild(backButton);
      } catch (error) {
        const prior = section.querySelector('.error');
        if (prior) prior.remove();
        section.insertBefore(node('div', 'error', error.message || 'Unable to submit the request.'), form);
      } finally {
        submit.disabled = false; submit.textContent = 'Send contact request';
      }
    });
    const backButton = node('button', 'contact-link', '← Back to chat');
    backButton.type = 'button';
    backButton.addEventListener('click', showChat);
    section.appendChild(form);
    section.appendChild(backButton);
    return section;
  }
  function buildPanel() {
    panel.replaceChildren();
    const head = node('div', 'head');
    head.append(node('div', 'brand-dot', '✦'));
    const copy = node('div', 'brand-copy');
    copy.append(node('div', 'brand-name', config.name || 'Assistant'), node('div', 'brand-status', 'Here to help'));
    head.append(copy);
    const close = node('button', 'close', '×');
    close.type = 'button'; close.setAttribute('aria-label', 'Close chat');
    close.addEventListener('click', () => { panel.classList.remove('open'); launcher.setAttribute('aria-expanded', 'false'); });
    head.append(close);

    messages = node('div', 'messages');
    composer = node('form', 'composer');
    messageInput = node('textarea', 'entry');
    messageInput.rows = 1; messageInput.maxLength = 12000; messageInput.placeholder = 'Type your message…';
    messageInput.setAttribute('aria-label', 'Your message');
    messageSend = node('button', 'send', '➤');
    messageSend.type = 'submit'; messageSend.setAttribute('aria-label', 'Send message');
    composer.append(messageInput, messageSend);
    composer.addEventListener('submit', event => { event.preventDefault(); submitMessage(messageInput.value, messageInput, messageSend); });
    messageInput.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); composer.requestSubmit(); } });

    contactLink = node('button', 'contact-link', 'Want a follow-up? Leave your details');
    contactLink.type = 'button'; contactLink.addEventListener('click', showLeadForm);
    leadPanel = buildLeadForm();
    panel.append(head, messages, contactLink, leadPanel, composer, node('div', 'foot', 'Powered by AttachAI'));
    if (!hasWelcomed) {
      addMessage('bot', config.welcome_message || 'Hi! How can I help you today?');
      hasWelcomed = true;
    }
    const suggestions = (config.widget?.suggested_questions || []).slice(0, 6);
    if (suggestions.length) {
      const wrap = node('div', 'suggestions');
      suggestions.forEach(question => {
        const button = node('button', 'suggestion', question);
        button.type = 'button';
        button.addEventListener('click', () => submitMessage(question, messageInput, messageSend));
        wrap.appendChild(button);
      });
      messages.appendChild(wrap);
    }
    setStyle();
  }
  async function submitMessage(raw, input, send) {
    const text = String(raw || '').trim();
    if (!text || sending) return;
    sending = true;
    if (input) input.value = '';
    if (send) send.disabled = true;
    addMessage('user', text);
    const typing = addMessage('bot', 'Thinking…');
    typing.classList.add('typing');
    try {
      const response = await fetch(`${apiBase}/api/client/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: clientId, message: text, session_id: sessionId || null }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'The assistant could not respond.');
      sessionId = data.session_id || sessionId;
      if (sessionId) sessionStorage.setItem(`attachai_session_${clientId}`, sessionId);
      typing.remove();
      addMessage('assistant', data.answer || config.fallback_message || 'Please contact the business team for help.');
    } catch (error) {
      typing.remove();
      messages.appendChild(node('div', 'error', error.message || 'Unable to connect. Please try again.'));
    } finally {
      sending = false;
      if (send) send.disabled = false;
      messages.scrollTop = messages.scrollHeight;
      if (input) input.focus();
    }
  }
  launcher.addEventListener('click', () => {
    if (!config) return;
    panel.classList.toggle('open');
    launcher.setAttribute('aria-expanded', panel.classList.contains('open') ? 'true' : 'false');
    if (panel.classList.contains('open')) { if (!panel.firstChild) buildPanel(); setStyle(); }
  });

  fetch(`${apiBase}/api/client/config?client_id=${encodeURIComponent(clientId)}`, { headers: { 'Accept': 'application/json' } })
    .then(async response => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `Configuration request failed (${response.status})`);
      return data;
    })
    .then(data => {
      config = data; setStyle(); launcher.title = `Chat with ${config.name || 'us'}`;
      launcher.setAttribute('aria-label', `Chat with ${config.name || 'assistant'}`);
    })
    .catch(error => {
      host.remove();
      console.warn('AttachAI widget was not initialized:', error.message);
    });
})();
