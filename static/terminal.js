const initial = JSON.parse(document.querySelector('#initial').textContent);
const csrf = JSON.parse(document.querySelector('#csrf').textContent);
const passage = document.querySelector('#passage');
const form = document.querySelector('form');
const input = document.querySelector('#flag');
const button = form.querySelector('button');
const message = document.querySelector('#message');
let timer, target = '', currentAttribution = null, typing = false;
let completed = false;
function showAttribution() {
  const attribution = document.querySelector('#attribution');
  attribution.textContent = currentAttribution || '';
  attribution.hidden = !currentAttribution;
  document.querySelector('#congratulations').hidden = !currentAttribution;
  if (currentAttribution) message.hidden = true;
}
function finish() {
  if (!typing) return;
  clearInterval(timer);
  passage.textContent = target;
  passage.classList.remove('typing');
  typing = false;
  showAttribution();
}
function update(data, animate) {
  finish();
  completed = data.count === 15;
  input.disabled = completed;
  button.disabled = completed;
  form.hidden = completed;
  document.querySelector('#count').textContent = String(data.count).padStart(2, '0');
  document.querySelector('#mode').textContent = data.count === 15 ? 'RECOVERY COMPLETE' : 'AWAITING SIGNAL';
  document.querySelector('#empty').hidden = data.count > 0;
  currentAttribution = data.attribution;
  target = data.parts.join('');
  if (!animate || matchMedia('(prefers-reduced-motion: reduce)').matches) {
    passage.textContent = target; showAttribution(); return;
  }
  let position = passage.textContent.length;
  typing = true;
  passage.classList.add('typing');
  timer = setInterval(() => {
    position += 2;
    passage.textContent = target.slice(0, position);
    if (position >= target.length) finish();
  }, 24);
}
passage.addEventListener('click', finish);
document.addEventListener('keydown', event => {
  if (event.code === 'Space' && !event.target.closest('input,textarea,button,select,[contenteditable]') && typing) {
    event.preventDefault(); finish();
  }
});
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (completed || button.disabled) return;
  button.disabled = true;
  message.classList.remove('error');
  message.classList.remove('feedback');
  message.textContent = 'VERIFYING…';
  try {
    const response = await fetch('/submit', {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({flag:input.value})});
    const data = await response.json();
    message.textContent = data.message;
    message.classList.add('feedback');
    message.classList.toggle('error', !response.ok);
    if (response.ok) { update(data, data.fresh); input.value = ''; }
  } catch {
    message.textContent = '연결 오류 — 다시 제출해주세요.';
    message.classList.add('error');
  } finally {
    button.disabled = completed;
    if (!completed) input.focus();
  }
});
update(initial, false);
