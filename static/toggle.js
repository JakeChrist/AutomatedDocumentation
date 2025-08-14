document.addEventListener('DOMContentLoaded', function () {
    var toggleButton = document.getElementById('sidebar-toggle');
    var sidebar = document.querySelector('.sidebar');
    if (toggleButton && sidebar) {
        toggleButton.addEventListener('click', function () {
            sidebar.classList.toggle('hidden');
        });
    }
});
