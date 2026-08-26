import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

/**
 * The browser's own menu, off.
 *
 * This is a desktop application. "Reload", "Back" and "Inspect Element" are verbs of the
 * frame rather than of the thing being shown, and offering them on a node teaches a person
 * that right-clicking here belongs to somebody else. Where we have a menu of our own, it is
 * put there instead (`Menu.tsx`).
 *
 * A field is the exception and stays native: copy, paste, and the system's own spelling and
 * substitution live there, and replacing them would be taking something away.
 */
document.addEventListener("contextmenu", (event) => {
  const target = event.target;
  const editable =
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.isContentEditable);
  if (!editable) event.preventDefault();
});

/**
 * The browser's own navigation, off.
 *
 * A dropped file would replace the whole application with that file, and a middle-click or a
 * swipe would try to go "back" to a page that never existed. Neither is reachable on purpose;
 * both are reachable by accident.
 */
for (const name of ["dragover", "drop"]) {
  document.addEventListener(name, (event) => event.preventDefault());
}

const container = document.getElementById("root");
if (!container) throw new Error("#root missing from index.html");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
