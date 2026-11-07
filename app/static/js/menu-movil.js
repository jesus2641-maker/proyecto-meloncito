/**
 * Menú móvil del sitio público (Beer House)
 * Abre y cierra el panel desplegable .nav en pantallas <= 768px.
 */
(function () {
    const BREAKPOINT_MOVIL = 768;

    function inicializarMenuMovil() {
        const toggleBtn = document.querySelector('.mobile-toggle');
        const nav = document.getElementById('main-nav') || document.querySelector('.header .nav');

        if (!toggleBtn || !nav) {
            return;
        }

        function estaAbierto() {
            return nav.classList.contains('is-open');
        }

        function abrirMenu() {
            nav.classList.add('is-open');
            toggleBtn.classList.add('is-active');
            toggleBtn.setAttribute('aria-expanded', 'true');
        }

        function cerrarMenu(devolverFoco) {
            if (!estaAbierto() && toggleBtn.getAttribute('aria-expanded') === 'false') {
                return;
            }
            nav.classList.remove('is-open');
            toggleBtn.classList.remove('is-active');
            toggleBtn.setAttribute('aria-expanded', 'false');
            if (devolverFoco) {
                toggleBtn.focus();
            }
        }

        toggleBtn.addEventListener('click', function () {
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

        // Restablecer al pasar de 768px de ancho
        window.addEventListener('resize', function () {
            if (window.innerWidth > BREAKPOINT_MOVIL && estaAbierto()) {
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
