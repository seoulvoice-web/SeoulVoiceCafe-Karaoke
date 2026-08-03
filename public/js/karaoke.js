document.addEventListener('DOMContentLoaded', () => {
  const startBtn = document.getElementById('startBtn');
  const lines = Array.from(document.querySelectorAll('#lyrics p'));
  let idx = 0;
  let timer = null;

  function highlight(i) {
    lines.forEach((l, j) => l.classList.toggle('active', j === i));
  }

  startBtn.addEventListener('click', () => {
    if (timer) {
      clearInterval(timer);
      timer = null;
      startBtn.textContent = 'Iniciar karaoke';
      highlight(-1);
      idx = 0;
      return;
    }
    startBtn.textContent = 'Detener karaoke';
    highlight(0);
    idx = 0;
    timer = setInterval(() => {
      idx++;
      if (idx >= lines.length) {
        clearInterval(timer);
        timer = null;
        startBtn.textContent = 'Iniciar karaoke';
        return;
      }
      highlight(idx);
    }, 3000);
  });
});
