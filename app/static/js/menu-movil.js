/**
 * Menú móvil del sitio público (Beer House)
 * Abre y cierra el panel desplegable .nav en pantallas < 1200px (incluyendo 175% de zoom).
 */
(function () {
    const BREAKPOINT_MOVIL = 1200;

    function inicializarMenuMovil() {
        const toggleBtn = document.querySelector('.mobile-toggle');
        const nav = document.getElementById('main-nav') || document.querySelector('.header .nav');

        if (!toggleBtn || !nav) {
            return;
        }

        function estaAbierto() {
            return nav.classList.contains('is-open') || nav.classList.contains('show');
        }

        function abrirMenu() {
            nav.classList.add('is-open');
            nav.classList.add('show');
            toggleBtn.classList.add('is-active');
            toggleBtn.setAttribute('aria-expanded', 'true');
        }

        function cerrarMenu(devolverFoco) {
            if (!estaAbierto() && toggleBtn.getAttribute('aria-expanded') === 'false') {
                return;
            }
            nav.classList.remove('is-open');
            nav.classList.remove('show');
            toggleBtn.classList.remove('is-active');
            toggleBtn.setAttribute('aria-expanded', 'false');
            if (devolverFoco) {
                toggleBtn.focus();
            }
        }

        toggleBtn.addEventListener('click', function (e) {
            if (estaAbierto()) {
                cerrarMenu(false);
            } else {
                abrirMenu();
            }
        });

        // Cerrar al pulsar cualquier enlace del menú
        const enlaces = nav.querySelectorAll('a');
        enlaces.forEach(function (enlace) {
            enlace.addEventListener('click', function () {
                cerrarMenu(false);
            });
        });

        // Cerrar con la tecla Escape
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && estaAbierto()) {
                cerrarMenu(true);
            }
        });

        // Restablecer al pasar del breakpoint de colapso (>= 1200px)
        window.addEventListener('resize', function () {
            if (window.innerWidth >= BREAKPOINT_MOVIL && estaAbierto()) {
                cerrarMenu(false);
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', inicializarMenuMovil);
    } else {
        inicializarMenuMovil();
    }
})();
