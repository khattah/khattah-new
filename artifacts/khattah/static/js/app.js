document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".show-password").forEach((button) => {
    button.addEventListener("click", () => {
      const input = button.parentElement.querySelector("input");
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.textContent = showing ? button.dataset.showLabel : button.dataset.hideLabel;
    });
  });

  document.querySelectorAll(".flash button").forEach((button) => {
    button.addEventListener("click", () => button.parentElement.remove());
  });

  document.querySelectorAll("[data-copy-link]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copyLink);
      button.textContent = button.dataset.copiedLabel || "Copied";
    });
  });
  document.querySelectorAll("[data-share-text]").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = button.dataset.shareText;
      const url = button.dataset.shareUrl;
      if (navigator.share) {
        await navigator.share({ text, url });
      } else {
        await navigator.clipboard.writeText(`${text}\n${url}`);
        button.textContent = button.dataset.copiedLabel || "Copied";
      }
    });
  });

  window.setTimeout(() => {
    document.querySelectorAll(".flash").forEach((flash) => {
      flash.style.transition = "opacity .25s ease, transform .25s ease";
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-8px)";
      window.setTimeout(() => flash.remove(), 260);
    });
  }, 5000);

  // Appearance Admin - Tabs
  const paletteTabs = document.querySelectorAll('.palette-tab');
  paletteTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.palette-tab, .palette-form').forEach(el => el.classList.remove('active'));
      tab.classList.add('active');
      const target = document.getElementById(tab.dataset.target);
      if (target) target.classList.add('active');
    });
  });

  // Appearance Admin - Color syncing and live preview
  document.querySelectorAll('form.palette-form').forEach(form => {
    const previewBox = form.querySelector('.preview-content');
    if (!previewBox) return;

    const updatePreview = () => {
      form.querySelectorAll('.color-hex').forEach(input => {
        const field = input.name;
        const varName = `--preview-${field.replace('_', '-')}`;
        previewBox.style.setProperty(varName, input.value);
      });
    };

    form.querySelectorAll('[data-color-picker]').forEach(picker => {
      const hexId = picker.dataset.colorPicker;
      const hexInput = form.querySelector(`[data-color-hex="${hexId}"]`);
      if (!hexInput) return;

      picker.addEventListener('input', () => {
        hexInput.value = picker.value.toUpperCase();
        updatePreview();
      });
      hexInput.addEventListener('input', () => {
        if (/^#[0-9A-Fa-f]{6}$/i.test(hexInput.value)) {
          picker.value = hexInput.value.toUpperCase();
          updatePreview();
        }
      });
    });
    // Init preview
    updatePreview();
  });
});