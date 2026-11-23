const lines = Array.from(document.querySelector("#boot").children);
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
  lines.forEach((line, index) => {
    line.style.visibility = "hidden";
    setTimeout(() => { line.style.visibility = "visible"; }, (index + 1) * 1800);
  });
}
setTimeout(() => location.replace(document.querySelector("#enter").href), 11000);
