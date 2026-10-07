
    function openRegister() {
        document.getElementById('id01').style.display = 'none';
        document.getElementById('id02').style.display = 'block';
    }

   
    window.onclick = function(event) {

        const loginModal = document.getElementById('id01');
        const registerModal = document.getElementById('id02');

        if (event.target === loginModal) {
            loginModal.style.display = 'none';
        }

        if (event.target === registerModal) {
            registerModal.style.display = 'none';
        }

    };