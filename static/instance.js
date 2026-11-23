const clock = document.getElementById("instance-clock");
const address = document.querySelector("[data-instance-url]");
address.textContent = address.href;
const deadline = performance.now() + Number(clock.dataset.seconds) * 1000;
function tick() {
  const left = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
  if (!left) {
    window.location.reload();
    return;
  }
  const seconds = String(left % 60).padStart(2, "0");
  clock.textContent = Math.floor(left / 60) + ":" + seconds;
  setTimeout(tick, 250);
}
tick();
