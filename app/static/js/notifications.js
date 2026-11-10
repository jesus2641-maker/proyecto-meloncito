/**
 * BEER HOUSE — Sistema Unificado de Notificaciones y Validaciones
 * 
 * Centraliza:
 * 1. Notificaciones flotantes (Toasts / Flash messages)
 * 2. Reemplazo de tooltips nativos de validación HTML5
 * 3. Estados de validación en inputs (.is-invalid, .is-valid)
 * 4. Intercepción de window.alert
 */

(function () {
    'use strict';

    // Normaliza categorías a: 'success', 'error', 'warning', 'info'
    function normalizeType(type) {
        if (!type) return 'info';
        const t = String(type).toLowerCase().trim();
        if (t === 'danger' || t === 'critical' || t === 'err') return 'error';
        if (t === 'warn') return 'warning';
        if (t === 'ok') return 'success';
        return ['success', 'error', 'warning', 'info'].includes(t) ? t : 'info';
    }

    // Iconos SVG estilizados para cada categoría
    function getNotificationIconSvg(type) {
        switch (type) {
            case 'success':
                return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>';
            case 'error':
                return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>';
            case 'warning':
                return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>';
            case 'info':
            default:
                return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>';
        }
    }

    // Obtener o crear el contenedor flotante
    function getNotificationContainer() {
        let container = document.getElementById('notification-container');
        if (!container) {
            container = document.querySelector('.flash-messages');
        }
        if (!container) {
            container = document.createElement('div');
            container.id = 'notification-container';
            container.className = 'notification-container flash-messages';
            container.setAttribute('aria-live', 'polite');
            document.body.appendChild(container);
        }
        return container;
    }

    /**
     * Muestra una notificación flotante (toast) con estilo premium.
     * @param {string} message - Texto del mensaje
     * @param {string} type - 'success', 'error', 'danger', 'warning', 'info'
     * @param {number} duration - Duración en milisegundos (0 para permanente)
     */
    function showNotification(message, type = 'info', duration = 5000) {
        if (!message) return null;
        const normType = normalizeType(type);
        const container = getNotificationContainer();

        const toast = document.createElement('div');
        toast.className = `custom-notification custom-notification-${normType} flash-message flash-${normType}`;
        toast.setAttribute('role', normType === 'error' ? 'alert' : 'status');

        toast.innerHTML = `
            <div class="notification-content">
                <div class="notification-icon">${getNotificationIconSvg(normType)}</div>
                <div class="notification-message">${message}</div>
                <button type="button" class="notification-close flash-close" aria-label="Cerrar notificación">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
            ${duration > 0 ? '<div class="notification-progress"></div>' : ''}
        `;

        const closeBtn = toast.querySelector('.notification-close');
        let closeTimeout = null;
        let remainingTime = duration;
        let startTime = Date.now();

        function dismissToast() {
            if (toast.classList.contains('closing')) return;
            toast.classList.add('closing');
            setTimeout(() => {
                if (toast.parentElement) toast.remove();
            }, 300);
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                dismissToast();
            });
        }

        const progressEl = toast.querySelector('.notification-progress');
        if (duration > 0) {
            if (progressEl) {
                progressEl.style.transition = `transform ${duration}ms linear`;
                requestAnimationFrame(() => {
                    progressEl.style.transform = 'scaleX(0)';
                });
            }

            closeTimeout = setTimeout(dismissToast, duration);

            // Pausar en hover para que el usuario pueda leer con calma
            toast.addEventListener('mouseenter', () => {
                clearTimeout(closeTimeout);
                remainingTime -= (Date.now() - startTime);
                if (progressEl) {
                    const computed = window.getComputedStyle(progressEl).transform;
                    progressEl.style.transition = 'none';
                    progressEl.style.transform = computed;
                }
            });

            toast.addEventListener('mouseleave', () => {
                if (remainingTime > 0) {
                    startTime = Date.now();
                    if (progressEl) {
                        progressEl.style.transition = `transform ${remainingTime}ms linear`;
                        progressEl.style.transform = 'scaleX(0)';
                    }
                    closeTimeout = setTimeout(dismissToast, remainingTime);
                } else {
                    dismissToast();
                }
            });
        }

        container.appendChild(toast);
        return toast;
    }

    /* =====================================================
       SISTEMA DE TOOLTIPS DE VALIDACIÓN HTML5 PERSONALIZADOS
       ===================================================== */
    let activeTooltip = null;
    let activeInput = null;

    function removeValidationTooltip() {
        if (activeTooltip) {
            activeTooltip.remove();
            activeTooltip = null;
        }
        if (activeInput) {
            activeInput.classList.remove('is-invalid');
            activeInput = null;
        }
    }

    function positionTooltip(input, tooltip) {
        if (!input || !tooltip) return;
        const rect = input.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();

        const spaceBelow = window.innerHeight - rect.bottom;
        const spaceAbove = rect.top;

        let placement = 'bottom';
        let top = rect.bottom + 8;

        if (spaceBelow < (tooltipRect.height + 16) && spaceAbove > spaceBelow) {
            placement = 'top';
            top = rect.top - tooltipRect.height - 8;
        }

        // Alinear a la izquierda del input, respetando los límites del viewport
        let left = rect.left;
        const maxLeft = window.innerWidth - tooltipRect.width - 16;
        if (left > maxLeft) left = maxLeft;
        if (left < 16) left = 16;

        tooltip.className = `bh-validation-tooltip placement-${placement}`;
        tooltip.style.top = `${Math.round(top)}px`;
        tooltip.style.left = `${Math.round(left)}px`;

        // Ajustar la flecha para que apunte hacia el centro o inicio del input
        const arrow = tooltip.querySelector('.bh-validation-tooltip-arrow');
        if (arrow) {
            const arrowLeft = Math.max(14, Math.min(rect.left + 24 - left, tooltipRect.width - 24));
            arrow.style.left = `${Math.round(arrowLeft)}px`;
        }
    }

    function showValidationTooltip(input, customMessage) {
        removeValidationTooltip();

        const message = customMessage || input.validationMessage || 'Este campo es obligatorio o contiene un formato no válido.';
        if (!message) return;

        input.classList.add('is-invalid');
        activeInput = input;

        const tooltip = document.createElement('div');
        tooltip.className = 'bh-validation-tooltip placement-bottom';
        tooltip.setAttribute('role', 'alert');
        tooltip.setAttribute('aria-live', 'assertive');

        tooltip.innerHTML = `
            <div class="bh-validation-tooltip-arrow"></div>
            <div class="bh-validation-tooltip-icon">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
            </div>
            <div class="bh-validation-tooltip-text">${message}</div>
        `;

        document.body.appendChild(tooltip);
        activeTooltip = tooltip;

        positionTooltip(input, tooltip);

        // Descartar tooltip en cuanto el usuario empiece a corregir el campo
        function onUserChange() {
            if (input.checkValidity()) {
                removeValidationTooltip();
                input.removeEventListener('input', onUserChange);
                input.removeEventListener('change', onUserChange);
            } else if (activeTooltip) {
                const textEl = activeTooltip.querySelector('.bh-validation-tooltip-text');
                if (textEl && input.validationMessage) {
                    textEl.textContent = input.validationMessage;
                    positionTooltip(input, activeTooltip);
                }
            }
        }

        input.addEventListener('input', onUserChange);
        input.addEventListener('change', onUserChange);
    }

    // Interceptar el evento nativo 'invalid' en fase de captura para sustituir la burbuja nativa
    document.addEventListener('invalid', function (e) {
        const el = e.target;
        if (!el || !el.form) return;

        // Suprimir el popup nativo del navegador
        e.preventDefault();

        // Mostrar el tooltip únicamente en el primer elemento inválido del formulario
        const firstInvalid = el.form.querySelector(':invalid');
        if (el === firstInvalid) {
            try {
                el.focus({ preventScroll: true });
                el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (_) {
                el.focus();
            }
            showValidationTooltip(el);
        }
    }, true);

    // Cerrar tooltip si el usuario pulsa Escape o hace clic fuera
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && activeTooltip) {
            removeValidationTooltip();
        }
    });

    document.addEventListener('pointerdown', function (e) {
        if (activeTooltip && !activeTooltip.contains(e.target) && e.target !== activeInput) {
            removeValidationTooltip();
        }
    });

    // Reposicionar el tooltip en redimensión o scroll
    window.addEventListener('resize', function () {
        if (activeTooltip && activeInput) {
            positionTooltip(activeInput, activeTooltip);
        }
    });

    window.addEventListener('scroll', function () {
        if (activeTooltip && activeInput) {
            positionTooltip(activeInput, activeTooltip);
        }
    }, true);

    // Limpiar al enviar formulario exitosamente
    document.addEventListener('submit', function () {
        removeValidationTooltip();
    });

    /* =====================================================
       INICIALIZACIÓN DE MENSAJES FLASH RENDERIZADOS POR SERVIDOR
       ===================================================== */
    function initServerFlashes() {
        const flashes = document.querySelectorAll('.flash-message, .custom-notification');
        flashes.forEach(flash => {
            // Asegurar icono si no lo tiene
            const iconEl = flash.querySelector('.notification-icon');
            if (iconEl && !iconEl.innerHTML.trim()) {
                let type = 'info';
                if (flash.classList.contains('flash-danger') || flash.classList.contains('flash-error') || flash.classList.contains('custom-notification-danger') || flash.classList.contains('custom-notification-error')) {
                    type = 'error';
                } else if (flash.classList.contains('flash-warning') || flash.classList.contains('custom-notification-warning')) {
                    type = 'warning';
                } else if (flash.classList.contains('flash-success') || flash.classList.contains('custom-notification-success')) {
                    type = 'success';
                }
                iconEl.innerHTML = getNotificationIconSvg(type);
            }

            // Manejo de botón de cierre
            const closeBtn = flash.querySelector('.notification-close, .flash-close');
            if (closeBtn) {
                closeBtn.onclick = function (e) {
                    e.stopPropagation();
                    flash.classList.add('closing');
                    setTimeout(() => flash.remove(), 300);
                };
            }

            // Auto-cierre con temporizador y pausa al posar el cursor
            const autoClose = flash.getAttribute('data-auto-close') || '5000';
            const duration = parseInt(autoClose, 10);
            if (duration > 0) {
                let timer = null;
                let remaining = duration;
                let start = Date.now();

                function dismiss() {
                    flash.classList.add('closing');
                    setTimeout(() => flash.remove(), 300);
                }

                timer = setTimeout(dismiss, duration);

                flash.addEventListener('mouseenter', () => {
                    clearTimeout(timer);
                    remaining -= (Date.now() - start);
                });

                flash.addEventListener('mouseleave', () => {
                    if (remaining > 0) {
                        start = Date.now();
                        timer = setTimeout(dismiss, remaining);
                    } else {
                        dismiss();
                    }
                });
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initServerFlashes);
    } else {
        initServerFlashes();
    }

    // Exponer APIs de forma global
    window.showNotification = showNotification;
    window.showValidationTooltip = showValidationTooltip;
    window.removeValidationTooltip = removeValidationTooltip;
    window.alert = function (message) {
        showNotification(message, 'info');
    };
})();
