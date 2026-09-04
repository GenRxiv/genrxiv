const form = document.getElementById('interest-form');
const confirmMsg = document.getElementById('confirm-message');
form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const email = document.getElementById('email').value;
    const notify = document.getElementById('notify').checked;
    confirmMsg.classList.remove('error');
    confirmMsg.style.display = 'block';
    confirmMsg.textContent = 'Sending\u2026';
    try {
        const resp = await fetch('/api/signup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, notify_on_launch: notify }),
        });
        if (resp.ok) {
            confirmMsg.textContent = 'Thanks \u2014 we\'ll be in touch.';
            form.reset();
        } else {
            confirmMsg.classList.add('error');
            confirmMsg.textContent = 'Something went wrong. Please try again.';
        }
    } catch (err) {
        confirmMsg.classList.add('error');
        confirmMsg.textContent = 'Network error. Please try again.';
    }
});
