// ===================== Модальные окна =====================

function openModal(id) {
    document.getElementById(id).style.display = "block";
}

function closeModal(id) {
    document.getElementById(id).style.display = "none";
}

function openRegister() {
    closeModal("id01");
    openModal("id02");
}

// Закрытие по клику на тёмный фон вокруг формы
window.addEventListener("click", e => {
    if (e.target.classList.contains("modal")) {
        e.target.style.display = "none";
    }
});


// ===================== Вход и регистрация =====================

// Что делать после любого успешного входа (пароль, регистрация, Google)
function afterLogin(result) {
    if (result.is_admin) {
        location.href = "/admin";
        return;
    }
    document.querySelectorAll(".modal").forEach(m => { m.style.display = "none"; });
    updateAccountButton();
}

async function sendForm(form, url) {
    const data = Object.fromEntries(new FormData(form));
    data.remember = form.querySelector('[name="remember"]')?.checked || false;

    try {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });
        const result = await res.json();

        if (result.ok) {
            form.reset();
            afterLogin(result);
        } else {
            alert(result.error);
        }
    } catch (err) {
        alert("Server error, try again later");
        console.error(err);
    }
}

document.querySelector("#id01 form")?.addEventListener("submit", e => {
    e.preventDefault();
    sendForm(e.target, "/api/login");
});

document.querySelector("#id02 form")?.addEventListener("submit", e => {
    e.preventDefault();
    sendForm(e.target, "/api/register");
});


// ===================== Вход через Google =====================

function loadScript(src) {
    return new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        s.async = true;
        s.onload = resolve;
        s.onerror = reject;
        document.head.append(s);
    });
}

async function onGoogleSignIn(response) {
    try {
        const res = await fetch("/api/auth/google", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ credential: response.credential })
        });
        const result = await res.json();

        if (result.ok) {
            afterLogin(result);
        } else {
            alert(result.error);
        }
    } catch (err) {
        alert("Server error, try again later");
        console.error(err);
    }
}

async function initGoogleSignIn() {
    const box = document.getElementById("google-btn");
    if (!box) return;

    try {
        // Client ID берётся с сервера — в HTML его вписывать не нужно
        const cfg = await (await fetch("/api/config")).json();
        if (!cfg.google_client_id) return;          // Google не настроен — кнопки просто нет

        await loadScript("https://accounts.google.com/gsi/client");
        google.accounts.id.initialize({
            client_id: cfg.google_client_id,
            callback: onGoogleSignIn
        });
        google.accounts.id.renderButton(box, {
            type: "standard",
            theme: "outline",
            size: "large",
            text: "signin_with",
            width: 300
        });
        box.hidden = false;
        box.style.display = "flex";
    } catch (err) {
        console.error("Google sign-in unavailable:", err);
    }
}


// ===================== Кнопка Account =====================

async function updateAccountButton() {
    const btn = document.getElementById("account-btn");
    if (!btn) return;

    try {
        const res = await fetch("/api/me");
        const { username, is_admin } = await res.json();

        if (username) {
            btn.textContent = username + " (Logout)";
            btn.onclick = async () => {
                await fetch("/api/logout", { method: "POST" });
                location.reload();
            };

            // Ссылка на админку в меню — только для админов
            if (is_admin && !document.getElementById("admin-link")) {
                const li = document.createElement("li");
                const a = document.createElement("a");
                a.id = "admin-link";
                a.href = "/admin";
                a.textContent = "Admin";
                li.append(a);
                btn.closest("li").before(li);
            }
        }
    } catch (err) {
        console.error(err);
    }
}


// ===================== Запуск =====================

updateAccountButton();
initGoogleSignIn();