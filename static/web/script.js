function openModal(id) {
    document.getElementById(id).style.display = 'block';
}
 
function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}
 
// Switch from login to register
function openRegister() {
    closeModal('id01');
    openModal('id02');
}
 
// Close a modal when clicking on the dark background around it
window.addEventListener('click', function (event) {
    if (event.target.classList && event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
    }
});
 
// Close any open modal with the Escape key
document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
        document.querySelectorAll('.modal').forEach(function (m) {
            m.style.display = 'none';
        });
    }
});
 
