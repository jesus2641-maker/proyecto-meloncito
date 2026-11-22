let confirmCallback = null;

function showConfirm(title, message, callback) {
    const modal = document.getElementById('confirmModal');
    const titleEl = document.getElementById('confirmTitle');
    const messageEl = document.getElementById('confirmMessage');
    if (!modal || !titleEl || !messageEl) return;

    titleEl.textContent = title;
    messageEl.textContent = message;
    modal.classList.add('modal-open');
    confirmCallback = callback;
}

document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('confirmModal');
    const cancelBtn = document.getElementById('confirmCancel');
    const okBtn = document.getElementById('confirmOk');
    if (!modal || !cancelBtn || !okBtn) return;

    function closeConfirmModal() {
        modal.classList.remove('modal-open');
        confirmCallback = null;
    }

    cancelBtn.addEventListener('click', closeConfirmModal);

    okBtn.addEventListener('click', function() {
        const cb = confirmCallback;
        closeConfirmModal();
        if (typeof cb === 'function') {
            cb();
        }
    });

    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeConfirmModal();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.classList.contains('modal-open')) {
            closeConfirmModal();
        }
    });
});
