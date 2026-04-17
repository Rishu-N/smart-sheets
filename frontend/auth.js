// SmartSheet — Auth module (Phase 3: name entry + OTP screens)

let currentRequestId = null;
let countdownTimer = null;
let countdownSeconds = 0;

// ─── Screen Management ──────────────────────────────────────

function showNameScreen() {
    document.getElementById('auth-container').style.display = 'flex';
    document.getElementById('name-screen').style.display = 'block';
    document.getElementById('otp-screen').style.display = 'none';
    document.getElementById('app-container').style.display = 'none';
    document.getElementById('auth-error').textContent = '';

    const nameInput = document.getElementById('name-input');
    nameInput.value = '';
    nameInput.focus();
}

function showOTPScreen(requestId, expiresIn) {
    currentRequestId = requestId;
    document.getElementById('name-screen').style.display = 'none';
    document.getElementById('otp-screen').style.display = 'block';
    document.getElementById('otp-error').textContent = '';

    // Clear OTP inputs
    const inputs = document.querySelectorAll('.otp-digit');
    inputs.forEach(inp => { inp.value = ''; });
    inputs[0]?.focus();

    // Start countdown
    startCountdown(expiresIn);
}

function showSpreadsheet() {
    document.getElementById('auth-container').style.display = 'none';
    document.getElementById('app-container').style.display = 'flex';

    if (countdownTimer) {
        clearInterval(countdownTimer);
        countdownTimer = null;
    }
}

// ─── API Calls ──────────────────────────────────────────────

async function requestAccess(name) {
    const errorEl = document.getElementById('auth-error');
    errorEl.textContent = '';

    try {
        const res = await fetch('/auth/request', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });

        if (res.status === 429) {
            errorEl.textContent = 'Too many requests. Please wait a moment.';
            return;
        }

        const data = await res.json();
        if (!res.ok) {
            errorEl.textContent = data.detail || 'Request failed';
            return;
        }

        showOTPScreen(data.request_id, data.expires_in);
    } catch (err) {
        errorEl.textContent = 'Connection error. Is the server running?';
    }
}

async function verifyOTP(requestId, otp) {
    const errorEl = document.getElementById('otp-error');
    errorEl.textContent = '';

    try {
        const res = await fetch('/auth/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ request_id: requestId, otp }),
            credentials: 'same-origin',
        });

        const data = await res.json();

        if (data.status === 'ok') {
            // Session cookie set by server
            showSpreadsheet();
            return;
        }

        if (data.status === 'locked_out') {
            errorEl.textContent = `Too many wrong attempts. Try again in ${data.retry_after} seconds.`;
            setTimeout(() => showNameScreen(), 3000);
            return;
        }

        if (data.status === 'expired') {
            errorEl.textContent = 'Code expired. Please request a new one.';
            setTimeout(() => showNameScreen(), 2000);
            return;
        }

        if (data.attempts_remaining !== undefined) {
            errorEl.textContent = `Wrong code. ${data.attempts_remaining} attempt(s) remaining.`;
            // Clear inputs for retry
            const inputs = document.querySelectorAll('.otp-digit');
            inputs.forEach(inp => { inp.value = ''; });
            inputs[0]?.focus();
            return;
        }

        errorEl.textContent = data.error || 'Verification failed';
    } catch (err) {
        errorEl.textContent = 'Connection error.';
    }
}

// ─── Countdown ──────────────────────────────────────────────

function startCountdown(seconds) {
    if (countdownTimer) clearInterval(countdownTimer);
    countdownSeconds = seconds;
    updateCountdownDisplay();

    countdownTimer = setInterval(() => {
        countdownSeconds--;
        updateCountdownDisplay();

        if (countdownSeconds <= 0) {
            clearInterval(countdownTimer);
            countdownTimer = null;
            document.getElementById('otp-error').textContent = 'Code expired. Request a new one.';
            setTimeout(() => showNameScreen(), 2000);
        }
    }, 1000);
}

function updateCountdownDisplay() {
    const el = document.getElementById('otp-countdown');
    if (!el) return;
    const min = Math.floor(countdownSeconds / 60);
    const sec = countdownSeconds % 60;
    el.textContent = `${min}:${sec.toString().padStart(2, '0')}`;
}

// ─── Event Listeners ────────────────────────────────────────

function setupAuthListeners() {
    // Name screen
    document.getElementById('request-btn').addEventListener('click', () => {
        const name = document.getElementById('name-input').value.trim();
        if (name.length >= 2 && name.length <= 32) {
            requestAccess(name);
        } else {
            document.getElementById('auth-error').textContent = 'Name must be 2-32 characters.';
        }
    });

    document.getElementById('name-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('request-btn').click();
        }
    });

    // OTP digit inputs — auto-advance and auto-submit
    const otpInputs = document.querySelectorAll('.otp-digit');
    otpInputs.forEach((input, idx) => {
        input.addEventListener('input', (e) => {
            const val = e.target.value;
            if (val.length === 1 && idx < otpInputs.length - 1) {
                otpInputs[idx + 1].focus();
            }

            // Auto-submit when all 6 digits filled
            const otp = Array.from(otpInputs).map(i => i.value).join('');
            if (otp.length === 6) {
                verifyOTP(currentRequestId, otp);
            }
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !input.value && idx > 0) {
                otpInputs[idx - 1].focus();
            }
        });

        // Allow paste of full OTP
        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = (e.clipboardData || window.clipboardData).getData('text').trim();
            if (/^\d{6}$/.test(text)) {
                otpInputs.forEach((inp, i) => { inp.value = text[i]; });
                verifyOTP(currentRequestId, text);
            }
        });
    });

    // Verify button
    document.getElementById('verify-btn').addEventListener('click', () => {
        const otp = Array.from(otpInputs).map(i => i.value).join('');
        if (otp.length === 6) {
            verifyOTP(currentRequestId, otp);
        } else {
            document.getElementById('otp-error').textContent = 'Enter all 6 digits.';
        }
    });

    // Back to name screen
    document.getElementById('otp-back-btn')?.addEventListener('click', () => {
        showNameScreen();
    });
}

// ─── Init ───────────────────────────────────────────────────

async function initAuth() {
    setupAuthListeners();

    try {
        // Check if we're the host or have an existing session
        const res = await fetch('/auth/whoami');
        const data = await res.json();

        if (data.is_host) {
            // Host — go straight to spreadsheet
            showSpreadsheet();
            return;
        }

        if (data.open_access) {
            // Open LAN mode — no auth required
            showSpreadsheet();
            return;
        }

        if (data.has_session) {
            // Valid session exists — go to spreadsheet
            showSpreadsheet();
            return;
        }

        // No session — show name screen
        showNameScreen();
    } catch (err) {
        console.error('Auth init error:', err);
        showNameScreen();
    }
}

export { initAuth, showSpreadsheet, showNameScreen };
