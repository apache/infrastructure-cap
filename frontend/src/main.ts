import "./styles/theme.scss";
import "./styles/icons.scss";
import "bootstrap/dist/js/bootstrap.bundle.min.js";

import { mount } from "svelte";
import App from "./App.svelte";

const target = document.getElementById("app");
if (!target) {
  throw new Error("CAP frontend: #app element not found in index.html");
}

const app = mount(App, { target });

export default app;
