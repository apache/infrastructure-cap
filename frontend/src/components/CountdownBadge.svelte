<script lang="ts">
  import { onDestroy, onMount, createEventDispatcher } from "svelte";
  import {
    secondsRemaining,
    formatCountdown,
    formatCountdownAria,
    formatLocal,
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

  // The digits alone ("2d 0h") do not say what is being counted, and the
  // badge sits on a dashboard card with no surrounding label. A native
  // title tooltip (the app initializes no Bootstrap JS tooltips) names
  // the deadline the timer runs to, in the viewer's local time.
  $: tooltip =
    remaining > 0
      ? `Time left to respond. Voting closes ${formatLocal(closesAt)}.`
      : `Voting closed ${formatLocal(closesAt)}. Responses are no longer accepted.`;

  $: cls =
    remaining <= 0
      ? "bg-dark"
      : remaining < 3600
        ? "bg-danger"
        : remaining < 86400
          ? "bg-warning text-dark"
          : "bg-secondary";
</script>

<span
  class="badge countdown {cls}"
  title={tooltip}
  aria-label={formatCountdownAria(remaining)}
>
  <i class="fa-regular fa-clock me-1"></i>
  {formatCountdown(remaining)}
</span>

<style>
  /* Hints that there is something to hover for. */
  .countdown {
    cursor: help;
  }
</style>
