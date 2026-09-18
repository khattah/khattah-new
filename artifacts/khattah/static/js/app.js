document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".show-password").forEach((button) => {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.textContent = showing ? "Show" : "Hide";
    });
  });

  document.querySelectorAll(".flash button").forEach((button) => {
    button.addEventListener("click", () => button.parentElement.remove());
  });

  window.setTimeout(() => {
    document.querySelectorAll(".flash").forEach((flash) => {
      flash.style.transition = "opacity .25s ease, transform .25s ease";
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-8px)";
      window.setTimeout(() => flash.remove(), 260);
    });
  }, 5000);
});