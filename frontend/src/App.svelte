<script lang="ts">
  import { onMount } from "svelte";
  import Router from "svelte-spa-router";
  import { routes } from "./routes";
  import NavBar from "./components/NavBar.svelte";
  import Footer from "./components/Footer.svelte";
  import ToastHost from "./components/ToastHost.svelte";
  import { loadSession } from "./lib/auth";

  onMount(() => {
    void loadSession();
  });
</script>

<NavBar />
<main>
  <div class="container">
    <Router {routes} />
  </div>
</main>
<Footer />
<ToastHost />
