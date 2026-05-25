import "./styles/theme.scss";
import "./styles/icons.scss";
import "bootstrap/dist/js/bootstrap.bundle.min.js";

import App from "./App.svelte";

const target = document.getElementById("app");
if (!target) {
  throw new Error("CAP frontend: #app element not found in index.html");
}

const app = new App({ target });

export default app;
