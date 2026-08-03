const form = document.getElementById("form");
const error = document.getElementById("error");
const mode = form.dataset.mode;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const password = document.getElementById("password").value;
  if (mode === "setup") {
    const confirm = document.getElementById("confirm").value;
    if (password.length < 6) {
      error.textContent = "Password must be at least 6 characters.";
      return;
    }
    if (password !== confirm) {
      error.textContent = "Passwords do not match.";
      return;
    }
  }
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const response = await fetch(`/api/auth/${mode}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      error.textContent = payload.detail || "Something went wrong.";
      button.disabled = false;
      return;
    }
    window.location.href = "/";
  } catch (failure) {
    error.textContent = "Cannot reach the server.";
    button.disabled = false;
  }
});
