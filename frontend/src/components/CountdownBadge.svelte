<script lang="ts">
  import { onDestroy, onMount, createEventDispatcher } from "svelte";
  import {
    secondsRemaining,
    formatCountdown,
    formatCountdownAria,
  } from "../lib/time";

  export let closesAt: string;
  export let initialSeconds: number | null = null;

  const dispatch = createEventDispatcher<{ closed: void }>();
  let remaining = initialSeconds ?? secondsRemaining(closesAt);
  let interval: ReturnType<typeof setInterval> | null = null;
  let lastWasZero = remaining <= 0;

  function tick() {
    remaining = secondsRemaining(closesAt);
    if (!lastWasZero && remaining <= 0) {
      lastWasZero = true;
      dispatch("closed");
    }
  }

  onMount(() => {
    interval = setInterval(tick, 1000);
  });
  onDestroy(() => {
    if (interval) clearInterval(interval);
  });

  $: cls =
    remaining <= 0
      ? "bg-dark"
      : remaining < 3600
        ? "bg-danger"
        : remaining < 86400
          ? "bg-warning text-dark"
          : "bg-secondary";
</script>

<span class="badge {cls}" aria-label={formatCountdownAria(remaining)}>
  <i class="fa-regular fa-clock me-1"></i>
  {formatCountdown(remaining)}
</span>
