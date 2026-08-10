(function () {
  const form = document.getElementById('checkoutForm');
  const confirmBox = document.getElementById('confirmBox');
  const submitBtn = document.getElementById('submitBtn');

  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';

    const data = Object.fromEntries(new FormData(form).entries());

    try {
      const res = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json();

      if (result.ok) {
        confirmBox.innerHTML = `Thanks, ${escapeHtml(data.contact_name)}! We've received your request for <strong>${escapeHtml(result.tier_label)}</strong> (booking ref <strong>${result.reference}</strong>) and will reach out on <strong>${escapeHtml(data.email)}</strong> within one business day.`;
        confirmBox.classList.add('show');
        form.reset();
        submitBtn.textContent = 'Request sent';
        confirmBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } else {
        throw new Error(result.error || 'Something went wrong');
      }
    } catch (err) {
      confirmBox.style.background = 'rgba(205,92,92,0.12)';
      confirmBox.style.borderColor = 'rgba(205,92,92,0.4)';
      confirmBox.style.color = '#8a3030';
      confirmBox.textContent = 'We could not send that just now, please try again in a moment or email hello@circlpk.com directly.';
      confirmBox.classList.add('show');
      submitBtn.disabled = false;
      submitBtn.textContent = 'Confirm booking request';
    }
  });

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
  }
})();
