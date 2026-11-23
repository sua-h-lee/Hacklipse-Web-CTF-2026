const form = document.getElementById("pilot-start");
const output = document.getElementById("pilot-output");
async function start() {
  form.hidden = true;
  output.textContent = "테스트 환경을 시작하는 중…";
  try {
    const response = await fetch(form.action, {method:"POST", body:new FormData(form)});
    const data = await response.json();
    if (response.ok && data.solved) {
      location.reload();
      return;
    }
    if (!response.ok || !data.sample) throw new Error();
    output.textContent = data.sample;
  } catch {
    output.textContent = "환경을 열지 못했습니다. 다시 시도해 주세요.";
    form.hidden = false;
  }
}
form.addEventListener("submit", event => { event.preventDefault(); start(); });
start();
