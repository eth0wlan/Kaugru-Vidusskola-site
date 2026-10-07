// ---------- Модальные окна ----------

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

// ---------- Отправка форм в Flask ----------

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
            alert("Welcome, " + result.username + "!");
            form.closest(".modal").style.display = "none";
            updateAccountButton();
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

// ---------- Кнопка Account ----------

async function updateAccountButton() {
    const btn = document.getElementById("account-btn");
    if (!btn) return;

    try {
        const res = await fetch("/api/me");
        const { username } = await res.json();

        if (username) {
            btn.textContent = username + " (Logout)";
            btn.onclick = async () => {
                await fetch("/api/logout", { method: "POST" });
                location.reload();
            };
        }
    } catch (err) {
        console.error(err);
    }
}

updateAccountButton();