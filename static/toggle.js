document.addEventListener('DOMContentLoaded', function () {
    var toggleButton = document.getElementById('sidebar-toggle');
    var sidebar = document.querySelector('.sidebar');
    var resizer = document.querySelector('.sidebar-resizer');
    var root = document.documentElement;
    var body = document.body;
    var storageKey = 'docgenSidebarWidth';
    var minWidth = 160;
    var maxWidth = 500;
    var startX = 0;
    var startWidth = 0;
    var currentWidth = 0;

    if (sidebar) {
        if (!resizer) {
            resizer = document.createElement('div');
            resizer.className = 'sidebar-resizer';
            resizer.setAttribute('aria-hidden', 'true');
            sidebar.insertAdjacentElement('afterend', resizer);
        }

        var computedRootStyles = getComputedStyle(root);
        minWidth = parseSize(computedRootStyles.getPropertyValue('--sidebar-min-width'), minWidth);
        maxWidth = parseSize(computedRootStyles.getPropertyValue('--sidebar-max-width'), maxWidth);

        var storedWidth = loadStoredWidth();
        var initialWidth = storedWidth !== null
            ? storedWidth
            : parseSize(getComputedStyle(sidebar).width, parseSize(computedRootStyles.getPropertyValue('--sidebar-width'), 220));

        setSidebarWidth(initialWidth);

        if (resizer) {
            resizer.setAttribute('aria-hidden', sidebar.classList.contains('hidden') ? 'true' : 'false');
            resizer.addEventListener('mousedown', startResize);
            resizer.addEventListener('touchstart', startResize, { passive: false });
        }
    }

    if (toggleButton && sidebar) {
        if (!sidebar.id) {
            sidebar.id = 'docgen-sidebar';
        }
        toggleButton.setAttribute('aria-controls', sidebar.id);
        toggleButton.setAttribute('aria-expanded', sidebar.classList.contains('hidden') ? 'false' : 'true');

        toggleButton.addEventListener('click', function () {
            var isHidden = sidebar.classList.toggle('hidden');
            toggleButton.setAttribute('aria-expanded', isHidden ? 'false' : 'true');
            if (resizer) {
                resizer.setAttribute('aria-hidden', isHidden ? 'true' : 'false');
            }
        });
    }

    // collapse all directories and expand current path
    document.querySelectorAll('.sidebar details').forEach(function (d) {
        d.open = false;
    });
    var current = document.querySelector(
        '.sidebar a[href="' + window.location.pathname.split('/').pop() + '"]'
    );
    if (current) {
        var el = current.parentElement;
        while (el) {
            if (el.tagName && el.tagName.toLowerCase() === 'details') {
                el.open = true;
            }
            el = el.parentElement;
        }
    }

    window.addEventListener('resize', function () {
        if (!sidebar) {
            return;
        }
        var clamped = clampWidth(currentWidth);
        if (clamped !== currentWidth) {
            setSidebarWidth(clamped);
        }
    });

    function startResize(event) {
        if (sidebar.classList.contains('hidden')) {
            return;
        }
        event.preventDefault();
        startX = getClientX(event);
        startWidth = sidebar.getBoundingClientRect().width;
        body.classList.add('sidebar-resizing');
        document.addEventListener('mousemove', handlePointerMove);
        document.addEventListener('mouseup', stopResize);
        document.addEventListener('touchmove', handlePointerMove, { passive: false });
        document.addEventListener('touchend', stopResize);
        document.addEventListener('touchcancel', stopResize);
    }

    function handlePointerMove(event) {
        if (event.cancelable) {
            event.preventDefault();
        }
        var delta = getClientX(event) - startX;
        var newWidth = clampWidth(startWidth + delta);
        setSidebarWidth(newWidth);
    }

    function stopResize() {
        document.removeEventListener('mousemove', handlePointerMove);
        document.removeEventListener('mouseup', stopResize);
        document.removeEventListener('touchmove', handlePointerMove);
        document.removeEventListener('touchend', stopResize);
        document.removeEventListener('touchcancel', stopResize);
        body.classList.remove('sidebar-resizing');
        if (!sidebar.classList.contains('hidden')) {
            saveWidth(currentWidth);
        }
    }

    function setSidebarWidth(width) {
        currentWidth = clampWidth(width);
        root.style.setProperty('--sidebar-width', currentWidth + 'px');
    }

    function clampWidth(width) {
        var maxAllowed = Math.min(maxWidth, Math.max(minWidth, window.innerWidth - 120));
        return Math.min(Math.max(width, minWidth), maxAllowed);
    }

    function parseSize(value, fallback) {
        var parsed = parseFloat(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    function getClientX(event) {
        if (event.touches && event.touches.length) {
            return event.touches[0].clientX;
        }
        return event.clientX;
    }

    function loadStoredWidth() {
        try {
            var stored = localStorage.getItem(storageKey);
            var parsed = parseFloat(stored);
            return Number.isFinite(parsed) ? parsed : null;
        } catch (err) {
            return null;
        }
    }

    function saveWidth(width) {
        try {
            localStorage.setItem(storageKey, String(width));
        } catch (err) {
            /* ignore persistence errors */
        }
    }
});
