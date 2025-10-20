(function () {
    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    function initCallgraph(figure) {
        var viewport = figure.querySelector('.callgraph-viewport');
        var svg = viewport ? viewport.querySelector('svg') : null;
        if (!viewport || !svg) {
            return;
        }

        var zoomInBtn = figure.querySelector('.callgraph-zoom-in');
        var zoomOutBtn = figure.querySelector('.callgraph-zoom-out');
        var resetBtn = figure.querySelector('.callgraph-zoom-reset');

        var state = {
            scale: 1,
            minScale: 0.4,
            maxScale: 3.5,
            translateX: 0,
            translateY: 0,
        };

        var pan = {
            active: false,
            pointerId: null,
            startX: 0,
            startY: 0,
            originX: 0,
            originY: 0,
        };

        function applyTransform() {
            svg.style.transform =
                'translate(' + state.translateX + 'px, ' + state.translateY + 'px) scale(' +
                state.scale + ')';
        }

        function setScale(newScale, focusEvent) {
            var scale = clamp(newScale, state.minScale, state.maxScale);
            var rect = viewport.getBoundingClientRect();
            var focusX = rect.left + rect.width / 2;
            var focusY = rect.top + rect.height / 2;

            if (focusEvent && typeof focusEvent.clientX === 'number') {
                focusX = focusEvent.clientX;
                focusY = focusEvent.clientY;
            }

            var offsetX = focusX - rect.left;
            var offsetY = focusY - rect.top;

            var currentSvgX = (offsetX - state.translateX) / state.scale;
            var currentSvgY = (offsetY - state.translateY) / state.scale;

            state.scale = scale;
            state.translateX = offsetX - currentSvgX * state.scale;
            state.translateY = offsetY - currentSvgY * state.scale;
            applyTransform();
        }

        function adjustZoom(step, focusEvent) {
            var nextScale = state.scale * step;
            setScale(nextScale, focusEvent);
        }

        function resetZoom() {
            state.scale = 1;
            state.translateX = 0;
            state.translateY = 0;
            applyTransform();
        }

        function onWheel(event) {
            event.preventDefault();
            var factor = event.deltaY > 0 ? 0.9 : 1.1;
            adjustZoom(factor, event);
        }

        function isInteractiveTarget(element) {
            if (!element) {
                return false;
            }
            return (
                element.closest('a') !== null ||
                element.closest('button') !== null ||
                element.closest('input') !== null ||
                element.closest('select') !== null ||
                element.closest('textarea') !== null
            );
        }

        function onPointerDown(event) {
            if (event.button !== 0) {
                return;
            }

            if (isInteractiveTarget(event.target)) {
                return;
            }
            pan.active = true;
            pan.pointerId = event.pointerId;
            pan.startX = event.clientX;
            pan.startY = event.clientY;
            pan.originX = state.translateX;
            pan.originY = state.translateY;
            viewport.classList.add('is-panning');
            viewport.setPointerCapture(event.pointerId);
        }

        function onPointerMove(event) {
            if (!pan.active || event.pointerId !== pan.pointerId) {
                return;
            }
            var deltaX = event.clientX - pan.startX;
            var deltaY = event.clientY - pan.startY;
            state.translateX = pan.originX + deltaX;
            state.translateY = pan.originY + deltaY;
            applyTransform();
        }

        function onPointerUp(event) {
            if (!pan.active || event.pointerId !== pan.pointerId) {
                return;
            }
            pan.active = false;
            pan.pointerId = null;
            viewport.classList.remove('is-panning');
            viewport.releasePointerCapture(event.pointerId);
        }

        function bindControl(button, handler) {
            if (!button) {
                return;
            }
            button.addEventListener('click', handler);
        }

        bindControl(zoomInBtn, function (event) {
            adjustZoom(1.2, event);
        });
        bindControl(zoomOutBtn, function (event) {
            adjustZoom(1 / 1.2, event);
        });
        bindControl(resetBtn, function () {
            resetZoom();
        });

        viewport.addEventListener('wheel', onWheel, { passive: false });
        viewport.addEventListener('pointerdown', onPointerDown);
        viewport.addEventListener('pointermove', onPointerMove);
        viewport.addEventListener('pointerup', onPointerUp);
        viewport.addEventListener('pointercancel', onPointerUp);
        viewport.addEventListener('pointerleave', function (event) {
            if (pan.active && event.pointerId === pan.pointerId) {
                onPointerUp(event);
            }
        });

        applyTransform();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            document.querySelectorAll('[data-callgraph]').forEach(initCallgraph);
        });
    } else {
        document.querySelectorAll('[data-callgraph]').forEach(initCallgraph);
    }
})();
