(() => {
  let openDialog = null;

  window.appConfirm = ({ title, message, confirmLabel = 'Confirm' }) => new Promise((resolve) => {
    if (openDialog || typeof HTMLDialogElement === 'undefined' || !HTMLDialogElement.prototype.showModal) {
      resolve(false);
      return;
    }

    const dialog = document.createElement('dialog');
    dialog.className = 'app-confirm-dialog';
    dialog.innerHTML = `
      <form method="dialog">
        <h2></h2>
        <p></p>
        <div class="app-confirm-actions">
          <button type="submit" value="cancel" class="secondary-button">Cancel</button>
          <button type="submit" value="confirm"></button>
        </div>
      </form>
    `;
    dialog.querySelector('h2').textContent = title;
    dialog.querySelector('p').textContent = message;
    dialog.querySelector('[value="confirm"]').textContent = confirmLabel;
    document.body.append(dialog);
    openDialog = dialog;
    dialog.addEventListener('close', () => {
      const confirmed = dialog.returnValue === 'confirm';
      dialog.remove();
      openDialog = null;
      resolve(confirmed);
    }, { once: true });
    dialog.showModal();
    dialog.querySelector('[value="cancel"]').focus();
  });

  document.querySelectorAll('form[data-confirm-title]').forEach((form) => {
    form.querySelector('[data-confirm-trigger]')?.addEventListener('click', async () => {
      if (form.dataset.confirming === 'true') return;
      form.dataset.confirming = 'true';
      try {
        if (await window.appConfirm({
          title: form.dataset.confirmTitle,
          message: form.dataset.confirmMessage,
          confirmLabel: form.dataset.confirmLabel,
        })) {
          HTMLFormElement.prototype.submit.call(form);
        }
      } finally {
        form.dataset.confirming = 'false';
      }
    });
  });
})();
