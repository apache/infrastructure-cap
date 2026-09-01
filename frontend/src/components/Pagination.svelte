<script lang="ts">
  // Page controls for a client-side paginated list. The parent owns the
  // current page (so each dashboard tab keeps its own) and slices its own
  // data; this component only renders the controls and reports clicks.
  //
  // Nothing is rendered at all when everything fits on one page, so a
  // caller can mount it unconditionally.
  export let page: number;
  export let total: number;
  export let pageSize: number;
  export let onChange: (page: number) => void;
  // Announced to screen readers, e.g. "Awaiting your response pages".
  export let label: string = "Pages";
  // A list is bracketed by two of these: one above the rows, so the
  // controls are visible without scrolling past a screenful of cards,
  // and one below, where the reader ends up after reading a page. The
  // variant only decides the separator and which copy announces itself
  // to a screen reader; both render the same controls.
  export let variant: "top" | "bottom" = "bottom";

  $: pageCount = Math.max(1, Math.ceil(total / pageSize));
  $: firstShown = total === 0 ? 0 : (page - 1) * pageSize + 1;
  $: lastShown = Math.min(page * pageSize, total);

  // A windowed page list: always the first and last page, the current
  // page and its immediate neighbours, and `null` where a run of pages
  // was elided (rendered as an ellipsis). Keeps the control a fixed width
  // no matter how deep the list gets.
  function pageWindow(current: number, count: number): (number | null)[] {
    const wanted = new Set([1, count, current - 1, current, current + 1]);
    const shown = [...wanted]
      .filter((p) => p >= 1 && p <= count)
      .sort((a, b) => a - b);
    const out: (number | null)[] = [];
    let previous = 0;
    for (const p of shown) {
      if (previous && p - previous > 1) out.push(null);
      out.push(p);
      previous = p;
    }
    return out;
  }

  $: pages = pageWindow(page, pageCount);

  function go(target: number): void {
    const clamped = Math.min(Math.max(target, 1), pageCount);
    if (clamped !== page) onChange(clamped);
  }
</script>

{#if pageCount > 1}
  <div
    class="d-flex flex-wrap justify-content-between align-items-center gap-2 {variant ===
    'top'
      ? 'border-bottom pb-2 mb-3'
      : 'border-top pt-3 mt-3'}"
  >
    <div
      class="small text-muted"
      aria-live={variant === "top" ? "polite" : undefined}
    >
      Showing {firstShown}-{lastShown} of {total}
      <span class="ms-1">(page {page} of {pageCount})</span>
    </div>
    <nav aria-label={label}>
      <ul class="pagination pagination-sm mb-0">
        <li class="page-item" class:disabled={page <= 1}>
          <button
            type="button"
            class="page-link"
            aria-label="Previous page"
            disabled={page <= 1}
            on:click={() => go(page - 1)}
          >
            <i class="fa-solid fa-chevron-left"></i>
          </button>
        </li>
        {#each pages as p}
          {#if p === null}
            <li class="page-item disabled">
              <span class="page-link">&hellip;</span>
            </li>
          {:else}
            <li class="page-item" class:active={p === page}>
              <button
                type="button"
                class="page-link"
                aria-label="Page {p}"
                aria-current={p === page ? "page" : undefined}
                on:click={() => go(p)}
              >
                {p}
              </button>
            </li>
          {/if}
        {/each}
        <li class="page-item" class:disabled={page >= pageCount}>
          <button
            type="button"
            class="page-link"
            aria-label="Next page"
            disabled={page >= pageCount}
            on:click={() => go(page + 1)}
          >
            <i class="fa-solid fa-chevron-right"></i>
          </button>
        </li>
      </ul>
    </nav>
  </div>
{/if}
