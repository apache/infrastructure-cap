<script lang="ts">
  import { link } from "svelte-spa-router";
  import { session } from "../lib/stores";
  import { config } from "../lib/config";
  import { loginUrl } from "../lib/auth";

  function logoutHref(): string {
    const base = `${config.API_BASE}/auth?logout`;
    return base;
  }
</script>

<nav class="navbar navbar-expand-md navbar-dark bg-dark">
  <div class="container">
    <a class="navbar-brand d-flex align-items-center" href="/" use:link>
      <img src="/feather.svg" alt="" class="feather" />
      <span>{config.PRODUCT_NAME}</span>
    </a>
    <button
      class="navbar-toggler"
      type="button"
      data-bs-toggle="collapse"
      data-bs-target="#mainNav"
      aria-controls="mainNav"
      aria-expanded="false"
      aria-label="Toggle navigation"
    >
      <span class="navbar-toggler-icon"></span>
    </button>
    <div class="collapse navbar-collapse" id="mainNav">
      <ul class="navbar-nav me-auto mb-2 mb-md-0">
        <li class="nav-item">
          <a class="nav-link" href="/" use:link>
            <i class="fa-solid fa-list-check me-1"></i> Dashboard
          </a>
        </li>
        {#if $session.status === "ready" && $session.user.projects.length > 0}
          <li class="nav-item">
            <a class="nav-link" href="/question/new" use:link>
              <i class="fa-solid fa-circle-plus me-1"></i> New question
            </a>
          </li>
        {/if}
      </ul>
      <ul class="navbar-nav">
        {#if $session.status === "ready"}
          <li class="nav-item dropdown">
            <button
              type="button"
              class="nav-link dropdown-toggle btn btn-link"
              data-bs-toggle="dropdown"
              aria-expanded="false"
            >
              <i class="fa-solid fa-user me-1"></i>
              {$session.user.fullname || $session.user.uid}
              {#if $session.user.isRoot}
                <span class="badge bg-danger ms-1">root</span>
              {/if}
            </button>
            <ul class="dropdown-menu dropdown-menu-end">
              <li>
                <h6 class="dropdown-header">
                  Logged in as <code>{$session.user.uid}</code>
                </h6>
              </li>
              <li>
                <span class="dropdown-item-text small text-muted">
                  Projects: {$session.user.projects.length === 0
                    ? "(none)"
                    : $session.user.projects.join(", ")}
                </span>
              </li>
              <li>
                <span class="dropdown-item-text small text-muted">
                  Committees: {$session.user.committees.length === 0
                    ? "(none)"
                    : $session.user.committees.join(", ")}
                </span>
              </li>
              <li><hr class="dropdown-divider" /></li>
              <li>
                <a class="dropdown-item" href={logoutHref()}>
                  <i class="fa-solid fa-right-from-bracket me-1"></i> Logout
                </a>
              </li>
            </ul>
          </li>
        {:else if $session.status === "anonymous"}
          <li class="nav-item">
            <a class="nav-link" href={loginUrl()}>
              <i class="fa-solid fa-right-to-bracket me-1"></i> Login
            </a>
          </li>
        {:else if $session.status === "loading"}
          <li class="nav-item">
            <span class="nav-link text-secondary">
              <i class="fa-solid fa-circle-notch fa-spin me-1"></i> Loading
            </span>
          </li>
        {/if}
      </ul>
    </div>
  </div>
</nav>
