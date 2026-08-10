(function () {
  const chatBody = document.getElementById('chatBody');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const promptChips = document.querySelectorAll('.prompt-chip');

  const history = [];
  let waiting = false;  // one request in flight at a time, or replies interleave

  function addMessage(text, who) {
    const msg = document.createElement('div');
    msg.className = 'msg ' + who;
    msg.textContent = text;
    chatBody.appendChild(msg);
    chatBody.scrollTop = chatBody.scrollHeight;
    return msg;
  }

  function addTyping() {
    const msg = document.createElement('div');
    msg.className = 'msg bot typing';
    msg.innerHTML = '<span></span><span></span><span></span>';
    chatBody.appendChild(msg);
    chatBody.scrollTop = chatBody.scrollHeight;
    return msg;
  }

  async function sendMessage(text) {
    if (waiting) return;
    waiting = true;

    addMessage(text, 'user');
    history.push({ role: 'user', text });
    const typingEl = addTyping();

    try {
      const res = await fetch('/api/consultancy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await res.json();
      typingEl.remove();
      const reply = data.reply || "Sorry, I didn't quite catch that, could you rephrase?";
      addMessage(reply, 'bot');
      history.push({ role: 'assistant', text: reply });
    } catch (err) {
      typingEl.remove();
      addMessage('I ran into a connection hiccup. Mind trying that again in a moment?', 'bot');
    } finally {
      waiting = false;
    }
  }

  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput.value.trim();
    if (!text) return;
    chatInput.value = '';
    sendMessage(text);
  });

  promptChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const text = chip.getAttribute('data-prompt');
      sendMessage(text);
    });
  });
})();
