/**
 * Menú lateral móvil (drawer) para los paneles de Administrador y Trabajador.
 * Controla la apertura/cierre a <= 1024px, el overlay, tecla Esc y bloqueo de scroll del body.
 */
(function () {
    const BREAKPOINT_PANEL = 1024;

    function inicializarPanelMovil() {
        const toggleBtn = document.getElementById('panelMenuToggle') || document.querySelector('.panel-menu-toggle');
        const sidebar = document.getElementById('panel-sidebar') || document.querySelector('.admin-sidebar');
        const overlay = document.getElementById('panelSidebarOverlay') || document.querySelector('.panel-sidebar-overlay');

        if (!toggleBtn || !sidebar) {
            return;
        }

        function estaAbierto() {
            return sidebar.classList.contains('is-open');
        }

        function abrirDrawer() {
            sidebar.classList.add('is-open');
            if (overlay) {
                overlay.classList.add('is-open');
                overlay.setAttribute('aria-hidden', 'false');
            }
            document.body.classList.add('panel-drawer-open');
            toggleBtn.setAttribute('aria-expanded', 'true');
        }

        function cerrarDrawer(devolverFoco) {
            sidebar.classList.remove('is-open');
            if (overlay) {
                overlay.classList.remove('is-open');
                overlay.setAttribute('aria-hidden', 'true');
            }
            document.body.classList.remove('panel-drawer-open');
            toggleBtn.setAttribute('aria-expanded', 'false');
            if (devolverFoco) {
                toggleBtn.focus();
            }
        }

        toggleBtn.addEventListener('click', function () {
            if (estaAbierto()) {
                cerrarDrawer(false);
            } else {
                abrirDrawer();
            }
        });

        // Cerrar al tocar el overlay oscuro
        if (overlay) {
            overlay.addEventListener('click', function () {
                cerrarDrawer(false);
            });
        }

        // Cerrar al tocar un enlace dentro del sidebar
        const enlaces = sidebar.querySelectorAll('a');
        enlaces.forEach(function (enlace) {
            enlace.addEventListener('click', function () {
                if (window.innerWidth <= BREAKPOINT_PANEL) {
                    cerrarDrawer(false);
                }
            });
        });

        // Cerrar con la tecla Escape
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && estaAbierto()) {
                cerrarDrawer(true);
            }
        });

        // Al pasar de 1024px se restablece todo
        window.addEventListener('resize', function () {
            if (window.innerWidth > BREAKPOINT_PANEL && (estaAbierto() || document.body.classList.contains('panel-drawer-open'))) {
                cerrarDrawer(false);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', inicializarPanelMovil);
    } else {
        inicializarPanelMovil();
    }
})();
