import Dashboard from "./pages/Dashboard.svelte";
import NewQuestion from "./pages/NewQuestion.svelte";
import QuestionView from "./pages/QuestionView.svelte";
import EditQuestion from "./pages/EditQuestion.svelte";
import Resolution from "./pages/Resolution.svelte";
import About from "./pages/About.svelte";
import NotFound from "./pages/NotFound.svelte";

export const routes = {
  "/": Dashboard,
  "/about": About,
  "/question/new": NewQuestion,
  "/question/:id": QuestionView,
  "/question/:id/edit": EditQuestion,
  "/resolution/:id": Resolution,
  "*": NotFound,
};
